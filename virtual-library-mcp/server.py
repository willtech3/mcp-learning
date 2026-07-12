"""Virtual Library MCP Server - FastMCP 3 Implementation

A complete MCP server targeting protocol revision 2025-11-25, demonstrating:

- Resources & templates: catalog browsing (library://...) with icons/tags
- Tools: typed signatures -> rich input schemas, structured output,
  annotations, elicitation, tool-enabled sampling, background tasks
- Prompts: user-invoked templates for recommendations and reading plans
- Notifications: resources/list_changed fired on visibility changes
- Observability: Logfire middleware tracing every protocol message

Transport is selected via config: stdio for local development (default).
Streamable HTTP with OAuth 2.1 arrives with the deployment work.
"""

import logging
import sys

from dotenv import load_dotenv
from fastmcp import FastMCP

import prompts
import resources
import tools
from config import get_config
from observability import LOGFIRE_AVAILABLE, initialize_observability
from observability import get_config as get_obs_config
from observability.middleware import MCPInstrumentationMiddleware

load_dotenv()

# stderr for logs — stdout belongs to the MCP protocol when using stdio.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

config = get_config()
initialize_observability()

mcp = FastMCP(
    name=config.server_name,
    version=config.server_version,
    instructions=(
        "Virtual Library MCP Server - A comprehensive library management system "
        "demonstrating the full MCP feature surface. Browse the catalog through "
        "resources, perform circulation actions through tools, and use prompts "
        "for AI-assisted recommendations. Some tools ask follow-up questions "
        "(elicitation) or generate content via your LLM (sampling)."
    ),
)

# Observability middleware traces every MCP message when Logfire is available.
obs_config = get_obs_config()
if obs_config.enabled and LOGFIRE_AVAILABLE:
    logger.info("Enabling observability middleware for MCP protocol tracing")
    mcp.add_middleware(MCPInstrumentationMiddleware())

# Each package registers its own components (see <package>/__init__.py).
resources.register(mcp)
tools.register(mcp)
prompts.register(mcp)


def main() -> None:
    """Entry point: run the server on the configured transport."""
    logger.info(
        "%s v%s starting (transport=%s, debug=%s)",
        config.server_name,
        config.server_version,
        config.transport,
        config.debug,
    )

    if config.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger("fastmcp").setLevel(logging.WARNING)

    try:
        if config.transport == "stdio":
            mcp.run(transport="stdio")
        else:
            logger.error("Unsupported transport: %s", config.transport)
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception:
        logger.exception("Fatal error in MCP server")
        sys.exit(1)


if __name__ == "__main__":
    main()
