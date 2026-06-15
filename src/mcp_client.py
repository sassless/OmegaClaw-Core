import asyncio
import json
import os
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.sse import sse_client

CONFIG_PATH = Path(__file__).parents[1].joinpath("mcp.json")
MCP_JSON_CONTENT = os.environ.get("MCP_JSON_CONTENT")

SERVERS_CONFIG_MAP = {}
TOOL_ROUTING_MAP = {}  # tool name -> server name
LAST_FORMATTED_STRING = ""
LAST_REFRESH_TIME = 0
CACHE_TTL_SECONDS = 300


def _run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
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
            return
        except json.JSONDecodeError as e:
            print(f"Failed to parse inner MCP_JSON_CONTENT string atom: {e}")

    if not os.path.exists(CONFIG_PATH):
        SERVERS_CONFIG_MAP = {}
        return

    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    SERVERS_CONFIG_MAP = config.get("mcpServers", {})


async def _discover_and_map_server(server_name: str, cfg: dict):
    global TOOL_ROUTING_MAP

    if "url" not in cfg:
        return []

    try:
        headers = cfg.get("headers", {})
        async with sse_client(url=cfg["url"], headers=headers) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                res = await session.list_tools()

                tools_found = []
                for tool in res.tools:
                    TOOL_ROUTING_MAP[tool.name] = server_name

                    schema = tool.inputSchema.get("properties", {})
                    tools_found.append(
                        (tool.name, tool.description, list(schema.keys()))
                    )
                return tools_found

    except Exception as e:
        print(f"Failed to scan tools from server '{server_name}': {e}")
    return []


# we probably should use persistent session implementation to reuse session for multiple tool calls
# and not to reconnect every time we call mcp server
async def _execute_tool_on_server(cfg: dict, tool_name: str, arguments: dict):
    headers = cfg.get("headers", {})
    async with sse_client(url=cfg["url"], headers=headers) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments=arguments)


def _update_server_tools_if_needed(force_update: bool = False):
    global \
        TOOL_ROUTING_MAP, \
        LAST_FORMATTED_STRING, \
        LAST_REFRESH_TIME, \
        SERVERS_CONFIG_MAP

    if not SERVERS_CONFIG_MAP:
        _load_mcp_config_to_memory()

    current_time = time.time()
    cache_is_expired = (current_time - LAST_REFRESH_TIME) > CACHE_TTL_SECONDS

    if LAST_FORMATTED_STRING and not cache_is_expired and not force_update:
        return

    TOOL_ROUTING_MAP.clear()

    all_tasks = [
        _discover_and_map_server(name, cfg) for name, cfg in SERVERS_CONFIG_MAP.items()
    ]
    resolved_lists = _run_async(asyncio.gather(*all_tasks))

    formatted_skills = []
    for tool_list in resolved_lists:
        for name, desc, param_keys in tool_list:
            formatted_skills.append(f'"- {desc}: call-mcp {name} {param_keys}"')

    if not formatted_skills:
        LAST_FORMATTED_STRING = "()"
    else:
        LAST_FORMATTED_STRING = f"( {' '.join(formatted_skills)} )"

    LAST_REFRESH_TIME = time.time()


def get_tools_as_string() -> str:
    _update_server_tools_if_needed()
    return LAST_FORMATTED_STRING


def call_tool(name: str, parameters_input: str | dict) -> str:
    global TOOL_ROUTING_MAP, SERVERS_CONFIG_MAP

    _update_server_tools_if_needed(name not in TOOL_ROUTING_MAP)

    server_name = TOOL_ROUTING_MAP.get(name)
    if not server_name:
        return f"Error: Tool '{name}' cannot be resolved."

    target_config = SERVERS_CONFIG_MAP.get(server_name)
    if not target_config:
        return f"Error: Configuration for server '{server_name}' missing."

    if isinstance(parameters_input, str):
        try:
            args = json.loads(parameters_input)
        except json.JSONDecodeError:
            args = {}
    else:
        args = dict(parameters_input)

    try:
        tool_result = _run_async(_execute_tool_on_server(target_config, name, args))
        text_responses = [c.text for c in tool_result.content if hasattr(c, "text")]
        return "\n".join(text_responses)
    except Exception as e:
        if "not found" in str(e).lower() or "404" in str(e):
            TOOL_ROUTING_MAP.pop(name, None)
        return f"Execution Error on tool '{name}': {str(e)}"
