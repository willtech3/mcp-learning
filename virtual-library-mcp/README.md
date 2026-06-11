# Virtual Library MCP Server

A complete MCP (Model Context Protocol) server simulating a library
management system — built as a learning tool and a reference for the
**full protocol surface, revision 2025-11-25**, on FastMCP 3.

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

## Transports & security

- **stdio** (default): local development, Claude Desktop integration.
- **Streamable HTTP**: stateful sessions (sampling/elicitation/notifications
  ride a per-session SSE stream). OAuth 2.1 with PKCE via Google identity,
  plus an email allowlist for authorization. The server **fails closed**:
  HTTP without auth requires an explicit local-dev opt-out.

Deployment to Google Cloud Run (Terraform, Secret Manager, least-privilege
service account, session affinity) is covered in
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

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
