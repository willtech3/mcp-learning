"""Virtual Library MCP Server - FastMCP Implementation

Demonstrates a complete MCP server with resources, tools, and prompts.
Clients connect via stdio transport for library management operations.

Features exposed:
- Resources: Book catalog, patron records, library statistics
- Tools: Checkout, return, and reservation operations
- Prompts: Book recommendations, reading plans, review generation
"""

import logging
import signal
import sys
from typing import Any

from fastmcp import FastMCP

from config import get_config
from prompts import all_prompts
from resources import all_resources
from tools import all_tools

# Initialize logging - stderr for logs, stdout for MCP protocol
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)

logger = logging.getLogger(__name__)

# Load configuration
config = get_config()

# Create the FastMCP server instance
mcp = FastMCP(
    name=config.server_name,
    version=config.server_version,
    instructions=(
        "Virtual Library MCP Server - A comprehensive library management system "
        "demonstrating all MCP protocol features. Manages books, authors, patrons, "
        "and circulation with real-time updates. Use resources to browse the catalog, "
        "tools to perform actions, and prompts for AI-assisted recommendations."
    ),
)

# Register all resources with the MCP server

for resource in all_resources:
    uri = resource.get("uri_template", resource.get("uri"))
    if not uri:
        logger.error("Resource missing URI: %s", resource)
        continue

    logger.debug("Registering resource: %s with URI: %s", resource["name"], uri)
    try:
        mcp.resource(
            uri=uri,
            name=resource["name"],
            description=resource["description"],
            mime_type=resource["mime_type"],
        )(resource["handler"])
    except Exception:
        logger.exception("Failed to register resource %s", resource["name"])
        raise

logger.info("Registered %d resources", len(all_resources))

# Register all tools with the MCP server
for tool in all_tools:
    logger.debug("Registering tool: %s", tool["name"])
    try:
        mcp.tool(
            name=tool["name"],
            description=tool["description"],
        )(tool["handler"])
    except Exception:
        logger.exception("Failed to register tool %s", tool["name"])
        raise

logger.info("Registered %d tools", len(all_tools))

# Register all prompts with the MCP server
for prompt in all_prompts:
    logger.debug("Registering prompt: %s", prompt.__name__)
    try:
        mcp.prompt()(prompt)
    except Exception:
        logger.exception("Failed to register prompt %s", prompt.__name__)
        raise

logger.info("Registered %d prompts", len(all_prompts))


async def handle_initialization(params: dict[str, Any]) -> None:
    """Handle MCP client initialization.

    Logs client info and capabilities for debugging.
    Client sends 'initialize', server responds with capabilities.
    """
    client_info = params.get("clientInfo", {})
    client_capabilities = params.get("capabilities", {})
    protocol_version = params.get("protocolVersion", "unknown")

    logger.info(
        "MCP Client connecting: %s v%s (Protocol: %s)",
        client_info.get("name", "Unknown"),
        client_info.get("version", "Unknown"),
        protocol_version,
    )

    if client_capabilities:
        logger.debug("Client capabilities: %s", client_capabilities)


async def handle_shutdown() -> None:
    """Handle graceful server shutdown.

    Logs shutdown and cleans up resources.
    """
    logger.info("MCP Server shutting down gracefully...")
    logger.info("Shutdown complete")


async def handle_error(error: Exception) -> None:
    """Handle server-level errors.

    Logs errors for debugging. MCP uses standard JSON-RPC error codes.
    """
    logger.error("MCP Server error: %s: %s", type(error).__name__, error)


def run_stdio_server() -> None:
    """Run the MCP server using stdio transport.

    Stdin receives JSON-RPC requests, stdout sends responses.
    Ideal for local development and subprocess architectures.
    """
    logger.info("Starting %s v%s on stdio transport", config.server_name, config.server_version)

    if config.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug mode enabled - verbose protocol logging active")
    else:
        logging.getLogger("fastmcp").setLevel(logging.WARNING)

    # Set up signal handlers for graceful shutdown
    def signal_handler(signum: int, _frame: Any) -> None:
        logger.info("Received signal %s, initiating shutdown...", signum)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        logger.info("MCP Server ready and waiting for connections...")
        mcp.run(transport="stdio")
    except Exception:
        logger.exception("Fatal error in MCP server")
        sys.exit(1)


def main() -> None:
    """Main entry point for the MCP server.

    Starts the server via command line or entry point.
    """
    try:
        logger.info("=" * 60)
        logger.info("Virtual Library MCP Server")
        logger.info("Version: %s", config.server_version)
        logger.info("Transport: %s", config.transport)
        logger.info("Debug Mode: %s", config.debug)
        logger.info("=" * 60)

        if config.transport == "stdio":
            run_stdio_server()
        else:
            logger.error("Unsupported transport: %s", config.transport)
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception:
        logger.exception("Failed to start MCP server")
        sys.exit(1)


if __name__ == "__main__":
    main()
