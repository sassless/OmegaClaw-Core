"""Local no-credential MCP server used by the Omega 2.0 Compose spike."""

from mcp.server.fastmcp import FastMCP


server = FastMCP(
    "omega2-spike",
    host="0.0.0.0",
    port=8000,
    stateless_http=True,
)


@server.tool()
def echo(message: str) -> str:
    """Return the supplied message."""
    return message


if __name__ == "__main__":
    server.run(transport="streamable-http")
