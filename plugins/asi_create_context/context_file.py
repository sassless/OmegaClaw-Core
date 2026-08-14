from pathlib import Path


def context_path(memory_directory: str) -> str:
    directory = Path(str(memory_directory).strip('"'))
    return str((directory / "asi_create_context.txt").resolve())


def read_context(path: str) -> str:
    try:
        return Path(str(path).strip('"')).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
