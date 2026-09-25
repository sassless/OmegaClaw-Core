"""
In-process unit tests for the WebSocket channel logic (channels/wschat.py).

These drive the channel's pure functions directly on the host: no container, no
running agent, no `-t websocket`, and no `websockets` library (wschat imports it
lazily, only when actually connecting). That makes them CI-eligible in the same
job as test_comm / test_llm / test_rpc — they catch regressions in the dedup,
A | B | C merge, outbox and frame-parsing logic on every run.

The end-to-end wiring (channels.metta websocket dispatch, send skill ->
agent_message, real drain -> LLM) is covered separately by the
test_*_ws_mock.py integration suite, which needs a `-t websocket` container.
"""
import importlib.util
import json
import os
import sys
import uuid

import pytest

_WSCHAT_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "channels", "wschat.py")
)
_CHANNEL_PATH = os.path.dirname(_WSCHAT_PATH)


def _load_wschat():
    if _CHANNEL_PATH not in sys.path:
        sys.path.insert(0, _CHANNEL_PATH)
    spec = importlib.util.spec_from_file_location("wschat_under_test", _WSCHAT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def wschat():
    module = _load_wschat()
    module._inbox.clear()
    module._outbox.clear()
    module._last_seen_seq = None
    module._connected = False
    module._ws = None
    module._running = False
    return module


def _user_message(seq, text):
    return json.dumps({"type": "user_message", "seq": seq, "text": text})


def test_enqueue_join_and_last_seen(wschat):
    wschat._handle_frame(_user_message(1, "A"))
    wschat._handle_frame(_user_message(2, "B"))
    wschat._handle_frame(_user_message(3, "C"))
    assert wschat.getLastMessage() == "A | B | C"
    assert wschat._last_seen_seq == 3
    assert wschat.getLastMessage() == ""


def test_dedup_by_last_seen_seq(wschat):
    wschat._handle_frame(_user_message(1, "A"))
    wschat._handle_frame(_user_message(2, "B"))
    assert wschat.getLastMessage() == "A | B"
    assert wschat._last_seen_seq == 2

    wschat._handle_frame(_user_message(2, "replay-2"))
    wschat._handle_frame(_user_message(1, "replay-1"))
    assert wschat.getLastMessage() == ""


def test_dedup_by_inbox_order(wschat):
    wschat._handle_frame(_user_message(5, "X"))
    wschat._handle_frame(_user_message(5, "Y"))
    wschat._handle_frame(_user_message(4, "Z"))
    assert wschat.getLastMessage() == "X"
    assert wschat._last_seen_seq == 5


def test_frame_robustness(wschat):
    wschat._handle_frame("this is not json <<<{")
    wschat._handle_frame(json.dumps(["not", "a", "dict"]))
    wschat._handle_frame(json.dumps({"type": "user_message", "seq": "x", "text": "t"}))
    wschat._handle_frame(json.dumps({"type": "user_message", "seq": 1, "text": 123}))
    wschat._handle_frame(json.dumps({"type": "totally_unknown"}))
    wschat._handle_frame(json.dumps({"type": "ack", "seq": 1, "client_seq": "abc"}))
    wschat._handle_frame(json.dumps({"type": "error", "code": "E", "message": "boom"}))
    assert len(wschat._inbox) == 0

    wschat._handle_frame(_user_message(1, "OK"))
    assert wschat.getLastMessage() == "OK"


def test_outbox_buffers_while_disconnected_and_flushes(wschat):
    wschat._connected = False
    wschat._ws = None

    wschat.send_message("buffered-1")
    assert len(wschat._outbox) == 1
    payload = wschat._outbox[0]
    assert payload["type"] == "agent_message"
    assert payload["text"] == "buffered-1"
    uuid.UUID(hex=payload["client_seq"])
    original_client_seq = payload["client_seq"]

    sent = []

    class _FakeWs:
        def send(self, message):
            sent.append(message)

    wschat._drain_outbox(_FakeWs())
    assert len(wschat._outbox) == 0
    assert len(sent) == 1
    flushed = json.loads(sent[0])
    assert flushed["type"] == "agent_message"
    assert flushed["text"] == "buffered-1"
    assert flushed["client_seq"] == original_client_seq


def test_attachment_skill_sends_one_use_id_once(wschat):
    wschat._running = True
    wschat._skill_sent_attachments.clear()

    assert wschat.send_attachment_skill("uploaded-id", "Here is the file") is True
    assert wschat.send_attachment_skill("uploaded-id", "Here is the file") is True
    assert wschat.send_attachment_skill("uploaded-id", "Different text") is False
    assert len(wschat._outbox) == 1
    assert wschat._outbox[0]["attachments"] == [{"id": "uploaded-id"}]


def test_attachment_skill_rejects_inactive_channel(wschat):
    wschat._skill_sent_attachments.clear()

    assert wschat.send_attachment_skill("uploaded-id", "Here is the file") is False
    assert not wschat._outbox


def test_resume_frame_reflects_last_seen(wschat):
    assert wschat._build_resume_frame() == {"type": "resume", "last_seen_seq": None}
    wschat._last_seen_seq = 7
    assert wschat._build_resume_frame() == {"type": "resume", "last_seen_seq": 7}


def test_channel_start_reads_token_from_configured_file(wschat, monkeypatch, tmp_path):
    token_path = tmp_path / "ws-token"
    token_path.write_text("mounted-secret\n", encoding="utf-8")
    values = {
        "WS_URL": "wss://space.example/ws",
        "wsTokenPath": str(token_path),
    }
    started_with = []

    monkeypatch.setattr(
        wschat,
        "config_get_by_key",
        lambda key, default="": values.get(key, default),
    )
    monkeypatch.setattr(
        wschat,
        "start_websocket",
        lambda url, token: started_with.append((url, token)),
    )

    wschat.WSChannel().start()

    assert started_with == [("wss://space.example/ws", "mounted-secret")]


def test_channel_greets_once_and_hides_only_startup_version(wschat, monkeypatch):
    monkeypatch.setattr(
        wschat,
        "config_get_by_key",
        lambda key, default="": True if key == "wschatManageStartupMessages" else default,
    )
    monkeypatch.setattr(wschat, "_configured_ws_token", lambda: "")
    monkeypatch.setattr(wschat, "start_websocket", lambda url, token: object())
    monkeypatch.setattr(wschat.helper, "omega_version", lambda: "Omega version=test", raising=False)

    channel = wschat.WSChannel()
    channel.start()
    assert [item["text"] for item in wschat._outbox] == [
        "Welcome to Omega Cloud! I'm your Omega agent, delighted to assist you. "
        "To get started, simply type a message in the chat – I'm all yours!"
    ]

    channel.send("Omega version=test")
    channel.send("Hello")
    channel.send("Omega version=test")
    assert [item["text"] for item in wschat._outbox] == [
        "Welcome to Omega Cloud! I'm your Omega agent, delighted to assist you. "
        "To get started, simply type a message in the chat – I'm all yours!",
        "Hello",
        "Omega version=test",
    ]


def test_fork_channel_keeps_its_existing_startup_messages(wschat, monkeypatch):
    monkeypatch.setattr(wschat, "config_get_by_key", lambda key, default="": default)
    monkeypatch.setattr(wschat, "_configured_ws_token", lambda: "")
    monkeypatch.setattr(wschat, "start_websocket", lambda url, token: object())

    channel = wschat.WSChannel()
    channel.start()
    channel.send("Existing fork greeting")

    assert [item["text"] for item in wschat._outbox] == ["Existing fork greeting"]
