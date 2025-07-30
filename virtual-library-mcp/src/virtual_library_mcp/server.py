"""Virtual Library MCP Server - Core Server Implementation

This module demonstrates the heart of an MCP (Model Context Protocol) server.
The MCP protocol enables Large Language Models to interact with external systems
through a standardized interface, similar to how USB standardized hardware connections.

MCP PROTOCOL OVERVIEW:
The Model Context Protocol follows a client-server architecture where:
1. Clients (like Claude) connect to servers via transports (stdio, Streamable HTTP)
2. Servers expose capabilities through resources, tools, and prompts
3. Communication uses JSON-RPC 2.0 for structured message exchange
4. The protocol supports both request-response and notification patterns

KEY CONCEPTS DEMONSTRATED:
- Server Initialization: The three-phase handshake (initialize, response, initialized)
- Capability Negotiation: How servers declare what features they support
- Transport Layer: How MCP messages flow between client and server
- Logging Integration: Protocol-level debugging and monitoring
"""

import logging
import signal
import sys
from typing import Any

from fastmcp import FastMCP

from virtual_library_mcp.config import get_config
from virtual_library_mcp.resources import book_resources

# Initialize logging for protocol debugging
# MCP servers should provide detailed logging for troubleshooting
# as the protocol involves complex async message flows
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr)
    ],  # Use stderr to keep stdout clean for stdio transport
)

logger = logging.getLogger(__name__)

# Load configuration
config = get_config()

# =============================================================================
# MCP SERVER INITIALIZATION
# =============================================================================

# Create the FastMCP server instance
# WHY: FastMCP abstracts the low-level protocol details while maintaining compliance
# HOW: It handles JSON-RPC message parsing, routing, and response formatting
# WHERE: This sits at the top of the MCP stack, above transport and below business logic
# WHAT: The central hub that coordinates all MCP interactions

# The instructions parameter provides context about the server's purpose
# This is sent to clients during initialization to help them understand
# what this server does and how to interact with it
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

# =============================================================================
# CAPABILITY CONFIGURATION
# =============================================================================

# MCP servers declare their capabilities during initialization
# This allows clients to adapt their behavior based on what the server supports
# The protocol is designed for extensibility - servers only implement what they need

# FastMCP automatically handles capability negotiation based on what
# resources, tools, and prompts we register with the server.
# The capabilities are dynamically determined during the initialization handshake.

# When we add resources, tools, or prompts later (in subsequent steps),
# FastMCP will automatically include them in the capabilities response.
# This follows the MCP principle of "capabilities follow implementation".

# =============================================================================
# RESOURCE REGISTRATION
# =============================================================================

# Register all book resources with the MCP server
# WHY: Resources must be registered before the server starts
# HOW: FastMCP uses decorators or direct registration
# WHAT: Each resource gets a URI pattern and handler function

for resource in book_resources:
    if "uri_template" in resource:
        # Resources with URI templates (e.g., /books/{isbn})
        # These support parameterized URIs for accessing specific items
        mcp.resource(
            uri_template=resource["uri_template"],
            name=resource["name"],
            description=resource["description"],
            mime_type=resource["mime_type"],
        )(resource["handler"])
    else:
        # Static URI resources (e.g., /books/list)
        # These have fixed URIs without parameters
        mcp.resource(
            uri=resource["uri"],
            name=resource["name"],
            description=resource["description"],
            mime_type=resource["mime_type"],
        )(resource["handler"])

logger.info("Registered %d book resources", len(book_resources))

# =============================================================================
# LIFECYCLE MANAGEMENT
# =============================================================================


async def handle_initialization(params: dict[str, Any]) -> None:
    """Handle server initialization phase.

    MCP INITIALIZATION SEQUENCE:
    1. Client sends 'initialize' request with its capabilities
    2. Server responds with its capabilities and metadata
    3. Client sends 'initialized' notification
    4. Normal operations begin

    This handler is called during step 1, allowing the server to:
    - Validate client capabilities
    - Configure server behavior based on client features
    - Set up any client-specific state

    Args:
        params: Client capabilities and metadata from initialize request
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

    # Log client capabilities for debugging
    # Understanding what the client supports helps diagnose integration issues
    if client_capabilities:
        logger.debug("Client capabilities: %s", client_capabilities)

    # In a production server, you might:
    # - Validate the protocol version
    # - Check for required client capabilities
    # - Initialize client-specific resources
    # - Set up authentication/authorization


async def handle_shutdown() -> None:
    """Handle graceful server shutdown.

    MCP SHUTDOWN SEQUENCE:
    The protocol doesn't define a specific shutdown handshake,
    but servers should clean up resources gracefully:

    1. Stop accepting new requests
    2. Complete in-flight operations
    3. Close database connections
    4. Clean up temporary resources
    5. Notify clients if possible

    This ensures data integrity and allows for clean restarts.
    """
    logger.info("MCP Server shutting down gracefully...")

    # In a full implementation, you would:
    # - Close database connections
    # - Cancel long-running operations
    # - Flush any buffers
    # - Save state if needed

    # For now, just log the shutdown
    logger.info("Shutdown complete")


# =============================================================================
# ERROR HANDLING
# =============================================================================


async def handle_error(error: Exception) -> None:
    """Handle server-level errors.

    MCP ERROR HANDLING:
    The protocol defines standard JSON-RPC error codes:
    - -32700: Parse error (invalid JSON)
    - -32600: Invalid request (not valid JSON-RPC)
    - -32601: Method not found
    - -32602: Invalid params
    - -32603: Internal error
    - -32000 to -32099: Server-defined errors

    Proper error handling ensures clients can gracefully
    recover from failures and provide meaningful feedback.

    Args:
        error: The exception that occurred
    """
    logger.error("MCP Server error: %s: %s", type(error).__name__, error)

    # In production, you might:
    # - Send error notifications to monitoring systems
    # - Implement retry logic for transient failures
    # - Gracefully degrade functionality
    # - Maintain audit logs for security


# =============================================================================
# TRANSPORT CONFIGURATION
# =============================================================================


def run_stdio_server() -> None:
    """Run the MCP server using stdio transport.

    STDIO TRANSPORT:
    The stdio transport is the simplest MCP transport:
    - Input: JSON-RPC messages via stdin
    - Output: JSON-RPC messages via stdout
    - Errors: Log messages via stderr

    This transport is ideal for:
    - Local development and testing
    - Simple integrations
    - Subprocess-based architectures

    The protocol also supports Streamable HTTP for
    production deployments with better scalability.
    """
    logger.info("Starting %s v%s on stdio transport", config.server_name, config.server_version)

    # Configure logging based on debug mode
    if config.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug mode enabled - verbose protocol logging active")
    else:
        # In production, reduce noise but keep important messages
        logging.getLogger("fastmcp").setLevel(logging.WARNING)

    # Set up signal handlers for graceful shutdown
    # This ensures the server can clean up properly when terminated
    def signal_handler(signum: int, _frame: Any) -> None:
        logger.info("Received signal %s, initiating shutdown...", signum)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Termination signal

    try:
        # Start the FastMCP server
        # This begins the event loop and starts processing messages
        logger.info("MCP Server ready and waiting for connections...")

        # The stdio transport in FastMCP handles:
        # 1. Reading JSON-RPC messages from stdin
        # 2. Parsing and validating message structure
        # 3. Routing to appropriate handlers
        # 4. Formatting and sending responses to stdout

        mcp.run(transport="stdio")

    except Exception:
        logger.exception("Fatal error in MCP server")
        sys.exit(1)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main() -> None:
    """Main entry point for the MCP server.

    This function is called when the server is started via:
    - Command line: `python -m virtual_library_mcp.server`
    - Entry point: `virtual-library-mcp` (defined in pyproject.toml)

    The main function sets up the async event loop and starts
    the server. It's kept simple to ensure reliable startup.
    """
    try:
        # Log startup information
        logger.info("=" * 60)
        logger.info("Virtual Library MCP Server")
        logger.info("Version: %s", config.server_version)
        logger.info("Transport: %s", config.transport)
        logger.info("Debug Mode: %s", config.debug)
        logger.info("=" * 60)

        # Run the server based on configured transport
        if config.transport == "stdio":
            run_stdio_server()
        else:
            # Future: Add Streamable HTTP transport support
            logger.error("Unsupported transport: %s", config.transport)
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception:
        logger.exception("Failed to start MCP server")
        sys.exit(1)


if __name__ == "__main__":
    main()


# =============================================================================
# MCP PROTOCOL LEARNINGS
# =============================================================================

# Key Takeaways from this Implementation:
#
# 1. THREE-PHASE INITIALIZATION:
#    The MCP protocol uses a careful handshake to ensure compatibility:
#    - Client announces what it can do
#    - Server responds with what it offers
#    - Client confirms it's ready
#    This prevents version mismatches and capability conflicts.
#
# 2. CAPABILITY-DRIVEN DESIGN:
#    Not all servers need all features. The capability system lets
#    servers implement only what makes sense for their domain while
#    maintaining protocol compliance.
#
# 3. TRANSPORT ABSTRACTION:
#    MCP separates the protocol from transport concerns. The same
#    server can work over stdio, HTTP/SSE, or other transports
#    without changing the core logic.
#
# 4. JSON-RPC FOUNDATION:
#    Using JSON-RPC 2.0 provides:
#    - Standardized request/response format
#    - Built-in error handling
#    - Support for notifications (no response expected)
#    - Batch operations (future enhancement)
#
# 5. ASYNC-FIRST ARCHITECTURE:
#    MCP servers are inherently async to handle:
#    - Concurrent client requests
#    - Long-running operations
#    - Real-time subscriptions
#    - Progress notifications
#
# Next Steps:
# - Implement resources (Step 12): Add /books/list, /books/{isbn} ✓
# - Implement tools (Step 14): Add search_catalog, checkout_book
# - Add subscriptions (Step 16): Real-time updates
# - Implement prompts (Step 18): AI-assisted recommendations
