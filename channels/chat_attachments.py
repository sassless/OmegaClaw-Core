"""Safe download and local retention helpers for native chat attachments."""

import base64
import hashlib
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePath
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


UPLOAD_ROOT = Path("/tmp/omegaclaw/uploads")
DOWNLOAD_TIMEOUT_SECONDS = 30
DOWNLOAD_CHUNK_BYTES = 64 * 1024
LOCAL_MAX_AGE_SECONDS = 24 * 60 * 60
LOCAL_MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_TEXT_BYTES = MAX_ATTACHMENT_BYTES
MAX_PDF_BYTES = MAX_ATTACHMENT_BYTES
MAX_PDF_PAGES = 100
MAX_PDF_CHARACTERS = 200_000
MAX_PDF_SECONDS = 10.0
MAX_PDF_MEMORY_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class AttachmentDescriptor:
    id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str | None
    available: bool
    download_link: str


class AttachmentDownloadError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class UploadCleanupResult:
    removed_files: int
    remaining_bytes: int


@dataclass(frozen=True, slots=True)
class AttachmentProcessingResult:
    original_path: Path
    derived_text_path: Path | None
    content_type: str
    error: str | None


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def open_http_request(request, *, allow_redirects, timeout_seconds):
    opener = build_opener() if allow_redirects else build_opener(_NoRedirectHandler())
    try:
        return opener.open(request, timeout=timeout_seconds)
    except HTTPError as exc:
        if not allow_redirects and exc.code in {301, 302, 303, 307, 308}:
            return exc
        raise


def _normalized_origin(url, *, websocket=False):
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise AttachmentDownloadError("invalid attachment download link") from exc

    allowed_schemes = {"ws", "wss"} if websocket else {"http", "https"}
    if parsed.scheme not in allowed_schemes or not parsed.hostname:
        raise AttachmentDownloadError("invalid attachment download link")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise AttachmentDownloadError("invalid attachment download link")

    scheme = parsed.scheme
    if websocket:
        scheme = "https" if scheme == "wss" else "http"
    default_port = 443 if scheme == "https" else 80
    return scheme, parsed.hostname.lower(), port or default_port


def _validated_download_link(download_link, ws_url):
    if not download_link:
        raise AttachmentDownloadError("attachment download link is required")
    if _normalized_origin(download_link) != _normalized_origin(ws_url, websocket=True):
        raise AttachmentDownloadError("attachment download link origin does not match WS_URL")
    return download_link


def _is_allowed_s3_redirect(url):
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if port not in {None, 443}:
        return False

    hostname = parsed.hostname.lower()
    if not (
        hostname.endswith(".amazonaws.com")
        or hostname.endswith(".amazonaws.com.cn")
    ):
        return False

    labels = hostname.split(".")
    return any(label == "s3" or label.startswith("s3-") for label in labels)


def _safe_segment(value, fallback):
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return sanitized[:160] or fallback


def _attachment_local_path(upload_root, seq, attachment_id, filename):
    root = Path(upload_root)
    if root.is_symlink():
        raise AttachmentDownloadError("attachment upload root must not be a symlink")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root = root.resolve()

    seq_dir = root / str(int(seq))
    seq_dir.mkdir(mode=0o700, exist_ok=True)
    seq_dir = seq_dir.resolve()
    if not seq_dir.is_relative_to(root):
        raise AttachmentDownloadError("attachment sequence path escapes upload root")

    basename = PurePath(str(filename).replace("\\", "/")).name
    safe_name = _safe_segment(basename, "attachment")
    safe_id = _safe_segment(str(attachment_id), "attachment-id")
    path = (seq_dir / f"{safe_id}-{safe_name}").resolve()
    if not path.is_relative_to(seq_dir):
        raise AttachmentDownloadError("attachment path escapes upload root")
    return path


def download_attachment(
    attachment,
    *,
    seq,
    ws_url,
    ws_token,
    upload_root=UPLOAD_ROOT,
):
    if not attachment.available:
        raise AttachmentDownloadError("attachment is not available for download")
    if attachment.size_bytes < 0 or attachment.size_bytes > MAX_ATTACHMENT_BYTES:
        raise AttachmentDownloadError("attachment exceeds the size limit")
    endpoint = _validated_download_link(attachment.download_link, ws_url)
    headers = {"Accept": "application/octet-stream"}
    if ws_token:
        headers["Authorization"] = f"Bearer {ws_token}"

    try:
        with open_http_request(
            Request(endpoint, headers=headers),
            allow_redirects=False,
            timeout_seconds=DOWNLOAD_TIMEOUT_SECONDS,
        ) as response:
            if response.status != 307:
                raise AttachmentDownloadError(
                    f"attachment endpoint returned HTTP {response.status}"
                )
            redirect_url = response.headers.get("Location")
    except AttachmentDownloadError:
        raise
    except Exception as exc:
        raise AttachmentDownloadError(
            f"attachment endpoint request failed ({type(exc).__name__})"
        ) from exc

    if not redirect_url or not _is_allowed_s3_redirect(redirect_url):
        raise AttachmentDownloadError("attachment endpoint returned an unexpected redirect")

    destination = _attachment_local_path(
        upload_root,
        seq,
        attachment.id,
        attachment.filename,
    )
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.part")
    digest = hashlib.sha256()
    downloaded = 0

    try:
        with open_http_request(
            Request(redirect_url, headers={"Accept": "application/octet-stream"}),
            allow_redirects=False,
            timeout_seconds=DOWNLOAD_TIMEOUT_SECONDS,
        ) as response:
            if response.status != 200:
                raise AttachmentDownloadError(
                    f"attachment object returned HTTP {response.status}"
                )

            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    if int(content_length) != attachment.size_bytes:
                        raise AttachmentDownloadError(
                            "attachment object does not match declared size"
                        )
                except ValueError as exc:
                    raise AttachmentDownloadError(
                        "attachment object returned an invalid Content-Length"
                    ) from exc

            with temporary.open("xb") as file_pointer:
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > attachment.size_bytes:
                        raise AttachmentDownloadError(
                            "attachment object exceeds declared size"
                        )
                    digest.update(chunk)
                    file_pointer.write(chunk)

        if downloaded != attachment.size_bytes:
            raise AttachmentDownloadError("attachment object does not match declared size")

        if attachment.sha256 is not None:
            actual_checksum = base64.b64encode(digest.digest()).decode("ascii")
            if actual_checksum != attachment.sha256:
                raise AttachmentDownloadError("attachment checksum mismatch")

        os.replace(temporary, destination)
        return destination
    except AttachmentDownloadError:
        temporary.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise AttachmentDownloadError(
            f"attachment object download failed ({type(exc).__name__})"
        ) from exc


def cleanup_upload_root(
    *,
    upload_root=UPLOAD_ROOT,
    now=None,
    max_age_seconds=LOCAL_MAX_AGE_SECONDS,
    max_total_bytes=LOCAL_MAX_TOTAL_BYTES,
):
    root = Path(upload_root)
    if not root.exists():
        return UploadCleanupResult(removed_files=0, remaining_bytes=0)
    if root.is_symlink():
        raise ValueError("attachment upload root must not be a symlink")

    root = root.resolve()
    current_time = time.time() if now is None else now
    cutoff = current_time - max_age_seconds
    removed_files = 0
    retained = []

    for directory, child_directories, filenames in os.walk(
        root, topdown=True, followlinks=False
    ):
        directory_path = Path(directory)
        for child_name in list(child_directories):
            child_path = directory_path / child_name
            if child_path.is_symlink():
                child_path.unlink(missing_ok=True)
                child_directories.remove(child_name)
                removed_files += 1

        for filename in filenames:
            path = directory_path / filename
            if path.is_symlink():
                path.unlink(missing_ok=True)
                removed_files += 1
                continue
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            if stat.st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed_files += 1
                continue
            retained.append((stat.st_mtime, path, stat.st_size))

    total_bytes = sum(size for _, _, size in retained)
    for _, path, size in sorted(retained):
        if total_bytes <= max_total_bytes:
            break
        path.unlink(missing_ok=True)
        total_bytes -= size
        removed_files += 1

    for directory, _, _ in os.walk(root, topdown=False, followlinks=False):
        directory_path = Path(directory)
        if directory_path == root:
            continue
        try:
            directory_path.rmdir()
        except OSError:
            pass

    return UploadCleanupResult(
        removed_files=removed_files,
        remaining_bytes=total_bytes,
    )


def _write_text_sidecar(path, text):
    sidecar = path.with_name(f"{path.name}.txt")
    temporary = sidecar.with_name(f".{sidecar.name}.{uuid.uuid4().hex}.part")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, sidecar)
    finally:
        temporary.unlink(missing_ok=True)
    return sidecar


def _read_normalized_text(path):
    with path.open("rb") as file_pointer:
        raw = file_pointer.read(MAX_TEXT_BYTES + 1)
    if len(raw) > MAX_TEXT_BYTES:
        raise ValueError("text attachment exceeds the decoded-content limit")
    if b"\x00" in raw:
        raise ValueError("text attachment contains a NUL byte")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("text attachment is not valid UTF-8") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _load_pdf_reader(path):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("PDF processing dependency is unavailable") from exc
    return PdfReader(str(path))


def _extract_pdf_text_in_process(path):
    if path.stat().st_size > MAX_PDF_BYTES:
        raise ValueError("PDF exceeds the input-size limit")

    started_at = time.monotonic()
    reader = _load_pdf_reader(path)
    if time.monotonic() - started_at > MAX_PDF_SECONDS:
        raise ValueError("PDF processing timed out")
    if reader.is_encrypted:
        raise ValueError("encrypted PDFs are not supported")
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ValueError("PDF exceeds the page-count limit")

    parts = []
    character_count = 0
    for page in reader.pages:
        if time.monotonic() - started_at > MAX_PDF_SECONDS:
            raise ValueError("PDF processing timed out")
        page_text = page.extract_text() or ""
        if time.monotonic() - started_at > MAX_PDF_SECONDS:
            raise ValueError("PDF processing timed out")
        character_count += len(page_text)
        if character_count > MAX_PDF_CHARACTERS:
            raise ValueError("PDF exceeds the extracted-character limit")
        parts.append(page_text)
    return "\n\n".join(parts)


def _extract_pdf_text(path):
    resolved_path = Path(path).resolve()
    if resolved_path.stat().st_size > MAX_PDF_BYTES:
        raise ValueError("PDF exceeds the input-size limit")

    command = [
        "python3",
        str(Path(__file__).resolve()),
        "--extract-pdf-worker",
        str(resolved_path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=MAX_PDF_SECONDS,
            env={
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
            },
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("PDF processing timed out") from exc
    except OSError as exc:
        raise ValueError(f"PDF worker could not start: {exc}") from exc

    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(error[:1000] or "PDF processing failed")
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("PDF worker returned invalid UTF-8") from exc


def process_attachment(path, content_type):
    original_path = Path(path)
    try:
        if content_type in {
            "text/plain",
            "text/markdown",
            "application/json",
            "text/csv",
        }:
            normalized = _read_normalized_text(original_path)
            derived_path = (
                original_path
                if content_type == "text/plain"
                else _write_text_sidecar(original_path, normalized)
            )
        elif content_type == "application/pdf":
            extracted = _extract_pdf_text(original_path)
            derived_path = _write_text_sidecar(original_path, extracted)
        else:
            raise ValueError(f"unsupported attachment content type: {content_type}")
    except Exception as exc:
        return AttachmentProcessingResult(
            original_path=original_path,
            derived_text_path=None,
            content_type=content_type,
            error=str(exc),
        )

    return AttachmentProcessingResult(
        original_path=original_path,
        derived_text_path=derived_path,
        content_type=content_type,
        error=None,
    )


def _apply_pdf_worker_memory_limit():
    import resource

    resource.setrlimit(
        resource.RLIMIT_AS,
        (MAX_PDF_MEMORY_BYTES, MAX_PDF_MEMORY_BYTES),
    )


def _pdf_worker_main(path):
    try:
        _apply_pdf_worker_memory_limit()
        text = _extract_pdf_text_in_process(Path(path))
    except Exception as exc:
        sys.stderr.write(str(exc))
        return 1
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--extract-pdf-worker":
        sys.stderr.write("invalid PDF worker invocation")
        raise SystemExit(2)
    raise SystemExit(_pdf_worker_main(sys.argv[2]))
