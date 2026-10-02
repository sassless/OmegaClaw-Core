from pathlib import Path


def context_path(_memory_directory: str) -> str:
    try:
        from config import config_get_by_key
    except ModuleNotFoundError:
        configured_path = ""
    else:
        configured_path = str(config_get_by_key("asiCreateContextPath", "") or "").strip()
    if configured_path:
        return str(Path(configured_path).resolve())

    directory = Path(__file__).resolve().parents[2] / "memory"
    return str((directory / "asi_create_context.txt").resolve())


def read_context(path: str) -> str:
    try:
        return Path(str(path).strip('"')).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
