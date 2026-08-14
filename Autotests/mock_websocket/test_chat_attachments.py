import base64
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT_PATH = Path(__file__).parents[2]
CHANNEL_PATH = ROOT_PATH / "channels"
if str(CHANNEL_PATH) not in sys.path:
    sys.path.insert(0, str(CHANNEL_PATH))

import chat_attachments as module


class FakeHTTPResponse:
    def __init__(self, *, status, headers=None, body=b""):
        self.status = status
        self.headers = headers or {}
        self._body = body
        self._offset = 0

    def read(self, size=-1):
        if size < 0:
            size = len(self._body) - self._offset
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def attachment_descriptor(**overrides):
    values = {
        "id": "4e61d44d-c0ef-4b12-b223-8762796e91bf",
        "filename": "report.txt",
        "content_type": "text/plain",
        "size_bytes": 4,
        "sha256": base64.b64encode(hashlib.sha256(b"data").digest()).decode(
            "ascii"
        ),
        "available": True,
        "download_link": (
            "https://space.example/api/v1/agents/a/chat/attachments/id"
        ),
    }
    values.update(overrides)
    return module.AttachmentDescriptor(**values)


def test_download_uses_descriptor_link_and_sends_bearer_only_to_backend(
    monkeypatch, tmp_path
):
    calls = []
    s3_url = "https://chat-bucket.s3.eu-west-1.amazonaws.com/object?signature=test"

    def open_request(request, *, allow_redirects, timeout_seconds):
        calls.append(
            {
                "url": request.full_url,
                "headers": dict(request.header_items()),
                "allow_redirects": allow_redirects,
                "timeout_seconds": timeout_seconds,
            }
        )
        if len(calls) == 1:
            return FakeHTTPResponse(status=307, headers={"Location": s3_url})
        return FakeHTTPResponse(
            status=200, headers={"Content-Length": "4"}, body=b"data"
        )

    monkeypatch.setattr(module, "open_http_request", open_request)
    descriptor = attachment_descriptor(filename="../../report.txt")

    path = module.download_attachment(
        descriptor,
        seq=42,
        ws_url="wss://space.example/api/v1/agents/a/chat/assistant/ws",
        ws_token="secret-token",
        upload_root=tmp_path,
    )

    assert path.read_bytes() == b"data"
    assert path.is_relative_to(tmp_path / "42")
    assert ".." not in path.name
    assert calls[0]["url"] == descriptor.download_link
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-token"
    assert "Authorization" not in calls[1]["headers"]
    assert calls[0]["allow_redirects"] is False
    assert calls[1]["allow_redirects"] is False
    assert calls[1]["url"] == s3_url


@pytest.mark.parametrize(
    "download_link",
    [
        "https://attacker.example/api/attachments/id",
        "http://space.example/api/attachments/id",
        "https://user:pass@space.example/api/attachments/id",
        "https://space.example/api/attachments/id#fragment",
        "ftp://space.example/api/attachments/id",
    ],
)
def test_backend_download_link_must_match_websocket_origin(
    monkeypatch, tmp_path, download_link
):
    monkeypatch.setattr(
        module,
        "open_http_request",
        lambda *_args, **_kwargs: pytest.fail("invalid URL reached the network"),
    )

    with pytest.raises(module.AttachmentDownloadError, match="download link"):
        module.download_attachment(
            attachment_descriptor(download_link=download_link),
            seq=1,
            ws_url="wss://space.example/api/v1/agents/a/chat/assistant/ws",
            ws_token="secret-token",
            upload_root=tmp_path,
        )


def test_available_attachment_requires_download_link(tmp_path):
    with pytest.raises(module.AttachmentDownloadError, match="download link"):
        module.download_attachment(
            attachment_descriptor(download_link=""),
            seq=1,
            ws_url="wss://space.example/api/v1/agents/a/chat/assistant/ws",
            ws_token="secret-token",
            upload_root=tmp_path,
        )


@pytest.mark.parametrize(
    "redirect_url",
    [
        "http://bucket.s3.amazonaws.com/object",
        "https://user:pass@bucket.s3.amazonaws.com/object",
        "https://bucket.s3.amazonaws.com:444/object",
        "https://attacker.example/object",
    ],
)
def test_download_rejects_unsafe_object_redirects(
    monkeypatch, tmp_path, redirect_url
):
    calls = []

    def open_request(request, **_kwargs):
        calls.append(dict(request.header_items()))
        return FakeHTTPResponse(status=307, headers={"Location": redirect_url})

    monkeypatch.setattr(module, "open_http_request", open_request)

    with pytest.raises(module.AttachmentDownloadError, match="unexpected redirect"):
        module.download_attachment(
            attachment_descriptor(),
            seq=1,
            ws_url="wss://space.example/api/v1/agents/a/chat/assistant/ws",
            ws_token="secret-token",
            upload_root=tmp_path,
        )

    assert calls == [
        {"Accept": "application/octet-stream", "Authorization": "Bearer secret-token"}
    ]


@pytest.mark.parametrize(
    ("descriptor", "body", "error"),
    [
        (attachment_descriptor(size_bytes=3, sha256=None), b"data", "declared size"),
        (attachment_descriptor(sha256="ZmFrZQ=="), b"data", "checksum"),
    ],
)
def test_size_or_checksum_mismatch_removes_partial_file(
    monkeypatch, tmp_path, descriptor, body, error
):
    responses = iter(
        [
            FakeHTTPResponse(
                status=307,
                headers={"Location": "https://bucket.s3.amazonaws.com/object"},
            ),
            FakeHTTPResponse(status=200, body=body),
        ]
    )
    monkeypatch.setattr(
        module, "open_http_request", lambda *_args, **_kwargs: next(responses)
    )

    with pytest.raises(module.AttachmentDownloadError, match=error):
        module.download_attachment(
            descriptor,
            seq=1,
            ws_url="wss://space.example/api/v1/agents/a/chat/assistant/ws",
            ws_token="token",
            upload_root=tmp_path,
        )

    assert list(tmp_path.rglob("*")) == [tmp_path / "1"]


def test_cleanup_is_age_and_size_bounded_without_following_symlinks(tmp_path):
    outside = tmp_path.parent / "outside-attachment.txt"
    outside.write_bytes(b"outside")
    old_file = tmp_path / "old.txt"
    old_file.write_bytes(b"old")
    newer_file = tmp_path / "newer.txt"
    newer_file.write_bytes(b"123456")
    newest_file = tmp_path / "newest.txt"
    newest_file.write_bytes(b"abcdef")
    symlink = tmp_path / "outside-link"
    symlink.symlink_to(outside)

    now = time.time()
    os.utime(old_file, (now - 100, now - 100))
    os.utime(newer_file, (now - 20, now - 20))
    os.utime(newest_file, (now - 10, now - 10))

    result = module.cleanup_upload_root(
        upload_root=tmp_path,
        now=now,
        max_age_seconds=50,
        max_total_bytes=6,
    )

    assert not old_file.exists()
    assert not newer_file.exists()
    assert newest_file.read_bytes() == b"abcdef"
    assert not symlink.exists()
    assert outside.read_bytes() == b"outside"
    assert result == module.UploadCleanupResult(removed_files=3, remaining_bytes=6)


def test_local_path_rejects_symlinked_upload_root(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    upload_root = tmp_path / "uploads"
    upload_root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(module.AttachmentDownloadError, match="symlink"):
        module._attachment_local_path(upload_root, 1, "attachment-id", "file.txt")


def test_text_processing_normalizes_utf8_and_rejects_nul(tmp_path):
    markdown = tmp_path / "notes.md"
    markdown.write_bytes(b"first\r\nsecond\rthird")
    result = module.process_attachment(markdown, "text/markdown")
    assert result.error is None
    assert result.derived_text_path.read_text(encoding="utf-8") == (
        "first\nsecond\nthird"
    )

    invalid = tmp_path / "bad.txt"
    invalid.write_bytes(b"contains\x00nul")
    result = module.process_attachment(invalid, "text/plain")
    assert "NUL" in result.error
    assert result.derived_text_path is None


def test_pdf_extraction_enforces_encryption_page_and_character_limits(
    monkeypatch, tmp_path
):
    original = tmp_path / "bounded.pdf"
    original.write_bytes(b"%PDF-1.7\ncontent")

    class Page:
        def extract_text(self):
            return "abcd"

    class Reader:
        is_encrypted = False
        pages = [Page(), Page()]

    monkeypatch.setattr(module, "_load_pdf_reader", lambda _path: Reader())
    monkeypatch.setattr(module, "MAX_PDF_PAGES", 1)
    with pytest.raises(ValueError, match="page-count"):
        module._extract_pdf_text_in_process(original)

    monkeypatch.setattr(module, "MAX_PDF_PAGES", 2)
    monkeypatch.setattr(module, "MAX_PDF_CHARACTERS", 7)
    with pytest.raises(ValueError, match="extracted-character"):
        module._extract_pdf_text_in_process(original)

    Reader.is_encrypted = True
    with pytest.raises(ValueError, match="encrypted"):
        module._extract_pdf_text_in_process(original)


def test_pdf_extraction_enforces_deadline(monkeypatch, tmp_path):
    original = tmp_path / "slow.pdf"
    original.write_bytes(b"%PDF-1.7\ncontent")

    class Reader:
        is_encrypted = False
        pages = []

    timestamps = iter([0.0, 11.0])
    monkeypatch.setattr(module, "_load_pdf_reader", lambda _path: Reader())
    monkeypatch.setattr(module.time, "monotonic", lambda: next(timestamps))

    with pytest.raises(ValueError, match="timed out"):
        module._extract_pdf_text_in_process(original)


def test_pdf_extraction_runs_in_bounded_child_process(monkeypatch, tmp_path):
    original = tmp_path / "isolated.pdf"
    original.write_bytes(b"%PDF-1.7\ncontent")
    captured = {}

    def run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=b"extracted text", stderr=b"")

    monkeypatch.setattr(module.subprocess, "run", run)

    assert module._extract_pdf_text(original) == "extracted text"
    assert captured["command"] == [
        "python3",
        str(Path(module.__file__).resolve()),
        "--extract-pdf-worker",
        str(original.resolve()),
    ]
    assert captured["kwargs"]["timeout"] == module.MAX_PDF_SECONDS
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["check"] is False


def test_pdf_worker_timeout_is_visible(monkeypatch, tmp_path):
    original = tmp_path / "slow.pdf"
    original.write_bytes(b"%PDF-1.7\ncontent")

    def run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(ValueError, match="timed out"):
        module._extract_pdf_text(original)


def test_pdf_worker_applies_address_space_limit(monkeypatch):
    calls = []
    fake_resource = SimpleNamespace(
        RLIMIT_AS="address-space",
        setrlimit=lambda resource, limits: calls.append((resource, limits)),
    )
    monkeypatch.setitem(sys.modules, "resource", fake_resource)

    module._apply_pdf_worker_memory_limit()

    assert calls == [
        (
            "address-space",
            (module.MAX_PDF_MEMORY_BYTES, module.MAX_PDF_MEMORY_BYTES),
        )
    ]
