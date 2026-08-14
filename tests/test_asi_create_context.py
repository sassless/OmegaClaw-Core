import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "plugins"
    / "asi_create_context"
    / "context_file.py"
)


@pytest.fixture
def context_file_module():
    if not MODULE_PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location(
        "asi_create_context_file_under_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_context_returns_empty_string(tmp_path, context_file_module):
    assert context_file_module is not None
    assert context_file_module.read_context(tmp_path / "missing.txt") == ""


def test_context_path_is_absolute_and_uses_the_managed_filename(
    tmp_path, context_file_module
):
    assert context_file_module is not None
    assert context_file_module.context_path(tmp_path) == str(
        (tmp_path / "asi_create_context.txt").resolve()
    )


def test_context_is_read_again_after_atomic_replacement(tmp_path, context_file_module):
    assert context_file_module is not None
    path = tmp_path / "asi_create_context.txt"
    path.write_text("first", encoding="utf-8")
    assert context_file_module.read_context(path) == "first"

    replacement = tmp_path / ".asi_create_context.next"
    replacement.write_text("second", encoding="utf-8")
    replacement.replace(path)

    assert context_file_module.read_context(path) == "second"


def test_permission_errors_are_not_treated_as_missing(
    monkeypatch, context_file_module
):
    assert context_file_module is not None

    def permission_denied(*_args, **_kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(context_file_module.Path, "read_text", permission_denied)
    with pytest.raises(PermissionError, match="denied"):
        context_file_module.read_context("context.txt")
