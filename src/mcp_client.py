import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

CONFIG_PATH = Path(__file__).parents[1].joinpath("mcp.json")
MCP_JSON_CONTENT = os.environ.get("MCP_JSON_CONTENT")

SERVERS_CONFIG_MAP = {}
TOOL_ROUTING_MAP = {}  # tool name -> server name
LAST_TOOL_LIST = []
LAST_REFRESH_TIME = 0
CACHE_TTL_SECONDS = 300
MCP_OPERATION_TIMEOUT_SECONDS = 30


def _get_logger():
    _logger = logging.getLogger("MCPClientLogger")
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False

    if _logger.handlers:
        return _logger

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG)

    log_format = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    stream_handler.setFormatter(log_format)

    _logger.addHandler(stream_handler)

    return _logger


logger = _get_logger()
logger.debug(f"MCP_JSON_CONTENT configured: {bool(MCP_JSON_CONTENT)}")


def _run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError as e:
        logger.error(f"Error during _run_async: {str(e)}")
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return asyncio.ensure_future(coro, loop=loop)
        return loop.run_until_complete(coro)


def _load_mcp_config_to_memory():
    global SERVERS_CONFIG_MAP, MCP_JSON_CONTENT

    if MCP_JSON_CONTENT and MCP_JSON_CONTENT.strip():
        try:
            config = json.loads(MCP_JSON_CONTENT)
            SERVERS_CONFIG_MAP = config.get("mcpServers", {})
            logger.info(f"Configured MCP servers: {list(SERVERS_CONFIG_MAP)}")
            return
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse inner MCP_JSON_CONTENT string atom: {str(e)}")

    if not os.path.exists(CONFIG_PATH):
        SERVERS_CONFIG_MAP = {}
        logger.info("Configured MCP servers: []")
        return

    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)

    SERVERS_CONFIG_MAP = config.get("mcpServers", {})
    logger.info(f"Configured MCP servers: {list(SERVERS_CONFIG_MAP)}")


@asynccontextmanager
async def _connect_to_server(server_name: str, cfg: dict):
    transport = cfg.get("transport", "sse")
    headers = cfg.get("headers", {})

    if transport == "sse":
        async with sse_client(url=cfg["url"], headers=headers) as streams:
            yield streams
        return

    if transport == "streamable-http":
        async with httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=httpx.Timeout(MCP_OPERATION_TIMEOUT_SECONDS),
        ) as http_client:
            async with streamable_http_client(
                url=cfg["url"],
                http_client=http_client,
            ) as (read_stream, write_stream, _):
                yield read_stream, write_stream
        return

    raise ValueError(
        f"Unsupported MCP transport '{transport}' for server '{server_name}'"
    )


async def _discover_and_map_server(server_name: str, cfg: dict) -> list[str]:
    global TOOL_ROUTING_MAP

    if "url" not in cfg:
        return []

    try:
        async with asyncio.timeout(MCP_OPERATION_TIMEOUT_SECONDS):
            async with _connect_to_server(server_name, cfg) as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    res = await session.list_tools()
                    logger.info(f"List tools for server {server_name}: {res}")
                    # return res.model_dump_json()

                    # tools_found = []
                    # for tool in res.tools:
                    #     TOOL_ROUTING_MAP[tool.name] = server_name
                    #
                    #     schema = tool.inputSchema.get("properties", {})
                    #     tools_found.append(
                    #         (tool.name, tool.description, list(schema.keys()))
                    #     )
                    # return tools_found

                tools_found = []
                for tool in res.tools:
                    TOOL_ROUTING_MAP[tool.name] = server_name
                    tools_found.append(tool.model_dump_json())
                logger.info(f"TOOL_ROUTING_MAP: {TOOL_ROUTING_MAP}")
                return tools_found

    except Exception as e:
        logger.error(f"Failed to scan tools from server '{server_name}': {str(e)}")
    return []


# we probably should use persistent session implementation to reuse session for multiple tool calls
# and not to reconnect every time we call mcp server
async def _execute_tool_on_server(
    server_name: str, cfg: dict, tool_name: str, arguments: dict
):
    async with asyncio.timeout(MCP_OPERATION_TIMEOUT_SECONDS):
        async with _connect_to_server(server_name, cfg) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                logger.info(f"Calling {tool_name} tool with arguments: {arguments}")
                return await session.call_tool(tool_name, arguments=arguments)


def _update_server_tools_if_needed(force_update: bool = False):
    logger.info("Updating server tools")
    global \
        TOOL_ROUTING_MAP, \
        LAST_TOOL_LIST, \
        LAST_REFRESH_TIME, \
        SERVERS_CONFIG_MAP

    if not SERVERS_CONFIG_MAP:
        _load_mcp_config_to_memory()

    current_time = time.time()
    cache_is_expired = (current_time - LAST_REFRESH_TIME) > CACHE_TTL_SECONDS

    if LAST_TOOL_LIST and not cache_is_expired and not force_update:
        logger.info("No need to update")
        return

    TOOL_ROUTING_MAP.clear()

    all_tasks = [
        _discover_and_map_server(name, cfg) for name, cfg in SERVERS_CONFIG_MAP.items()
    ]

    async def _gather_tasks():
        return await asyncio.gather(*all_tasks)

    resolved_lists = _run_async(_gather_tasks())

    formatted_skills = []
    for server_tools in resolved_lists:
        for tool_data in server_tools:
            if isinstance(tool_data, str):
                try:
                    parsed = json.loads(tool_data)
                    name = parsed.get("name", "unknown")
                    desc = parsed.get("description", "No description")
                    # Extract parameter keys if inputSchema is present
                    schema_props = parsed.get("inputSchema", {}).get("properties", {})
                    params = list(schema_props.keys())
                except json.JSONDecodeError:
                    logger.error(f"Could not parse tool JSON: {tool_data}")
                    continue
            elif isinstance(tool_data, tuple):
                name, desc, params = tool_data[0], tool_data[1], tool_data[2]
            else:
                continue

            param_string = " ".join(params) if params else ""
            skill_string = f"- {desc}: call-mcp {name} {param_string}".strip()

            formatted_skills.append(skill_string)

    skills_for_log = "\n\t".join(formatted_skills)
    logger.info(f"MCP_TOOLS_LIST:\n\t{skills_for_log}")

    LAST_TOOL_LIST = formatted_skills
    LAST_REFRESH_TIME = time.time()


def get_tools_as_list() -> list:
    _update_server_tools_if_needed()
    return LAST_TOOL_LIST


def call_tool(name: str, parameters_input: str | dict | None = None) -> str:
    global TOOL_ROUTING_MAP, SERVERS_CONFIG_MAP

    logger.debug(f"tool_name='{name}', parameters type='{type(parameters_input)}', parameters='{parameters_input}'")

    _update_server_tools_if_needed(name not in TOOL_ROUTING_MAP)

    server_name = TOOL_ROUTING_MAP.get(name)
    if not server_name:
        logger.error(f"Error: Tool '{name}' cannot be resolved.")
        return f"Error: Tool '{name}' cannot be resolved."

    target_config = SERVERS_CONFIG_MAP.get(server_name)
    if not target_config:
        logger.error(f"Error: Configuration for server '{server_name}' missing.")
        return f"Error: Configuration for server '{server_name}' missing."

    if parameters_input is None:
        args = {}
    elif isinstance(parameters_input, str):
        try:
            args = json.loads(parameters_input)
        except json.JSONDecodeError:
            args = {}
    else:
        args = dict(parameters_input)

    try:
        tool_result = _run_async(
            _execute_tool_on_server(server_name, target_config, name, args)
        )
        logger.debug(f"tool_result: {tool_result}")
        text_responses = [c.text for c in tool_result.content if hasattr(c, "text")]
        logger.debug(f"text_responses: {text_responses}")
        return "\n".join(text_responses)
    except Exception as e:
        if "not found" in str(e).lower() or "404" in str(e):
            logger.exception(f"Error 404 Not Found. Removing tool {name} from the map.")
            TOOL_ROUTING_MAP.pop(name, None)
        logger.error(f"Execution Error on tool '{name}': {str(e)}")
        return f"Execution Error on tool '{name}': {str(e)}"
