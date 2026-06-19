import asyncio
import json
import logging
import os
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.sse import sse_client

CONFIG_PATH = Path(__file__).parents[1].joinpath("mcp.json")
MCP_JSON_CONTENT = os.environ.get("MCP_JSON_CONTENT")

SERVERS_CONFIG_MAP = {}
TOOL_ROUTING_MAP = {}  # tool name -> server name
LAST_TOOL_LIST = []
LAST_REFRESH_TIME = 0
CACHE_TTL_SECONDS = 300


def _get_logger():
    _logger = logging.getLogger("MCPClientLogger")
    _logger.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler("mcp_client.log", "a")
    file_handler.setLevel(logging.DEBUG)

    log_format = logging.Formatter("%(asctime)s – %(name)s – %(levelname)s – %(message)s")
    file_handler.setFormatter(log_format)

    _logger.addHandler(file_handler)

    return _logger


logger = _get_logger()
logger.debug(f"MCP_JSON_CONTENT = {MCP_JSON_CONTENT}")


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
            logger.info(f"SERVERS_CONFIG_MAP: {SERVERS_CONFIG_MAP}")
            return
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse inner MCP_JSON_CONTENT string atom: {str(e)}")

    if not os.path.exists(CONFIG_PATH):
        SERVERS_CONFIG_MAP = {}
        logger.info(f"SERVERS_CONFIG_MAP: {SERVERS_CONFIG_MAP}")
        return

    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)

    SERVERS_CONFIG_MAP = config.get("mcpServers", {})
    logger.info(f"SERVERS_CONFIG_MAP: {SERVERS_CONFIG_MAP}")


async def _discover_and_map_server(server_name: str, cfg: dict) -> list[str]:
    global TOOL_ROUTING_MAP

    if "url" not in cfg:
        return []

    try:
        headers = cfg.get("headers", {})
        async with sse_client(url=cfg["url"], headers=headers) as (r, w):
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
async def _execute_tool_on_server(cfg: dict, tool_name: str, arguments: dict):
    headers = cfg.get("headers", {})
    async with sse_client(url=cfg["url"], headers=headers) as (r, w):
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
        # for name, desc, param_keys in tool_list:
        #     formatted_skills.append(f'"- {desc}: call-mcp {name} {param_keys}"')
        for server_tool_as_json_string in server_tools:
            formatted_skills.append(server_tool_as_json_string)

    skills_for_log = "\n\t".join(formatted_skills)
    logger.info(f"MCP_TOOLS_LIST:\n{skills_for_log}")

    LAST_TOOL_LIST = formatted_skills

    LAST_REFRESH_TIME = time.time()


def get_tools_as_list() -> list[str]:

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
        tool_result = _run_async(_execute_tool_on_server(target_config, name, args))
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
