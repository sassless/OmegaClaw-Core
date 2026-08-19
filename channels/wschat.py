"""Minimal JSON chat adapter over WebSocket.

Connects to a chat server that speaks a small JSON frame format and exposes
an inbox/outbox surface: ``start_websocket`` / ``stop_websocket`` /
``send_message`` / ``getLastMessage``.

Connection
----------
URL and optional bearer token are read from ``WS_URL`` / ``WS_TOKEN``, or
passed to ``start_websocket`` directly. When a token is present it is sent
as ``Authorization: Bearer <token>``. The adapter reconnects automatically
with exponential backoff (1s -> 30s, +/-20% jitter) and is safe to start
once at process startup.

Frames
------
All frames are UTF-8 JSON objects with a ``type`` field; unknown types are
logged and ignored.

Server -> client:

  ``{"type": "user_message", "seq": <int>, "text": <str>}``
      A new inbound message. ``seq`` is a monotonically increasing integer
      assigned by the server; the client uses it for ordering and dedup.

  ``{"type": "ack", "seq": <int|null>, "client_seq": <str>}``
      Acknowledges a previously sent ``agent_message`` identified by
      ``client_seq``. Informational; logged only.

  ``{"type": "error", "code": <str>, "message": <str>}``
      Server-side error. Logged; the connection is left open.

Client -> server:

  ``{"type": "agent_message", "client_seq": <str>, "text": <str>}``
      A message produced by the local agent. ``client_seq`` is a
      client-generated idempotency key (UUID hex) so the server can dedupe
      retries after reconnect.

  ``{"type": "resume", "last_seen_seq": <int|null>}``
      Sent immediately after every (re)connect. The server should replay
      any ``user_message`` frames with ``seq > last_seen_seq``; on the
      first connection ``last_seen_seq`` is null.

Delivery semantics
------------------
- Inbound messages are buffered in a bounded inbox (256 entries) and drained
  by ``getLastMessage``, which joins pending texts with ``' | '`` and
  advances ``last_seen_seq``.
- Outbound messages sent while disconnected are queued in a bounded outbox
  (100 entries) and flushed after the next successful connect, before any
  new inbound traffic is processed.
- Duplicate ``user_message`` frames (``seq <= last_seen_seq``, or already in
  the inbox) are dropped, so server replays after resume are idempotent.
"""

import json
import os
import random
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
import sys
from config import config_get_by_key

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.logger import get_logger
import chat_attachments
try:
    import channels
except ModuleNotFoundError:
    import src.channels as channels

logger = get_logger(__name__)

AttachmentDownloadError = chat_attachments.AttachmentDownloadError
AttachmentDescriptor = chat_attachments.AttachmentDescriptor

_running = False
_thread = None
_ws = None
_connected = False

_state_lock = threading.Lock()
_send_lock = threading.Lock()
_msg_lock = threading.Lock()

_ws_url = ""
_ws_token = ""
_inbox = deque(maxlen=256)
_outbox = deque(maxlen=100)
_last_seen_seq = None
_upload_cleanup_enabled = False
_pending_lock = threading.Lock()
_pending_sends = {}
ATTACHMENT_VERDICT_TIMEOUT_SECONDS = 10
_last_upload_cleanup_at = None
_upload_cleanup_interval_seconds = 24 * 60 * 60
_upload_cleanup_stop_event = threading.Event()
_upload_cleanup_thread = None
_max_attachments_per_message = 3


@dataclass(frozen=True, slots=True)
class InboundMessage:
    seq: int
    text: str
    attachments: tuple[AttachmentDescriptor, ...] = ()


def _download_attachment(
    attachment,
    *,
    seq,
    ws_url=None,
    ws_token=None,
    upload_root=chat_attachments.UPLOAD_ROOT,
):
    return chat_attachments.download_attachment(
        attachment,
        seq=seq,
        ws_url=_ws_url if ws_url is None else ws_url,
        ws_token=_ws_token if ws_token is None else ws_token,
        upload_root=upload_root,
    )


def _download_attachment_with_retries(
    attachment: AttachmentDescriptor, *, seq, attempts=3
):
    last_error = None
    for attempt in range(attempts):
        try:
            return _download_attachment(attachment, seq=seq)
        except AttachmentDownloadError as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(0.25 * (2**attempt))
    raise last_error


def _render_attachment(message: InboundMessage, attachment: AttachmentDescriptor):
    header = (
        f"User attached {attachment.filename} ({attachment.content_type}, "
        f"{attachment.size_bytes} bytes; id={attachment.id})."
    )
    if not attachment.available:
        return f"{header}\nAttachment unavailable: retention expired or file revoked."

    try:
        local_path = _download_attachment_with_retries(attachment, seq=message.seq)
    except AttachmentDownloadError as exc:
        return f"{header}\nAttachment download error: {exc}"

    result = chat_attachments.process_attachment(local_path, attachment.content_type)
    lines = [header, f"Original file: {result.original_path}"]
    if result.derived_text_path is not None and result.derived_text_path != result.original_path:
        lines.append(f"Extracted text: {result.derived_text_path}")
    if result.error is not None:
        lines.append(f"Attachment processing error: {result.error}")
    return "\n".join(lines)


def _render_inbound_message(message: InboundMessage):
    if not message.attachments:
        return message.text

    lines = [f"[Message seq={message.seq}]"]
    lines.extend(
        _render_attachment(message, attachment) for attachment in message.attachments
    )
    lines.append(f"User request: {message.text}")
    return "\n".join(lines)


def _maybe_cleanup_uploads(*, force=False):
    global _last_upload_cleanup_at
    if not _upload_cleanup_enabled:
        return

    now = time.monotonic()
    if (
        not force
        and _last_upload_cleanup_at is not None
        and now - _last_upload_cleanup_at < _upload_cleanup_interval_seconds
    ):
        return
    _last_upload_cleanup_at = now
    try:
        result = chat_attachments.cleanup_upload_root()
        if result.removed_files:
            logger.info(
                "Attachment cleanup removed %d files; %d bytes remain",
                result.removed_files,
                result.remaining_bytes,
            )
    except Exception as exc:
        logger.warning("Attachment cleanup failed (%s)", type(exc).__name__)


def _upload_cleanup_loop():
    while _running:
        if _upload_cleanup_stop_event.wait(_upload_cleanup_interval_seconds):
            return
        if not _running:
            return
        _maybe_cleanup_uploads(force=True)


def _ensure_websockets_available():
    from websockets.sync.client import connect  # noqa: F401


def _connect_client(ws_url, ws_token):
    from websockets.sync.client import connect

    headers = {}
    if ws_token:
        headers["Authorization"] = f"Bearer {ws_token}"
    kwargs = {
        "open_timeout": 15,
        "close_timeout": 5,
        "ping_interval": 20,
        "ping_timeout": 20,
        "max_size": 64 * 1024,
    }

    try:
        return connect(ws_url, additional_headers=headers, **kwargs)
    except TypeError as e:
        logger.warning(f"additional_headers unsupported, retrying with extra_headers: {e}")
        return connect(ws_url, extra_headers=headers, **kwargs)  # for websockets<=4.14


def _resolve_connection_inputs(ws_url=None, ws_token=None):
    resolved_url = str(ws_url or os.environ.get("WS_URL", "")).strip()
    resolved_token = str(ws_token or os.environ.get("WS_TOKEN", "")).strip()

    if not resolved_url:
        raise ValueError("WS_URL is required")

    return resolved_url, resolved_token


def _build_resume_frame():
    with _msg_lock:
        return {"type": "resume", "last_seen_seq": _last_seen_seq}


def _set_connection(ws):
    global _ws, _connected
    with _state_lock:
        _ws = ws
        _connected = True


def _clear_connection(ws=None):
    global _ws, _connected
    with _state_lock:
        if ws is not None and _ws is not ws:
            return
        _ws = None
        _connected = False


def _send_json(payload, ws=None):
    target_ws = ws
    if target_ws is None:
        with _state_lock:
            target_ws = _ws

    if target_ws is None:
        raise RuntimeError("WebSocket channel is not connected")

    message = json.dumps(payload)
    with _send_lock:
        target_ws.send(message)


def _parse_attachment_descriptor(value):
    if not isinstance(value, dict):
        return None

    attachment_id = value.get("id")
    filename = value.get("filename")
    content_type = value.get("content_type")
    size_bytes = value.get("size_bytes")
    sha256 = value.get("sha256")
    available = value.get("available")
    download_link = value.get("download_link", "")

    if not isinstance(attachment_id, str) or not attachment_id:
        return None
    if not isinstance(filename, str) or not filename:
        return None
    if not isinstance(content_type, str) or not content_type:
        return None
    if (
        not isinstance(size_bytes, int)
        or isinstance(size_bytes, bool)
        or size_bytes <= 0
        or size_bytes > chat_attachments.MAX_ATTACHMENT_BYTES
    ):
        return None
    if sha256 is not None and (not isinstance(sha256, str) or not sha256):
        return None
    if not isinstance(available, bool):
        return None
    if not isinstance(download_link, str):
        return None
    if available and not download_link:
        return None

    return AttachmentDescriptor(
        id=attachment_id,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        sha256=sha256,
        available=available,
        download_link=download_link,
    )


def _parse_attachment_descriptors(value):
    if value is None:
        return ()
    if not isinstance(value, list):
        logger.warning("Ignoring malformed attachments payload")
        return ()

    attachments = []
    attachment_ids = set()
    for item in value:
        attachment = _parse_attachment_descriptor(item)
        if attachment is None:
            logger.warning("Ignoring malformed attachment descriptor")
            continue
        if attachment.id in attachment_ids:
            logger.warning("Ignoring duplicate attachment descriptor id=%s", attachment.id)
            continue
        if len(attachments) >= _max_attachments_per_message:
            logger.warning("Ignoring attachment descriptors above the per-message limit")
            break
        attachment_ids.add(attachment.id)
        attachments.append(attachment)
    return tuple(attachments)


def _enqueue_user_message(seq, text, attachments=()):
    with _msg_lock:
        if _last_seen_seq is not None and seq <= _last_seen_seq:
            return False
        if _inbox and seq <= _inbox[-1].seq:
            return False
        _inbox.append(
            InboundMessage(seq=seq, text=text, attachments=tuple(attachments))
        )
        return True


def _handle_frame(raw_message):
    if isinstance(raw_message, bytes):
        raw_message = raw_message.decode("utf-8", errors="ignore")

    try:
        frame = json.loads(raw_message)
    except json.JSONDecodeError:
        logger.warning("Ignoring non-JSON WebSocket frame")
        return

    if not isinstance(frame, dict):
        logger.warning("Ignoring unexpected WebSocket frame payload")
        return

    frame_type = frame.get("type")
    if frame_type == "user_message":
        seq = frame.get("seq")
        text = frame.get("text")
        if not isinstance(seq, int) or not isinstance(text, str):
            logger.warning("Ignoring malformed user_message frame")
            return
        attachments = _parse_attachment_descriptors(frame.get("attachments"))
        _enqueue_user_message(seq, text, attachments)
        return

    if frame_type == "ack":
        logger.info(f"Ack received for seq={frame.get('seq')} client_seq={frame.get('client_seq')}")
        _resolve_pending(frame.get("client_seq"))
        return

    if frame_type == "error":
        logger.error(f"Server error {frame.get('code')}: {frame.get('message')}")
        _resolve_pending(None, error=frame.get("code") or "unknown_error")
        return

    logger.warning(f"Ignoring unsupported frame type: {frame_type!r}")


def _drain_outbox(ws):
    with _msg_lock:
        pending = list(_outbox)
        _outbox.clear()
    for payload in pending:
        try:
            _send_json(payload, ws=ws)
        except Exception:
            with _msg_lock:
                _outbox.appendleft(payload)
            raise


def _listen_once(ws):
    _send_json(_build_resume_frame(), ws=ws)
    _drain_outbox(ws)
    while _running:
        raw_message = ws.recv()
        if raw_message is None:
            raise RuntimeError("WebSocket closed by peer")
        _handle_frame(raw_message)


def _listener_loop():
    backoff_seconds = 1.0
    logger.info(f"Starting adapter for {_ws_url}")

    while _running:
        active_ws = None
        try:
            with _connect_client(_ws_url, _ws_token) as ws:
                active_ws = ws
                _set_connection(ws)
                logger.info("Connected")
                backoff_seconds = 1.0
                _listen_once(ws)
        except Exception as exc:
            _clear_connection(active_ws)
            active_ws = None
            if not _running:
                break

            delay = min(backoff_seconds, 30.0)
            delay += random.uniform(0.0, delay * 0.2)
            logger.exception(f"Connection error: {exc}. Reconnecting in {delay:.1f}s")
            time.sleep(delay)
            backoff_seconds = min(backoff_seconds * 2.0, 30.0)
        finally:
            _clear_connection(active_ws)

    logger.info("Adapter stopped")


def start_websocket(ws_url=None, ws_token=None):
    global _running, _thread, _ws_url, _ws_token
    global _upload_cleanup_enabled, _upload_cleanup_thread

    try:
        _ensure_websockets_available()
        _ws_url, _ws_token = _resolve_connection_inputs(ws_url, ws_token)
    except Exception as exc:
        logger.exception(f"WebSocket channel disabled: {exc}")
        return None

    _clear_connection()
    _upload_cleanup_enabled = True
    _maybe_cleanup_uploads(force=True)

    _running = True
    _upload_cleanup_stop_event.clear()
    _upload_cleanup_thread = threading.Thread(
        target=_upload_cleanup_loop,
        daemon=True,
        name="websocket-attachment-cleanup",
    )
    _upload_cleanup_thread.start()
    _thread = threading.Thread(target=_listener_loop, daemon=True, name="websocket-channel")
    _thread.start()
    return _thread


def stop_websocket():
    global _running
    _running = False
    _upload_cleanup_stop_event.set()

    with _state_lock:
        active_ws = _ws

    if active_ws is None:
        return

    try:
        active_ws.close()
    except Exception as exc:
        logger.exception(f"Error while closing websocket: {exc}")


def getLastMessage():
    global _last_seen_seq

    with _msg_lock:
        if not _inbox:
            return ""

        batch = list(_inbox)
        _inbox.clear()
        _last_seen_seq = batch[-1].seq

    if all(not message.attachments for message in batch):
        return " | ".join(message.text for message in batch)

    _maybe_cleanup_uploads()
    return "\n\n".join(_render_inbound_message(message) for message in batch)



def _register_pending(client_seq):
    entry = {"event": threading.Event(), "error": None}
    with _pending_lock:
        _pending_sends[client_seq] = entry
    return entry


def _discard_pending(client_seq):
    with _pending_lock:
        _pending_sends.pop(client_seq, None)


def _resolve_pending(client_seq, error=None):
    with _pending_lock:
        if client_seq is None:
            if not _pending_sends:
                return
            client_seq = next(iter(_pending_sends))
        entry = _pending_sends.pop(client_seq, None)
    if entry is None:
        return
    entry["error"] = error
    entry["event"].set()


def _send_or_buffer(payload):
    with _state_lock:
        connected = _connected
        active_ws = _ws

    if not connected:
        with _msg_lock:
            _outbox.append(payload)
        return True

    try:
        _send_json(payload, ws=active_ws)
    except Exception as exc:
        logger.exception(f"Send failed, buffering for reconnect: {exc}")
        with _msg_lock:
            _outbox.append(payload)
    return True


def send_message(text):
    message_text = str(text).replace("\\n", "\n").replace("\r", "")
    if not message_text:
        return False

    return _send_or_buffer(
        {
            "type": "agent_message",
            "client_seq": uuid.uuid4().hex,
            "text": message_text,
        }
    )


def send_message_with_attachment(text, attachment_id):
    message_text = str(text).replace("\\n", "\n").replace("\r", "")
    attachment_id = str(attachment_id).strip()
    if not message_text or not attachment_id:
        return False

    client_seq = uuid.uuid4().hex
    payload = {
        "type": "agent_message",
        "client_seq": client_seq,
        "text": message_text,
        "attachments": [{"id": attachment_id}],
    }

    with _state_lock:
        connected = _connected

    if not connected:
        return _send_or_buffer(payload)

    entry = _register_pending(client_seq)
    try:
        _send_or_buffer(payload)
        if not entry["event"].wait(ATTACHMENT_VERDICT_TIMEOUT_SECONDS):
            return True
        if entry["error"] is not None:
            logger.error(f"Attachment send rejected by server: {entry['error']}")
            return False
        return True
    finally:
        _discard_pending(client_seq)


class WSChannel(channels.CommChannel):

    def __init__(self):
        super().__init__()

    def start(self) -> None:
        start_websocket(config_get_by_key("WS_URL", ""), config_get_by_key("WS_TOKEN", ""))

    def stop(self) -> None:
        stop_websocket()

    def receive(self) -> str:
        return getLastMessage()

    def send(self, message: str) -> None:
        send_message(message)

    def send_attachment(self, attachment_id: str, message: str) -> bool:
        return send_message_with_attachment(message, attachment_id)


def loadOmegaClawPlugin():
    channels.registerCommChannel("websocket", WSChannel())
