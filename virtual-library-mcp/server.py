"""Virtual Library MCP Server - a DUAL-ERA implementation

This server speaks two MCP protocol eras at once (spec: "a dual-era server
MAY serve both eras concurrently on the same endpoint/process"):

- LEGACY era (2025-11-25 and earlier, initialize handshake): FastMCP 3.
  Resources & templates, tools with elicitation / tool-enabled sampling /
  background tasks, prompts, icons, OAuth 2.1 via GoogleProvider (auth.py).
- MODERN era (2026-07-28, stateless — SEP-2575): the modern/ package,
  implemented from scratch for education. Per-request _meta metadata,
  server/discover, MRTR (SEP-2322), subscriptions/listen, CacheableResult
  (SEP-2549), required Mcp-Method/Mcp-Name headers (SEP-2243), the SEP-2640
  skills extension, the io.modelcontextprotocol/tasks extension (SEP-2663),
  and the draft authorization model (RFC 9728 PRM + bearer validation, with
  a built-in educational authorization server).

Spec: https://modelcontextprotocol.io/specification/draft (2026-07-28)

Transports (VIRTUAL_LIBRARY_TRANSPORT):
- stdio          -> legacy protocol via FastMCP (unchanged)
- stdio-modern   -> 2026-07-28 stateless protocol over stdio (modern/stdio.py)
- http           -> ONE endpoint serving BOTH eras: each POST is classified
  by its protocol markers (MCP-Protocol-Version header, initialize method,
  modern _meta keys) and routed to the matching pipeline. Legacy sessions
  keep their GET/DELETE verbs; the modern era has neither (SEP-2567).
"""

import logging
import secrets as secrets_module
import sys
from functools import partial

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


def build_modern_stack():
    """Assemble the 2026-07-28 protocol stack (modern/ package).

    Returns (dispatcher, broker, modern_asgi_or_None). The stack is pure
    wiring — every piece is built from the same declarative tables
    (tools.TOOL_SPECS, resources._RESOURCE_GROUPS, prompts.PROMPT_SPECS)
    the FastMCP app registers, so both protocol eras expose the same
    library. modern_asgi is None on stdio-modern (no HTTP layer needed).
    """
    from pathlib import Path

    from modern.broker import SubscriptionBroker
    from modern.dispatcher import Dispatcher
    from modern.mrtr import RequestStateCodec
    from modern.registry import ListCachePolicy, ModernRegistry
    from modern.skills import SkillsProvider
    from modern.tasks_ext import TasksExtension
    from modern.types import Implementation

    registry = ModernRegistry()

    # Skills extension (SEP-2640): the skills/ directory becomes skill://
    # resources with a digest-bearing index and resources/directory/read.
    skills_provider = SkillsProvider(Path(__file__).parent / "skills")
    registry.add_resource_provider(skills_provider)
    registry.add_extension_capabilities(skills_provider.capability_fragment())

    # Tasks extension (SEP-2663): task handles are the spec-sanctioned
    # explicit cross-call state now that protocol sessions are gone.
    tasks_ext = TasksExtension()
    tasks_ext.register_with(registry)

    # List-change notifications flow ONLY through subscriptions/listen
    # streams in the modern era — the broker is the fan-out point.
    broker = SubscriptionBroker()
    registry.on_list_changed = broker.publish_list_changed

    # MRTR requestState transits the client, so the spec REQUIRES integrity
    # protection (SEP-2322). Unset secret = random per process: fine for one
    # instance, but a retry would fail across a restart or a second replica.
    if config.request_state_secret:
        state_secret = config.request_state_secret.encode()
    else:
        state_secret = secrets_module.token_bytes(32)
        logger.info(
            "MRTR requestState secret: random per-process (set "
            "VIRTUAL_LIBRARY_REQUEST_STATE_SECRET to share across restarts)"
        )

    dispatcher = Dispatcher(
        registry,
        RequestStateCodec(state_secret),
        server_info=Implementation(name=config.server_name, version=config.server_version),
        instructions=(
            "Virtual Library MCP Server (dual-era). Browse the catalog through "
            "resources, perform circulation actions through tools, and use "
            "prompts for AI-assisted recommendations. Agent skills live at "
            "skill://index.json (SEP-2640). Some tools need follow-up input "
            "and will answer with resultType 'input_required' (MRTR)."
        ),
        broker=broker,
        cache_policy=ListCachePolicy(
            ttl_ms=config.modern_cache_ttl_ms,
            # Shared caches must never mix authorization contexts (SEP-2549).
            cache_scope="private" if config.modern_auth_enabled else "public",
        ),
        resource_update_hooks={
            # After these tools mutate a book, subscribers watching that
            # exact URI get notifications/resources/updated on their
            # listen stream.
            "checkout_book": lambda a: f"library://books/{a['book_isbn']}",
            "return_book": lambda a: f"library://books/{a['book_isbn']}",
            "reserve_book": lambda a: f"library://books/{a['book_isbn']}",
        },
        task_runner=tasks_ext.maybe_run_as_task,
        task_tool_names={"regenerate_catalog"},
    )

    if config.transport != "http":
        return dispatcher, broker, None

    from modern.http import create_modern_asgi

    extra_routes = []
    verifier = None
    challenge_401_fn = None
    challenge_403_fn = None
    if config.demo_as_enabled:
        from modern.auth import build_demo_auth, challenge_401, challenge_403, prm_url_for

        base = config.base_url or f"http://{config.http_host}:{config.http_port}"
        routes, verifier, issuer = build_demo_auth(
            base_url=base,
            canonical_resource_url=config.canonical_url,
            auto_approve=config.demo_as_auto_approve,
        )
        extra_routes.extend(routes)
        prm_url = prm_url_for(config.canonical_url)
        challenge_401_fn = partial(challenge_401, prm_url)
        challenge_403_fn = partial(challenge_403, "library:write", prm_url)
        logger.info("Educational authorization server mounted (issuer=%s)", issuer)

    modern_asgi = create_modern_asgi(
        dispatcher,
        allowed_origins=config.allowed_origins,
        require_auth=config.modern_auth_enabled,
        verifier=verifier,
        challenge_401=challenge_401_fn,
        challenge_403=challenge_403_fn,
        tool_schema_lookup=registry.tool_input_schema,
        extra_routes=extra_routes,
        mcp_path=config.http_path,
    )
    return dispatcher, broker, modern_asgi


def _run_http_server() -> None:
    """Run the Streamable HTTP transport with the configured security posture."""
    if not (config.auth_enabled and config.modern_auth_enabled):
        # The HTTP endpoint serves BOTH protocol eras, so "authenticated"
        # means both layers are on: the legacy era's OAuth (GoogleProvider)
        # AND the modern era's bearer validation. Enabling only one would
        # silently leave the other era open — fail closed instead.
        if not config.allow_insecure_http:
            logger.error(
                "Refusing to serve HTTP without authentication on BOTH protocol "
                "eras. Enable legacy OAuth (VIRTUAL_LIBRARY_AUTH_ENABLED=true "
                "with Google credentials) AND modern bearer auth "
                "(VIRTUAL_LIBRARY_MODERN_AUTH_ENABLED=true), or explicitly opt "
                "out for local development "
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

    import uvicorn

    from modern.http import create_dual_era_app

    # One endpoint, two protocol eras. The legacy FastMCP ASGI app keeps its
    # sessions, GET SSE stream, and Google OAuth; the modern pipeline is
    # stateless (SEP-2575). Classification happens per POST.
    _dispatcher, _broker, modern_asgi = build_modern_stack()
    legacy_asgi = mcp.http_app(path=config.http_path)
    app = create_dual_era_app(modern_asgi, legacy_asgi, mcp_path=config.http_path)

    logger.info(
        "Dual-era Streamable HTTP listening on %s:%s%s "
        "(modern=2026-07-28 auth=%s; legacy=2025-11-25 auth=%s)",
        config.http_host,
        config.http_port,
        config.http_path,
        "bearer" if config.modern_auth_enabled else "DISABLED",
        "oauth2.1" if config.auth_enabled else "DISABLED",
    )
    uvicorn.run(app, host=config.http_host, port=config.http_port, log_level="info")


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
        elif config.transport == "stdio-modern":
            # The 2026-07-28 stateless protocol over newline-delimited
            # JSON-RPC. No handshake: the first request can be anything;
            # dual-era clients probe with server/discover (SEP-2575).
            import asyncio

            from modern.stdio import run_stdio_modern

            dispatcher, _broker, _ = build_modern_stack()
            asyncio.run(run_stdio_modern(dispatcher))
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
