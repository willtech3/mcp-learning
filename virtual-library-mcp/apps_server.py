"""App-only FastMCP entry point for local preview and ChatGPT Developer Mode.

The full teaching server also registers these UI tools, but it exposes mutation
and administration tools that should not sit behind an unauthenticated tunnel.
This deliberately narrow server publishes only the read-only MCP Apps demos.
"""

from fastmcp import FastMCP

from tools.apps import register

mcp = FastMCP(
    name="Virtual Library MCP Apps",
    version="0.1.0",
    instructions=(
        "Use browse_catalog_app to visually explore books and "
        "library_dashboard_app to show circulation and popularity. "
        "Both tools are read-only demonstrations backed by simulated library data."
    ),
)
register(mcp)


def main() -> None:
    """Run the app-only server on a local Streamable HTTP endpoint."""
    mcp.run(
        transport="http",
        host="127.0.0.1",
        port=8001,
        path="/mcp",
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
