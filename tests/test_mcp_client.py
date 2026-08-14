import asyncio
import importlib.util
import logging
import sys
import types
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


MODULE_PATH = Path(__file__).parents[1] / "plugins" / "mcp" / "mcp_client.py"


@pytest.fixture
def mcp_client(monkeypatch):
    if not MODULE_PATH.exists():
        return types.SimpleNamespace()

    if not hasattr(asyncio, "timeout"):
        @asynccontextmanager
        async def no_timeout(_seconds):
            yield

        monkeypatch.setattr(asyncio, "timeout", no_timeout, raising=False)

    mcp_module = types.ModuleType("mcp")
    mcp_module.ClientSession = object
    mcp_client_module = types.ModuleType("mcp.client")
    mcp_sse_module = types.ModuleType("mcp.client.sse")
    mcp_sse_module.sse_client = object
    mcp_streamable_module = types.ModuleType("mcp.client.streamable_http")
    mcp_streamable_module.streamable_http_client = object
    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.client", mcp_client_module)
    monkeypatch.setitem(sys.modules, "mcp.client.sse", mcp_sse_module)
    monkeypatch.setitem(
        sys.modules,
        "mcp.client.streamable_http",
        mcp_streamable_module,
    )

    httpx_module = types.ModuleType("httpx")
    httpx_module.AsyncClient = object
    httpx_module.Timeout = lambda seconds: seconds
    monkeypatch.setitem(sys.modules, "httpx", httpx_module)

    logger_module = types.ModuleType("src.logger")
    logger_module.get_logger = logging.getLogger
    monkeypatch.setitem(sys.modules, "src.logger", logger_module)

    spec = importlib.util.spec_from_file_location("mcp_client_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_cache_and_timeout_constants_are_stable(mcp_client):
    assert mcp_client.CACHE_TTL_SECONDS == 300
    assert mcp_client.MCP_OPERATION_TIMEOUT_SECONDS == 30


def test_streamable_http_forwards_headers_to_the_backend_client(monkeypatch, mcp_client):
    http_client = AsyncMock()
    http_client.__aenter__.return_value = http_client
    http_client.__aexit__.return_value = None
    http_client_factory = MagicMock(return_value=http_client)
    captured = {}

    @asynccontextmanager
    async def streamable_client(url, *, http_client):
        captured["url"] = url
        captured["http_client"] = http_client
        yield "read", "write", lambda: None

    monkeypatch.setattr(mcp_client.httpx, "AsyncClient", http_client_factory)
    monkeypatch.setattr(mcp_client, "streamable_http_client", streamable_client)

    async def run():
        config = {
            "transport": "streamable-http",
            "url": "https://example.test/mcp",
            "headers": {"Authorization": "Bearer secret-api-key"},
        }
        async with mcp_client._connect_to_server("asi-create", config) as streams:
            assert streams == ("read", "write")

    asyncio.run(run())

    assert captured == {
        "url": "https://example.test/mcp",
        "http_client": http_client,
    }
    assert http_client_factory.call_args.kwargs["headers"] == {
        "Authorization": "Bearer secret-api-key"
    }
    assert http_client_factory.call_args.kwargs["follow_redirects"] is True


def test_missing_transport_defaults_to_sse(monkeypatch, mcp_client):
    captured = {}

    @asynccontextmanager
    async def legacy_sse_client(*, url, headers):
        captured["url"] = url
        captured["headers"] = headers
        yield "read", "write"

    monkeypatch.setattr(mcp_client, "sse_client", legacy_sse_client)

    async def run():
        config = {
            "url": "https://example.test/mcp/sse",
            "headers": {"Authorization": "Bearer secret-api-key"},
        }
        async with mcp_client._connect_to_server("legacy", config) as streams:
            assert streams == ("read", "write")

    asyncio.run(run())

    assert captured == {
        "url": "https://example.test/mcp/sse",
        "headers": {"Authorization": "Bearer secret-api-key"},
    }


def test_unknown_transport_is_rejected_without_exposing_headers(caplog, mcp_client):
    async def run():
        config = {
            "transport": "unknown",
            "url": "https://example.test/mcp",
            "headers": {"Authorization": "Bearer secret-api-key"},
        }
        async with mcp_client._connect_to_server("asi-create", config):
            pass

    with pytest.raises(ValueError, match="Unsupported MCP transport 'unknown'") as exc:
        asyncio.run(run())

    assert "secret-api-key" not in str(exc.value)
    assert "secret-api-key" not in caplog.text


def test_invalid_json_disables_mcp_without_logging_raw_config(
    caplog, monkeypatch, mcp_client
):
    monkeypatch.setenv(
        "MCP_JSON_CONTENT",
        '{"mcpServers":{"asi-create":{"headers":{"X-API-Key":"secret-api-key"}}',
    )

    with caplog.at_level(logging.INFO):
        assert mcp_client.get_tools_as_list() == []

    assert "secret-api-key" not in caplog.text
    assert "MCP configuration is invalid" in caplog.text


def test_discovery_populates_tool_to_server_routes(monkeypatch, mcp_client):
    monkeypatch.setenv(
        "MCP_JSON_CONTENT",
        '{"mcpServers":{"asi-create":{"url":"https://example.test/mcp"}}}',
    )

    @asynccontextmanager
    async def connection(_server_name, _config):
        yield "read", "write"

    tool = types.SimpleNamespace(
        name="get_user_agents",
        description="List user agents",
        inputSchema={"properties": {"user_id": {"type": "string"}}},
    )
    response = types.SimpleNamespace(tools=[tool])

    class Session:
        def __init__(self, _read, _write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def initialize(self):
            return None

        async def list_tools(self):
            return response

    monkeypatch.setattr(mcp_client, "_connect_to_server", connection)
    monkeypatch.setattr(mcp_client, "ClientSession", Session)

    assert mcp_client.get_tools_as_list() == [
        "- List user agents: call-mcp get_user_agents user_id"
    ]
    assert mcp_client.TOOL_ROUTING_MAP == {"get_user_agents": "asi-create"}


def test_call_tool_parses_json_arguments_and_returns_text_content(
    monkeypatch, mcp_client
):
    mcp_client.SERVERS_CONFIG_MAP = {"asi-create": {"url": "https://example.test"}}
    mcp_client.TOOL_ROUTING_MAP = {"get_user_agents": "asi-create"}
    captured = {}

    def keep_routes(_force_update=False):
        return None

    async def execute(server_name, config, tool_name, arguments):
        captured.update(
            server_name=server_name,
            config=config,
            tool_name=tool_name,
            arguments=arguments,
        )
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(text="first"), types.SimpleNamespace(text="second")]
        )

    monkeypatch.setattr(mcp_client, "_update_server_tools_if_needed", keep_routes)
    monkeypatch.setattr(mcp_client, "_execute_tool_on_server", execute)

    assert mcp_client.call_tool("get_user_agents", '{"limit": 2}') == "first\nsecond"
    assert captured == {
        "server_name": "asi-create",
        "config": {"url": "https://example.test"},
        "tool_name": "get_user_agents",
        "arguments": {"limit": 2},
    }


def test_discovery_and_calls_are_bounded_by_thirty_second_timeout(
    monkeypatch, mcp_client
):
    timeout_values = []

    class Timeout:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *_args):
            return None

    def timeout(seconds):
        timeout_values.append(seconds)
        return Timeout()

    @asynccontextmanager
    async def connection(_server_name, _config):
        yield "read", "write"

    class Session:
        def __init__(self, _read, _write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def initialize(self):
            return None

        async def list_tools(self):
            return types.SimpleNamespace(tools=[])

        async def call_tool(self, _name, *, arguments):
            return types.SimpleNamespace(content=[])

    monkeypatch.setattr(mcp_client.asyncio, "timeout", timeout, raising=False)
    monkeypatch.setattr(mcp_client, "_connect_to_server", connection)
    monkeypatch.setattr(mcp_client, "ClientSession", Session)

    async def run():
        await mcp_client._discover_and_map_server("server", {"url": "https://example.test"})
        await mcp_client._execute_tool_on_server(
            "server", {"url": "https://example.test"}, "tool", {}
        )

    asyncio.run(run())

    assert timeout_values == [30, 30]


def test_cached_tool_list_is_reused_for_five_minutes(monkeypatch, mcp_client):
    monkeypatch.setenv(
        "MCP_JSON_CONTENT",
        '{"mcpServers":{"asi-create":{"url":"https://example.test/mcp"}}}',
    )
    calls = []

    async def discover(server_name, _config):
        calls.append(server_name)
        mcp_client.TOOL_ROUTING_MAP["cached_tool"] = server_name
        return ["- Cached tool: call-mcp cached_tool"]

    now = iter([1000.0, 1000.0, 1200.0])
    monkeypatch.setattr(mcp_client, "_discover_and_map_server", discover)
    monkeypatch.setattr(mcp_client, "monotonic", lambda: next(now))

    assert mcp_client.get_tools_as_list() == ["- Cached tool: call-mcp cached_tool"]
    assert mcp_client.get_tools_as_list() == ["- Cached tool: call-mcp cached_tool"]
    assert calls == ["asi-create"]


def test_not_found_refreshes_routes_and_retries_once(monkeypatch, mcp_client):
    mcp_client.SERVERS_CONFIG_MAP = {"old": {"url": "https://old.test"}}
    mcp_client.TOOL_ROUTING_MAP = {"moving_tool": "old"}
    attempts = []

    def refresh(force_update=False):
        if force_update:
            mcp_client.SERVERS_CONFIG_MAP = {"new": {"url": "https://new.test"}}
            mcp_client.TOOL_ROUTING_MAP = {"moving_tool": "new"}

    async def execute(server_name, _config, _tool_name, _arguments):
        attempts.append(server_name)
        if server_name == "old":
            raise RuntimeError("404 not found")
        return types.SimpleNamespace(content=[types.SimpleNamespace(text="moved")])

    monkeypatch.setattr(mcp_client, "_update_server_tools_if_needed", refresh)
    monkeypatch.setattr(mcp_client, "_execute_tool_on_server", execute)

    assert mcp_client.call_tool("moving_tool", {}) == "moved"
    assert attempts == ["old", "new"]


def test_operational_failures_use_stable_public_errors(monkeypatch, mcp_client):
    mcp_client.SERVERS_CONFIG_MAP = {"server": {"url": "https://example.test"}}
    mcp_client.TOOL_ROUTING_MAP = {"tool": "server"}

    monkeypatch.setattr(
        mcp_client, "_update_server_tools_if_needed", lambda _force_update=False: None
    )

    async def timeout(*_args):
        raise asyncio.TimeoutError

    monkeypatch.setattr(mcp_client, "_execute_tool_on_server", timeout)
    assert mcp_client.call_tool("tool", {}) == "Error: MCP operation timed out"

    async def failed(*_args):
        raise RuntimeError("response included secret-api-key")

    monkeypatch.setattr(mcp_client, "_execute_tool_on_server", failed)
    assert mcp_client.call_tool("tool", {}) == "Error: MCP operation failed"
