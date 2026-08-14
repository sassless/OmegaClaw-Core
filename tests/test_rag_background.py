import importlib.util
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


REPO_ROOT = Path(__file__).parents[1]
RAG_PATH = REPO_ROOT / "src" / "rag.py"
LOOP_PATH = REPO_ROOT / "src" / "loop.metta"


@pytest.fixture
def rag(monkeypatch):
    chromadb_module = types.ModuleType("chromadb")
    openai_module = types.ModuleType("openai")
    llm_module = types.ModuleType("lib_llm_ext")
    llm_module.initLocalEmbedding = lambda: None
    llm_module.useLocalEmbedding = lambda _text: []
    config_module = types.ModuleType("config")
    config_module.config_get_by_key = lambda _key, default=None: default

    monkeypatch.syspath_prepend(str(REPO_ROOT))
    monkeypatch.setitem(sys.modules, "chromadb", chromadb_module)
    monkeypatch.setitem(sys.modules, "openai", openai_module)
    monkeypatch.setitem(sys.modules, "lib_llm_ext", llm_module)
    monkeypatch.setitem(sys.modules, "config", config_module)

    spec = importlib.util.spec_from_file_location("rag_background_under_test", RAG_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _join_worker(rag):
    worker = rag._knowledge_init_thread
    if worker is not None:
        worker.join(timeout=1)
        assert not worker.is_alive()


def test_start_returns_without_waiting_for_indexing(rag):
    started = threading.Event()
    release = threading.Event()

    def blocking_init(_selection):
        started.set()
        release.wait(timeout=2)
        return "Knowledge: ready"

    rag.init_knowledge = blocking_init
    before = time.monotonic()
    result = rag.start_knowledge_init("Local")
    elapsed = time.monotonic() - before

    assert result == "Knowledge initialization started"
    assert started.wait(timeout=1)
    assert elapsed < 0.25
    release.set()
    _join_worker(rag)


def test_worker_is_daemon_and_named_knowledge_init(rag):
    release = threading.Event()
    rag.init_knowledge = lambda _selection: release.wait(timeout=2)

    rag.start_knowledge_init("Local")
    worker = rag._knowledge_init_thread

    assert worker.name == "knowledge-init"
    assert worker.daemon is True
    release.set()
    _join_worker(rag)


def test_second_concurrent_start_does_not_spawn_another_worker(rag):
    started = threading.Event()
    release = threading.Event()
    calls = []

    def blocking_init(selection):
        calls.append(selection)
        started.set()
        release.wait(timeout=2)
        return "done"

    rag.init_knowledge = blocking_init
    assert rag.start_knowledge_init("Local") == "Knowledge initialization started"
    assert started.wait(timeout=1)
    first_worker = rag._knowledge_init_thread

    assert rag.start_knowledge_init("OpenAI") == (
        "Knowledge initialization already running"
    )
    assert rag._knowledge_init_thread is first_worker
    assert calls == ["Local"]
    release.set()
    _join_worker(rag)


def test_success_result_is_logged(rag):
    rag.logger.info = MagicMock()
    release = threading.Event()

    def successful_init(_selection):
        release.wait(timeout=2)
        return "Knowledge: ready"

    rag.init_knowledge = successful_init

    rag.start_knowledge_init("Local")
    worker = rag._knowledge_init_thread
    release.set()
    worker.join(timeout=1)

    rag.logger.info.assert_any_call("Knowledge: ready")


def test_unexpected_worker_exception_is_logged_and_does_not_escape(rag):
    rag.logger.exception = MagicMock()

    def fail(_selection):
        raise RuntimeError("unexpected")

    rag.init_knowledge = fail
    assert rag.start_knowledge_init("Local") == "Knowledge initialization started"
    deadline = time.monotonic() + 1
    while not rag.logger.exception.called and time.monotonic() < deadline:
        time.sleep(0.001)
    rag.logger.exception.assert_called_once()


def test_completed_worker_allows_a_later_refresh(rag):
    calls = []
    release = threading.Event()

    def controlled_init(selection):
        calls.append(selection)
        release.wait(timeout=2)
        return "done"

    rag.init_knowledge = controlled_init

    assert rag.start_knowledge_init("Local") == "Knowledge initialization started"
    first_worker = rag._knowledge_init_thread
    release.set()
    first_worker.join(timeout=1)
    assert not first_worker.is_alive()

    release.clear()
    assert rag.start_knowledge_init("OpenAI") == "Knowledge initialization started"
    second_worker = rag._knowledge_init_thread
    release.set()
    second_worker.join(timeout=1)

    assert second_worker is not first_worker
    assert calls == ["Local", "OpenAI"]


def test_loop_calls_start_knowledge_init_for_local_and_openai():
    source = LOOP_PATH.read_text(encoding="utf-8")

    assert "rag.init_knowledge" not in source
    assert source.count("rag.start_knowledge_init") == 2
