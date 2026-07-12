"""Virtual Library MCP Server - FastMCP 3 Implementation

A complete MCP server targeting protocol revision 2025-11-25, demonstrating:

- Resources & templates: catalog browsing (library://...) with icons/tags
- Tools: typed signatures -> rich input schemas, structured output,
  annotations, elicitation, tool-enabled sampling, background tasks
- Prompts: user-invoked templates for recommendations and reading plans
- Notifications: resources/list_changed fired on visibility changes
- Transports: stdio for local development, Streamable HTTP for remote use
- Authorization: OAuth 2.1 with PKCE on the HTTP transport (see auth.py)
- Observability: Logfire middleware tracing every protocol message

Session-state note: sampling, elicitation, and notifications are
server->client requests that ride the session's SSE stream, so the HTTP
transport runs STATEFUL. Scale out with session affinity, not stateless
round-robin (see the deployment docs).
"""

import logging
import sys

from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

import prompts
import resources
import tools
from auth import EmailAllowlistMiddleware, build_auth_provider
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
    auth=build_auth_provider(config),
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

# Authorization (distinct from authentication): restrict to listed accounts.
if config.auth_enabled and config.auth_allowed_emails:
    logger.info("Email allowlist active: %d account(s) authorized", len(config.auth_allowed_emails))
    mcp.add_middleware(EmailAllowlistMiddleware(config.auth_allowed_emails))

# Each package registers its own components (see <package>/__init__.py).
resources.register(mcp)
tools.register(mcp)
prompts.register(mcp)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(_: Request) -> JSONResponse:
    """Liveness probe for Cloud Run / load balancers.

    Custom routes bypass MCP authentication by design — health checks
    must not require tokens. Nothing sensitive is exposed here.
    """
    return JSONResponse({"status": "ok", "service": config.server_name})


def _run_http_server() -> None:
    """Run the Streamable HTTP transport with the configured security posture."""
    if not config.auth_enabled:
        if not config.allow_insecure_http:
            logger.error(
                "Refusing to serve HTTP without authentication. Either enable "
                "OAuth (VIRTUAL_LIBRARY_AUTH_ENABLED=true with Google credentials) "
                "or explicitly opt out for local development "
                "(VIRTUAL_LIBRARY_ALLOW_INSECURE_HTTP=true)."
            )
            sys.exit(1)
        logger.warning(
            "HTTP transport running WITHOUT authentication (allow_insecure_http=true). "
            "This must never be exposed beyond localhost."
        )

    # Basic abuse protection for the remote transport. Token-bucket per
    # client; generous limits suitable for a demo deployment.
    from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware

    mcp.add_middleware(RateLimitingMiddleware(max_requests_per_second=20, burst_capacity=40))

    logger.info(
        "Streamable HTTP listening on %s:%s%s (auth=%s)",
        config.http_host,
        config.http_port,
        config.http_path,
        "oauth2.1" if config.auth_enabled else "DISABLED",
    )
    mcp.run(
        transport="http",
        host=config.http_host,
        port=config.http_port,
        path=config.http_path,
    )


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
        elif config.transport == "http":
            _run_http_server()
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
