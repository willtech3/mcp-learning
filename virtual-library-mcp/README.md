# Virtual Library MCP Server

A complete MCP (Model Context Protocol) server simulating a library
management system — built as a learning tool and a reference for the
**full protocol surface, revision 2025-11-25**, on FastMCP 3.

## 🆕 Protocol 2026-07-28 (dual-era)

This server now speaks **two MCP protocol eras on one endpoint**: the legacy
`initialize`-handshake protocol (2025-11-25, via FastMCP) *and* the new
**stateless [2026-07-28](https://modelcontextprotocol.io/specification/draft)
revision**, implemented from scratch in [`modern/`](modern/) for teaching —
`server/discover`, per-request `_meta`, MRTR, `subscriptions/listen`,
CacheableResult, the SEP-2640 skills extension, the tasks extension, and the
draft authorization model (with a built-in demo authorization server).

- **What changed and where it lives:** [docs/mcp/11-protocol-2026-07-28.md](docs/mcp/11-protocol-2026-07-28.md)
- **Spec:** <https://modelcontextprotocol.io/specification/draft> ·
  [changelog](https://modelcontextprotocol.io/specification/draft/changelog) ·
  [transports](https://modelcontextprotocol.io/specification/draft/basic/transports/streamable-http) ·
  [MRTR](https://modelcontextprotocol.io/specification/draft/basic/patterns/mrtr) ·
  [authorization](https://modelcontextprotocol.io/specification/draft/basic/authorization)

```bash
# Dual-era Streamable HTTP (serves both protocol eras on :8080/mcp)
VIRTUAL_LIBRARY_TRANSPORT=http VIRTUAL_LIBRARY_ALLOW_INSECURE_HTTP=true uv run python server.py
```

Pairs with [mcp-client-learning](https://github.com/willtech3/mcp-client-learning),
a from-scratch client that exercises everything below (including the
OAuth 2.1 flow against the deployed server).

## What it demonstrates

| MCP feature | Where to see it |
|---|---|
| Resources + RFC 6570 templates | `library://books/list`, `library://books/{isbn}`, stats and recommendations |
| Tools with real input/output schemas | all 8 tools — typed signatures, structured content |
| Tool annotations + icons (SEP-973) | read-only/idempotent hints, data-URI SVG icons |
| **Elicitation** (approval + enum select) | `checkout_book` (fines confirmation), `renew_membership` (term choice) |
| **Sampling** (server-initiated LLM calls) | `generate_book_insights` |
| **Tool-enabled sampling** (SEP-1577) | `similar_books` insight — the client's LLM searches our catalog |
| **Background tasks** (SEP-1686) | `regenerate_catalog` (`task=optional`) |
| Progress notifications | `bulk_import_books`, `regenerate_catalog` |
| `resources/list_changed` notifications | maintenance mode hides/restores the recommendations resource |
| Prompts | `book_recommendation_prompt`, `reading_plan_prompt`, `review_generator_prompt` |
| **OAuth 2.1 + PKCE** (authorization spec) | Streamable HTTP transport, Google identity, email allowlist |
| Logging + observability | server log notifications; Logfire middleware tracing |

The catalog is real: 201 authors, 393 actual books with accurate
metadata, and 24 months of simulated circulation where every statistic
derives from the underlying records (see `database/seed_data/`).

## Quick start

```bash
just install     # dependencies (uv)
just db-seed     # build the catalog (201 authors, 393 books, full history)
just dev         # stdio transport - for Claude Desktop / local clients
just dev-http    # Streamable HTTP on http://127.0.0.1:8080/mcp (no auth, local only)
```

Then, from the sibling client repo:

```bash
mcp-client demo --server http://127.0.0.1:8080/mcp --anonymous
```

…or see [docs/DEMO.md](docs/DEMO.md) for the guided live-demo script.

## MCP Apps demo

The FastMCP protocol path includes two read-only MCP App tools:

- `browse_catalog_app` renders a searchable, sortable catalog with inventory
  metrics and selectable book details.
- `library_dashboard_app` renders circulation metrics, genre activity, and a
  popular-books table.

Preview both tools in FastMCP's local AppBridge host:

```bash
just dev-apps
```

For ChatGPT Developer Mode, run the app-only server so a temporary tunnel does
not expose the full server's circulation or administration tools:

```bash
just dev-apps-http
# In another terminal:
ngrok http 8001
```

In ChatGPT, enable **Settings → Security and login → Developer mode**, then open
**Plugins** and use the plus button to create a developer-mode app. Set its MCP
server URL to the tunnel's HTTPS URL followed by `/mcp`, for example
`https://example.ngrok.app/mcp`. Refresh the app in ChatGPT after changing tool
metadata. The app-only endpoint is stateless and contains only the two read-only
UI tools; it still serves simulated data and is intended for short-lived
development tunnels rather than permanent hosting.

## Transports & security

- **stdio** (default): local development, Claude Desktop integration.
- **Streamable HTTP**: stateful sessions (sampling/elicitation/notifications
  ride a per-session SSE stream). OAuth 2.1 with PKCE via Google identity,
  plus an email allowlist for authorization. The server **fails closed**:
  HTTP without auth requires an explicit local-dev opt-out.

Deployment to Google Cloud Run happens exclusively through GitHub Actions
(keyless Workload Identity Federation, Terraform with remote state,
Secret Manager, least-privilege service accounts, session affinity) —
covered in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Architecture

```text
virtual-library-mcp/
├── server.py               # FastMCP 3 server, transport selection, health route
├── auth.py                 # OAuth 2.1 provider + email-allowlist middleware
├── config.py               # pydantic-settings; fail-closed auth validation
├── icons.py                # SEP-973 icons (inline SVG data URIs)
├── models/                 # Pydantic domain models
├── database/               # SQLAlchemy schema, repositories, seed simulator
│   └── seed_data/          # curated real-book catalog (JSON)
├── resources/              # MCP resources (register(mcp) per package)
├── tools/                  # MCP tools - typed functions
├── prompts/                # MCP prompts
├── observability/          # Logfire middleware + metrics
├── terraform/              # Cloud Run deployment (see docs/DEPLOYMENT.md)
└── tests/                  # protocol-path tests via the in-memory client
```

## Development

```bash
just test         # pytest (in-memory MCP client tests)
just lint         # ruff
just typecheck    # pyright
just check        # all gates
just samples      # regenerate bulk-import sample files
```

Tests run against the real server through FastMCP's in-memory client, so
they exercise actual protocol behavior: schema validation, elicitation
round-trips, sampling handlers, progress, and notifications.

## Spec version note

This server targets MCP revision **2025-11-25** (current). The 2026-07-28
release candidate deprecates sampling/roots/logging and removes the
initialize handshake; this repo intentionally stays on the current
revision — those features are core learning material here.
