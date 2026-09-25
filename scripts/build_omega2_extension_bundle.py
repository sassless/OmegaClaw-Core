"""Build the versioned ASI extension bundle for the Omega 2 runtime."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_ROOT = REPO_ROOT / "extensions" / "omega2"
PACKAGE_NAME = "asi-omega-extensions"
SOURCE_FILES = {
    "config/plugins.yaml": REPO_ROOT / "deploy" / "omega2" / "config" / "plugins.yaml",
    "memory/prompt.txt": REPO_ROOT / "memory" / "prompt.txt",
    "memory/prompt_ASICloud.txt": REPO_ROOT / "memory" / "prompt_ASICloud.txt",
    "plugins/mcp/mcp.metta": REPO_ROOT / "plugins" / "mcp" / "mcp.metta",
    "plugins/mcp/mcp_client.py": REPO_ROOT / "plugins" / "mcp" / "mcp_client.py",
    "plugins/asi_create_context/asi_create_context.metta": REPO_ROOT / "plugins" / "asi_create_context" / "asi_create_context.metta",
    "plugins/asi_create_context/context_file.py": REPO_ROOT / "plugins" / "asi_create_context" / "context_file.py",
    "plugins/wschat/chat_attachments.py": REPO_ROOT / "plugins" / "wschat" / "chat_attachments.py",
    "plugins/wschat/asi_wschat.py": REPO_ROOT / "plugins" / "wschat" / "asi_wschat.py",
    "plugins/wschat/wschat.metta": REPO_ROOT / "plugins" / "wschat" / "wschat.metta",
    "requirements.txt": REPO_ROOT / "deploy" / "omega2" / "requirements.txt",
}


def _release_metadata() -> tuple[str, bytes]:
    version = (RELEASE_ROOT / "VERSION").read_text(encoding="ascii").strip()
    manifest_path = RELEASE_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("name") != PACKAGE_NAME:
        raise ValueError(f"manifest name must be {PACKAGE_NAME!r}")
    if manifest.get("version") != version:
        raise ValueError("VERSION and manifest.json version do not match")
    manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    return version, manifest_bytes


def _add_bytes(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mode = 0o644
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    archive.addfile(info, io.BytesIO(content))


def build_bundle(output_dir: Path) -> tuple[Path, Path]:
    version, manifest_bytes = _release_metadata()
    package_root = f"{PACKAGE_NAME}-{version}"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"{package_root}.tar.gz"

    files = {
        "VERSION": f"{version}\n".encode("ascii"),
        "manifest.json": manifest_bytes,
        **{
            destination: source.read_bytes()
            for destination, source in SOURCE_FILES.items()
        },
    }

    with (
        archive_path.open("wb") as raw_archive,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw_archive, mtime=0) as gz,
        tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as archive,
    ):
        for relative_path in sorted(files):
            _add_bytes(
                archive,
                f"{package_root}/{relative_path}",
                files[relative_path],
            )

    checksum_path = archive_path.with_name(f"{archive_path.name}.sha256")
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{digest}  {archive_path.name}\n", encoding="ascii")
    return archive_path.resolve(), checksum_path.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "dist",
        help="directory for the archive and checksum (default: ./dist)",
    )
    args = parser.parse_args()

    archive_path, checksum_path = build_bundle(args.output_dir)
    print(archive_path)
    print(checksum_path)


if __name__ == "__main__":
    main()
