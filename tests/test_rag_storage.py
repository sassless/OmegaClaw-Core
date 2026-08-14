import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parents[1]
RAG_PATH = REPO_ROOT / "src" / "rag.py"
POLICY_PATH = REPO_ROOT / "profile"
CONTEXT_PLUGIN_PATH = REPO_ROOT / "plugins" / "asi_create_context"


@pytest.fixture
def load_rag(monkeypatch):
    def load():
        chromadb_module = types.ModuleType("chromadb")
        openai_module = types.ModuleType("openai")
        llm_module = types.ModuleType("lib_llm_ext")
        llm_module.initLocalEmbedding = lambda: None
        llm_module.useLocalEmbedding = lambda _text: [0.0]
        config_module = types.ModuleType("config")
        config_module.config_get_by_key = lambda _key, default=None: default

        monkeypatch.setitem(sys.modules, "chromadb", chromadb_module)
        monkeypatch.setitem(sys.modules, "openai", openai_module)
        monkeypatch.setitem(sys.modules, "lib_llm_ext", llm_module)
        monkeypatch.setitem(sys.modules, "config", config_module)

        spec = importlib.util.spec_from_file_location("rag_storage_under_test", RAG_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return load


@pytest.mark.skipif(
    "MEMORY_DIR" not in os.environ or not Path("/PeTTa/chroma_db").exists(),
    reason="requires the OmegaClaw release image memory symlink",
)
def test_default_database_path_uses_runtime_chroma_symlink(monkeypatch, load_rag):
    monkeypatch.delenv("CHROMA_DB_PATH", raising=False)
    assert Path(load_rag().DB_PATH).resolve() == (
        Path(os.environ["MEMORY_DIR"]) / "chroma_db"
    ).resolve()


def test_database_path_can_be_overridden(monkeypatch, load_rag):
    monkeypatch.setenv("CHROMA_DB_PATH", "/tmp/custom-chroma")
    assert load_rag().DB_PATH == "/tmp/custom-chroma"


@pytest.mark.skipif(sys.platform != "linux", reason="Landlock requires Linux")
def test_policy_allows_cross_directory_rename(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "file").write_text("content", encoding="utf-8")
    script = f"""
import os
import sys
sys.path.insert(0, {str(POLICY_PATH)!r})
from policy import FileSystemPolicy

policy = FileSystemPolicy()
policy.load_dict({{
    "version": 1,
    "landlock": {{"compatibility": "hard_requirement"}},
    "filesystem_policy": {{
        "include_workdir": False,
        "read_write": [{str(tmp_path)!r}],
    }},
}})
policy.apply()
os.replace({str(source / 'file')!r}, {str(target / 'file')!r})
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
    assert (target / "file").read_text(encoding="utf-8") == "content"


@pytest.mark.skipif(sys.platform != "linux", reason="Landlock requires Linux")
def test_context_file_remains_readable_after_policy_application(tmp_path):
    context_path = tmp_path / "asi_create_context.txt"
    context_path.write_text("managed context", encoding="utf-8")
    script = f"""
import sys
sys.path.insert(0, {str(POLICY_PATH)!r})
sys.path.insert(0, {str(CONTEXT_PLUGIN_PATH)!r})
from policy import FileSystemPolicy
from context_file import read_context

policy = FileSystemPolicy()
policy.load_dict({{
    "version": 1,
    "landlock": {{"compatibility": "hard_requirement"}},
    "filesystem_policy": {{
        "include_workdir": False,
        "read_write": [{str(tmp_path)!r}],
    }},
}})
policy.apply()
assert read_context({str(context_path)!r}) == "managed context"
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
