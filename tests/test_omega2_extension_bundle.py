import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_omega2_extension_bundle.py"
EXPECTED_FILES = {
    "VERSION",
    "config/plugins.yaml",
    "manifest.json",
    "memory/prompt.txt",
    "memory/prompt_ASICloud.txt",
    "plugins/mcp/mcp.metta",
    "plugins/mcp/mcp_client.py",
    "plugins/asi_create_context/asi_create_context.metta",
    "plugins/asi_create_context/context_file.py",
    "plugins/wschat/chat_attachments.py",
    "plugins/wschat/asi_wschat.py",
    "plugins/wschat/wschat.metta",
    "requirements.txt",
}


def _build_bundle(output_dir: Path) -> tuple[Path, Path]:
    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--output-dir", str(output_dir)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    archive_path, checksum_path = map(Path, result.stdout.strip().splitlines())
    return archive_path, checksum_path


def test_bundle_contains_versioned_runtime_contract(tmp_path):
    archive_path, checksum_path = _build_bundle(tmp_path)

    assert archive_path.name == "asi-omega-extensions-0.1.4.tar.gz"
    assert checksum_path.name == f"{archive_path.name}.sha256"

    with tarfile.open(archive_path, "r:gz") as archive:
        root = "asi-omega-extensions-0.1.4"
        members = {
            member.name.removeprefix(f"{root}/")
            for member in archive.getmembers()
            if member.isfile()
        }
        assert members == EXPECTED_FILES

        manifest = json.load(archive.extractfile(f"{root}/manifest.json"))
        assert manifest["name"] == "asi-omega-extensions"
        assert manifest["version"] == "0.1.4"
        for name in manifest["prompt_files"]:
            assert archive.extractfile(f"{root}/{name}").read() == (
                REPO_ROOT / name
            ).read_bytes()
        assert manifest["omega"]["image"].startswith(
            "singularitynet/omega@sha256:"
        )
        assert manifest["plugins"] == [
            {"name": "mcp", "loader": "metta", "path": "plugins/mcp"},
            {"name": "wschat", "loader": "metta", "path": "plugins/wschat"},
            {"name": "asi_create_context", "loader": "metta", "path": "plugins/asi_create_context"},
        ]

    expected_digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert checksum_path.read_text(encoding="ascii") == (
        f"{expected_digest}  {archive_path.name}\n"
    )


def test_bundle_is_reproducible(tmp_path):
    first_archive, _ = _build_bundle(tmp_path / "first")
    second_archive, _ = _build_bundle(tmp_path / "second")

    assert first_archive.read_bytes() == second_archive.read_bytes()
