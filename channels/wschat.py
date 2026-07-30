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

  ``{"type": "user_message", "seq": <int>, "text": <str>,
  "attachments": [<descriptor>, ...]}``
      A new inbound message. ``seq`` is a monotonically increasing integer
      assigned by the server; the client uses it for ordering and dedup.
      ``attachments`` is optional. Available files are downloaded with the
      existing bearer token and rendered as safe local paths; unavailable or
      failed files are rendered as visible context.

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
  by ``getLastMessage``, which preserves the existing ``' | '`` rendering for
  text-only batches and advances ``last_seen_seq`` before attachment I/O.
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
from json import JSONDecodeError

from channels import chat_attachments


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


def _open_http_request(request, *, allow_redirects, timeout_seconds):
    return chat_attachments.open_http_request(
        request,
        allow_redirects=allow_redirects,
        timeout_seconds=timeout_seconds,
    )


def _download_attachment(
    attachment,
    *,
    seq,
    ws_token,
    upload_root=chat_attachments.UPLOAD_ROOT,
):
    return chat_attachments.download_attachment(
        attachment,
        seq=seq,
        ws_token=ws_token,
        upload_root=upload_root,
    )


def _cleanup_upload_root(**kwargs):
    return chat_attachments.cleanup_upload_root(**kwargs)


def _process_attachment(path, content_type):
    return chat_attachments.process_attachment(path, content_type)


def _download_attachment_with_retries(attachment: AttachmentDescriptor, *, seq, attempts=3):
    last_error = None
    for attempt in range(attempts):
        try:
            return _download_attachment(
                attachment,
                seq=seq,
                ws_token=_ws_token,
            )
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

    result = _process_attachment(local_path, attachment.content_type)
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
    lines.extend(_render_attachment(message, attachment) for attachment in message.attachments)
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
        result = _cleanup_upload_root()
        if result.removed_files:
            _log(
                "Attachment cleanup removed "
                f"{result.removed_files} files; {result.remaining_bytes} bytes remain"
            )
    except Exception as exc:
        _log(f"Attachment cleanup failed: {exc}")


def _upload_cleanup_loop():
    while _running:
        if _upload_cleanup_stop_event.wait(_upload_cleanup_interval_seconds):
            return
        if not _running:
            return
        _maybe_cleanup_uploads(force=True)


def _log(message):
    print(f"[WS] {message}")


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
    except TypeError:
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


def _parse_attachment_descriptor(value) -> AttachmentDescriptor | None:
    if not isinstance(value, dict):
        return None

    attachment_id = value.get("id")
    filename = value.get("filename")
    content_type = value.get("content_type")
    size_bytes = value.get("size_bytes")
    sha256 = value.get("sha256")
    available = value.get("available")
    download_link = value.get("download_link")

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

    return AttachmentDescriptor(
        id=attachment_id,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        sha256=sha256,
        available=available,
        download_link=download_link,
    )


def _parse_attachment_descriptors(value) -> tuple[AttachmentDescriptor] | tuple:
    if value is None:
        return ()
    if not isinstance(value, list):
        _log("Ignoring malformed attachments payload")
        return ()

    attachments = []
    attachment_ids = set()
    for item in value:
        attachment = _parse_attachment_descriptor(item)
        if attachment is None:
            _log(f"Ignoring malformed attachment descriptor: {item!r}")
            continue
        if attachment.id in attachment_ids:
            _log(f"Ignoring duplicate attachment descriptor id={attachment.id}")
            continue
        if len(attachments) >= _max_attachments_per_message:
            _log("Ignoring attachment descriptors above the per-message limit")
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
        _inbox.append(InboundMessage(seq=seq, text=text, attachments=attachments))
        return True


def _handle_frame(raw_message):
    if isinstance(raw_message, bytes):
        raw_message = raw_message.decode("utf-8", errors="ignore")

    try:
        frame = json.loads(raw_message)
    except json.JSONDecodeError:
        _log(f"Ignoring non-JSON frame: {raw_message!r}")
        return

    if not isinstance(frame, dict):
        _log(f"Ignoring unexpected frame payload: {frame!r}")
        return

    frame_type = frame.get("type")
    if frame_type == "user_message":
        seq = frame.get("seq")
        text = frame.get("text")
        if not isinstance(seq, int) or not isinstance(text, str):
            _log(f"Ignoring malformed user_message frame: {frame!r}")
            return
        attachments = _parse_attachment_descriptors(frame.get("attachments"))
        _enqueue_user_message(seq, text, attachments)
        return

    if frame_type == "ack":
        _log(f"Ack received for seq={frame.get('seq')} client_seq={frame.get('client_seq')}")
        return

    if frame_type == "error":
        _log(f"Server error {frame.get('code')}: {frame.get('message')}")
        return

    _log(f"Ignoring unsupported frame type: {frame_type!r}")


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
    _log(f"Starting adapter for {_ws_url}")

    while _running:
        active_ws = None
        try:
            with _connect_client(_ws_url, _ws_token) as ws:
                active_ws = ws
                _set_connection(ws)
                _log("Connected")
                backoff_seconds = 1.0
                _listen_once(ws)
        except Exception as exc:
            _clear_connection(active_ws)
            active_ws = None
            if not _running:
                break

            delay = min(backoff_seconds, 30.0)
            delay += random.uniform(0.0, delay * 0.2)
            _log(f"Connection error: {exc}. Reconnecting in {delay:.1f}s")
            time.sleep(delay)
            backoff_seconds = min(backoff_seconds * 2.0, 30.0)
        finally:
            _clear_connection(active_ws)

    _log("Adapter stopped")


def start_websocket(ws_url=None, ws_token=None):
    global _running, _thread, _ws_url, _ws_token
    global _upload_cleanup_enabled, _upload_cleanup_thread

    try:
        _ensure_websockets_available()
        _ws_url, _ws_token = _resolve_connection_inputs(ws_url, ws_token)
    except Exception as exc:
        _log(f"WebSocket channel disabled: {exc}")
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
        _log(f"Error while closing websocket: {exc}")


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


def send_message(text):
    try:
        msg_dict = json.loads(text)
        text = msg_dict.get("text", "")
        attachment_as_json = msg_dict.get("attachment", {})
    except JSONDecodeError:
        _log(f"Message doesn't have attachment")
        attachment_as_json = {}
    _log(f"Message to send via ws: text={text}, attachment={attachment_as_json}")

    message_text = str(text).replace("\\n", "\n").replace("\r", "")
    if not message_text:
        return

    if isinstance(attachment_as_json, str):
        try:
            attachment_dict = json.loads(attachment_as_json)
        except JSONDecodeError as e:
            _log(f"Attachment can't be decoded: {e}")
            attachment_dict = {}
    elif isinstance(attachment_as_json, dict):
        attachment_dict = attachment_as_json
    else:
        _log(f"Attachment has unexpected format: type={type(attachment_as_json)}, {attachment_as_json}")
        attachment_dict = {}

    payload = {
        "type": "agent_message",
        "client_seq": uuid.uuid4().hex,
        "text": message_text,
        "attachments": []
    }

    if attachment_dict.get("id", None) is None:
        _log(f"Attachment has unexpected fields: {attachment_dict}")
        attachment_dict = {}

    if attachment_dict:
        payload["attachments"].append(attachment_dict)

    with _state_lock:
        connected = _connected
        active_ws = _ws

    if not connected:
        with _msg_lock:
            _outbox.append(payload)
        return

    try:
        _log(f"Final message payload to send: {payload}")
        _send_json(payload, ws=active_ws)
    except Exception as exc:
        _log(f"Send failed, buffering for reconnect: {exc}")
        with _msg_lock:
            _outbox.append(payload)
