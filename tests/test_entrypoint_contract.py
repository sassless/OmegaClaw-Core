import re
from pathlib import Path


ENTRYPOINT = Path(__file__).parents[1] / "entrypoint.sh"


def _safe_vars(source: str) -> set[str]:
    match = re.search(r'^SAFE_VARS="(?P<body>.*?)"', source, re.DOTALL | re.MULTILINE)
    assert match is not None
    return set(match.group("body").replace("\\\n", " ").split())


def test_asi_create_variables_are_allowlisted():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert {"WS_URL", "WS_TOKEN", "MCP_JSON_CONTENT"} <= _safe_vars(source)


def test_scrubbed_environment_uses_an_argument_array():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "env_args=()" in source
    assert 'val="${!var:-}"' in source
    assert 'env -i "${env_args[@]}"' in source
