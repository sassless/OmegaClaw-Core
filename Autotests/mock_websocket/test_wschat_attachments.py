import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


ROOT_PATH = Path(__file__).parents[2]
CHANNEL_PATH = ROOT_PATH / "channels"
WSCHAT_PATH = CHANNEL_PATH / "wschat.py"


def _load_wschat():
    channel_path = str(CHANNEL_PATH)
    if channel_path not in sys.path:
        sys.path.insert(0, channel_path)
    spec = importlib.util.spec_from_file_location("wschat_under_test", WSCHAT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def wschat():
    module = _load_wschat()
    with module._msg_lock:
        module._inbox.clear()
        module._outbox.clear()
        module._last_seen_seq = None
    module._ws_url = "wss://space.example/api/v1/agents/a/chat/assistant/ws"
    module._ws_token = "secret-token"
    assert module.chat_attachments.__name__ == "chat_attachments"
    return module


def descriptor_payload(identifier="attachment-1", **overrides):
    values = {
        "id": identifier,
        "filename": "report.txt",
        "content_type": "text/plain",
        "size_bytes": 4,
        "sha256": None,
        "available": True,
        "download_link": (
            f"https://space.example/api/v1/agents/a/chat/attachments/{identifier}"
        ),
    }
    values.update(overrides)
    return values


def attachment_descriptor(wschat, **overrides):
    return wschat.AttachmentDescriptor(**descriptor_payload(**overrides))


def enqueue_attachment_message(wschat, *, available=True, text="summarize"):
    descriptor = attachment_descriptor(
        wschat,
        available=available,
        download_link=(
            "https://space.example/api/v1/agents/a/chat/attachments/attachment-1"
            if available
            else ""
        ),
    )
    wschat._enqueue_user_message(9, text, (descriptor,))


def test_text_only_frames_keep_existing_batch_rendering(wschat):
    wschat._handle_frame(
        json.dumps({"type": "user_message", "seq": 1, "text": "one"})
    )
    wschat._handle_frame(
        json.dumps({"type": "user_message", "seq": 2, "text": "two"})
    )

    assert wschat.getLastMessage() == "one | two"
    assert wschat._last_seen_seq == 2


def test_descriptors_are_validated_capped_at_three_and_deduplicated(wschat):
    descriptors = [descriptor_payload(f"attachment-{index}") for index in range(4)]
    descriptors.insert(1, dict(descriptors[0]))

    wschat._handle_frame(
        json.dumps(
            {
                "type": "user_message",
                "seq": 6,
                "text": "bounded",
                "attachments": descriptors,
            }
        )
    )

    with wschat._msg_lock:
        message = wschat._inbox[0]
    assert message.seq == 6
    assert message.text == "bounded"
    assert [item.id for item in message.attachments] == [
        "attachment-0",
        "attachment-1",
        "attachment-2",
    ]


def test_available_descriptor_requires_download_link(wschat):
    frame = {
        "type": "user_message",
        "seq": 1,
        "text": "keep the text",
        "attachments": [descriptor_payload(download_link="")],
    }
    wschat._handle_frame(json.dumps(frame))

    with wschat._msg_lock:
        message = wschat._inbox[0]
    assert message.text == "keep the text"
    assert message.attachments == ()


@pytest.mark.parametrize(
    "attachment",
    [
        {},
        descriptor_payload(identifier=""),
        descriptor_payload(size_bytes=0),
        descriptor_payload(size_bytes=10 * 1024 * 1024 + 1),
        descriptor_payload(available="yes"),
    ],
)
def test_malformed_attachment_keeps_valid_message_text(wschat, attachment):
    wschat._handle_frame(
        json.dumps(
            {
                "type": "user_message",
                "seq": 3,
                "text": "still deliver this",
                "attachments": [attachment],
            }
        )
    )

    with wschat._msg_lock:
        message = wschat._inbox[0]
    assert message.text == "still deliver this"
    assert message.attachments == ()


def test_duplicate_sequence_with_attachments_is_dropped(wschat):
    frame = {
        "type": "user_message",
        "seq": 5,
        "text": "once",
        "attachments": [descriptor_payload()],
    }
    wschat._handle_frame(json.dumps(frame))
    wschat._handle_frame(json.dumps(frame))

    with wschat._msg_lock:
        assert len(wschat._inbox) == 1


def test_unavailable_attachment_is_visible_without_download(wschat, monkeypatch):
    enqueue_attachment_message(wschat, available=False)
    monkeypatch.setattr(
        wschat,
        "_download_attachment_with_retries",
        lambda *_args, **_kwargs: pytest.fail("unavailable attachment was downloaded"),
    )

    rendered = wschat.getLastMessage()

    assert "report.txt" in rendered
    assert "attachment-1" in rendered
    assert "unavailable" in rendered.lower()
    assert "summarize" in rendered


def test_attachment_io_runs_after_message_lock_is_released(
    wschat, monkeypatch, tmp_path
):
    local_file = tmp_path / "report.txt"
    local_file.write_text("hello", encoding="utf-8")
    enqueue_attachment_message(wschat)

    def download(*_args, **_kwargs):
        assert wschat._msg_lock.acquire(blocking=False)
        wschat._msg_lock.release()
        return local_file

    monkeypatch.setattr(wschat, "_download_attachment_with_retries", download)

    rendered = wschat.getLastMessage()

    assert f"Original file: {local_file}" in rendered
    assert "User request: summarize" in rendered
    assert wschat._last_seen_seq == 9


def test_transient_download_failure_retries_without_duplicate_text(
    wschat, monkeypatch, tmp_path
):
    local_file = tmp_path / "report.txt"
    local_file.write_text("hello", encoding="utf-8")
    enqueue_attachment_message(wschat, text="unique request text")
    attempts = []

    def download(*_args, **_kwargs):
        attempts.append(1)
        if len(attempts) < 2:
            raise wschat.AttachmentDownloadError("temporary failure")
        return local_file

    monkeypatch.setattr(wschat, "_download_attachment", download)
    monkeypatch.setattr(wschat.time, "sleep", lambda _seconds: None)

    rendered = wschat.getLastMessage()

    assert len(attempts) == 2
    assert rendered.count("unique request text") == 1
    assert wschat.getLastMessage() == ""


def test_permanent_failure_is_visible_and_consumed_once(wschat, monkeypatch):
    enqueue_attachment_message(wschat)

    def fail(*_args, **_kwargs):
        raise wschat.AttachmentDownloadError("network unavailable")

    monkeypatch.setattr(wschat, "_download_attachment", fail)
    monkeypatch.setattr(wschat.time, "sleep", lambda _seconds: None)

    rendered = wschat.getLastMessage()

    assert "report.txt" in rendered
    assert "attachment-1" in rendered
    assert "network unavailable" in rendered
    assert wschat.getLastMessage() == ""


def test_start_and_stop_manage_attachment_cleanup(wschat, monkeypatch):
    started_threads = []
    cleanup_calls = []

    class Thread:
        def __init__(self, *, target, daemon, name):
            self.target = target
            self.daemon = daemon
            self.name = name

        def start(self):
            started_threads.append(self)

    monkeypatch.setattr(wschat, "_ensure_websockets_available", lambda: None)
    monkeypatch.setattr(wschat.threading, "Thread", Thread)
    monkeypatch.setattr(
        wschat,
        "_maybe_cleanup_uploads",
        lambda *, force=False: cleanup_calls.append(force),
    )

    wschat.start_websocket("wss://space.example/ws", "token")

    assert cleanup_calls == [True]
    assert [thread.name for thread in started_threads] == [
        "websocket-attachment-cleanup",
        "websocket-channel",
    ]
    assert all(thread.daemon for thread in started_threads)

    wschat.stop_websocket()
    assert wschat._running is False
    assert wschat._upload_cleanup_stop_event.is_set()


def test_outbound_attachment_send_queues_only_id_and_text(wschat):
    wschat._connected = False
    wschat._ws = None
    attachment_id = "550e8400-e29b-41d4-a716-446655440000"

    assert wschat.send_message_with_attachment(
        "Here is the report.", attachment_id
    ) is True

    payload = wschat._outbox[-1]
    assert payload["text"] == "Here is the report."
    assert payload["attachments"] == [{"id": attachment_id}]
    assert set(payload) == {"type", "client_seq", "text", "attachments"}


@pytest.mark.parametrize(
    ("text", "attachment_id"),
    [("", "attachment-id"), ("message", ""), ("", "")],
)
def test_outbound_attachment_send_rejects_empty_arguments(
    wschat, text, attachment_id
):
    before = list(wschat._outbox)

    assert wschat.send_message_with_attachment(text, attachment_id) is False

    assert list(wschat._outbox) == before
