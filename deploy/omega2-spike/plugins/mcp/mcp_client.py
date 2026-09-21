"""Omega 2.0 compatibility wrapper for the existing MCP client plugin."""

import helper


# Omega 2.0 registers commands through add-skill, but its text parser still
# needs to know that call-mcp accepts two arguments. Direct aliases for
# discovered remote tools were a fork feature and are unnecessary here because
# the plugin prompt tells the model to use call-mcp explicitly.
helper.TWO_ARG_COMMANDS.add("call-mcp")
helper.add_llm_command("call-mcp")
if not hasattr(helper, "set_mcp_commands"):
    helper.set_mcp_commands = lambda _commands: None

from mcp_client_impl import *  # noqa: E402,F403
