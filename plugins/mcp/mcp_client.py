"""MCP client integration exposed to the MeTTa plugin."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic
from typing import Any, AsyncIterator

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.logger import get_logger


logger = get_logger(__name__)

CACHE_TTL_SECONDS = 300
MCP_OPERATION_TIMEOUT_SECONDS = 30

SERVERS_CONFIG_MAP: dict[str, dict[str, Any]] = {}
TOOL_ROUTING_MAP: dict[str, str] = {}
LAST_TOOL_LIST: list[str] = []
LAST_REFRESH_TIME: float | None = None
_CONFIG_VALID = True
_CACHE_LOCK = threading.Lock()


def _load_mcp_config_to_memory() -> None:
    """Load MCP configuration without ever logging its potentially secret values."""
    global SERVERS_CONFIG_MAP, _CONFIG_VALID

    raw_config = os.environ.get("MCP_JSON_CONTENT", "")
    if not raw_config.strip():
        SERVERS_CONFIG_MAP = {}
        _CONFIG_VALID = True
        return

    try:
        parsed = json.loads(raw_config)
        servers = parsed.get("mcpServers", {})
        if not isinstance(parsed, dict) or not isinstance(servers, dict):
            raise ValueError("invalid MCP configuration shape")
        if not all(isinstance(name, str) and isinstance(config, dict)
                   for name, config in servers.items()):
            raise ValueError("invalid MCP server configuration shape")
    except (AttributeError, json.JSONDecodeError, TypeError, ValueError) as error:
        SERVERS_CONFIG_MAP = {}
        _CONFIG_VALID = False
        logger.error("MCP configuration is invalid (%s)", type(error).__name__)
        return

    SERVERS_CONFIG_MAP = servers
    _CONFIG_VALID = True
    logger.info("Loaded MCP configuration for %d server(s)", len(servers))


@asynccontextmanager
async def _connect_to_server(
    server_name: str, config: dict[str, Any]
) -> AsyncIterator[tuple[Any, Any]]:
    transport = config.get("transport", "sse")
    url = config.get("url")
    headers = config.get("headers", {})
    if not isinstance(headers, dict):
        headers = {}

    if transport == "sse":
        async with sse_client(url=url, headers=headers) as streams:
            yield streams[0], streams[1]
        return

    if transport == "streamable-http":
        async with httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=httpx.Timeout(MCP_OPERATION_TIMEOUT_SECONDS),
        ) as http_client:
            async with streamable_http_client(
                url, http_client=http_client
            ) as streams:
                yield streams[0], streams[1]
        return

    raise ValueError(
        f"Unsupported MCP transport '{transport}' for server '{server_name}'"
    )


def _tool_description(tool: Any) -> str:
    properties = getattr(tool, "inputSchema", {}).get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
    arguments = json.dumps(
        {name: f"<{name}>" for name in properties}, separators=(",", ":")
    )
    description = getattr(tool, "description", None) or "No description"
    return f"- {description}: call-mcp {tool.name} {arguments}"


async def _discover_and_map_server(
    server_name: str, config: dict[str, Any]
) -> list[str]:
    if not config.get("url"):
        logger.warning("MCP server '%s' has no URL", server_name)
        return []

    try:
        async with asyncio.timeout(MCP_OPERATION_TIMEOUT_SECONDS):
            async with _connect_to_server(server_name, config) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    response = await session.list_tools()
        descriptions = []
        for tool in response.tools:
            TOOL_ROUTING_MAP[tool.name] = server_name
            descriptions.append(_tool_description(tool))
        logger.info(
            "Discovered %d MCP tool(s) from server '%s'",
            len(descriptions),
            server_name,
        )
        return descriptions
    except asyncio.TimeoutError:
        logger.warning("MCP discovery timed out for server '%s'", server_name)
    except Exception as error:
        logger.warning(
            "MCP discovery failed for server '%s' (%s)",
            server_name,
            type(error).__name__,
        )
    return []


async def _execute_tool_on_server(
    server_name: str,
    config: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
) -> Any:
    async with asyncio.timeout(MCP_OPERATION_TIMEOUT_SECONDS):
        async with _connect_to_server(server_name, config) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(tool_name, arguments=arguments)


def _run_async(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


def _update_server_tools_if_needed(force_update: bool = False) -> None:
    global LAST_REFRESH_TIME, LAST_TOOL_LIST

    with _CACHE_LOCK:
        now = monotonic()
        if (
            not force_update
            and LAST_REFRESH_TIME is not None
            and now - LAST_REFRESH_TIME <= CACHE_TTL_SECONDS
        ):
            return

        _load_mcp_config_to_memory()
        TOOL_ROUTING_MAP.clear()
        if not _CONFIG_VALID or not SERVERS_CONFIG_MAP:
            LAST_TOOL_LIST = []
            LAST_REFRESH_TIME = now
            return

        async def discover_all() -> list[list[str]]:
            return await asyncio.gather(
                *(
                    _discover_and_map_server(server_name, config)
                    for server_name, config in SERVERS_CONFIG_MAP.items()
                )
            )

        discovered = _run_async(discover_all())
        LAST_TOOL_LIST = [item for server_tools in discovered for item in server_tools]
        LAST_REFRESH_TIME = now


def get_tools_as_list() -> list[str]:
    _update_server_tools_if_needed()
    return list(LAST_TOOL_LIST)


def get_tools_prompt() -> str:
    return "\n".join(get_tools_as_list())


def _parse_arguments(arguments: Any) -> dict[str, Any]:
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return dict(arguments)
    if isinstance(arguments, str):
        parsed = json.loads(arguments)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("MCP tool arguments must be a JSON object")


def _is_not_found(error: Exception) -> bool:
    if getattr(error, "status_code", None) == 404:
        return True
    message = str(error).lower()
    return "not found" in message or "404" in message


def _public_result(result: Any) -> str:
    return "\n".join(
        item.text
        for item in getattr(result, "content", [])
        if isinstance(getattr(item, "text", None), str)
    )


def call_tool(tool_name: str, arguments: Any = None) -> str:
    try:
        parsed_arguments = _parse_arguments(arguments)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        logger.warning("Invalid MCP tool arguments (%s)", type(error).__name__)
        return "Error: MCP operation failed"

    _update_server_tools_if_needed()
    if not _CONFIG_VALID:
        return "Error: MCP configuration is invalid"

    for attempt in range(2):
        server_name = TOOL_ROUTING_MAP.get(tool_name)
        config = SERVERS_CONFIG_MAP.get(server_name) if server_name else None
        if config is None:
            return f"Error: Tool '{tool_name}' cannot be resolved"

        try:
            return _public_result(
                _run_async(
                    _execute_tool_on_server(
                        server_name, config, tool_name, parsed_arguments
                    )
                )
            )
        except asyncio.TimeoutError:
            logger.warning("MCP tool call timed out")
            return "Error: MCP operation timed out"
        except Exception as error:
            if attempt == 0 and _is_not_found(error):
                _update_server_tools_if_needed(force_update=True)
                continue
            logger.warning("MCP tool call failed (%s)", type(error).__name__)
            return "Error: MCP operation failed"

    return "Error: MCP operation failed"
