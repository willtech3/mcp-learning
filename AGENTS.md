# AGENTS.md

Shared guidance for coding agents in this repository. Codex reads this file directly; Claude Code loads it through `CLAUDE.md`. Keep repo-wide agent guidance here, in one place.

## Layout

- `docs/mcp/` — protocol reference notes (01–10).
- `virtual-library-mcp/` — the Virtual Library MCP server: Python 3.12+, uv, SQLite/SQLAlchemy, Pydantic v2. The justfile, tests, CI and deploy config all live here.
- The server is **dual-era**:
  - **Legacy** (2025-11-25 and earlier) runs on FastMCP, at the version pinned in `virtual-library-mcp/pyproject.toml`.
  - **Modern** (wire string `2026-07-28`) is hand-implemented in `virtual-library-mcp/modern/` without FastMCP, deliberately, for teaching. The pinned FastMCP / `mcp` 1.x stack does not speak this era.
- `.mcp.json` (Claude Code) and `.codex/config.toml` (Codex) both register the local stdio server `virtual-library-local`, launched with `just --justfile virtual-library-mcp/justfile dev`.

## Rules

1. **Run everything through `just`**, from `virtual-library-mcp/` (or `just --justfile virtual-library-mcp/justfile <recipe>` from the repo root). `just --list` is the catalog. Recipes call `uv run` or `.venv/bin/python`, so they always use the project venv.
2. **Read the spec before implementing an MCP feature.** Modern path: <https://modelcontextprotocol.io/specification/draft> and [`virtual-library-mcp/docs/mcp/11-protocol-2026-07-28.md`](virtual-library-mcp/docs/mcp/11-protocol-2026-07-28.md). Legacy path: the FastMCP docs for the pinned version.
3. **Feature branch and PR for every change**; main only moves by merged PR. An issue is complete when its PR merges.
4. **Green before committing:** `just lint`, `just format-check`, `just typecheck` and `just test` all pass. CI (`.github/workflows/ci.yml`) runs the same four on every PR.
5. **Stage files by name** (`git add <path>`) and check the diff for secrets, tokens and `.env` values before committing.
6. **Deploys are CI-only.** A push to main that touches `virtual-library-mcp/**` runs `.github/workflows/deploy.yml` to Cloud Run. Local `just` deploy recipes are for one-time bootstrap and read-only inspection; see `virtual-library-mcp/docs/DEPLOYMENT.md`.

## Running locally

From `virtual-library-mcp/` on a fresh checkout:

```bash
just install    # uv sync --dev
just db-seed    # builds data/library.db (gitignored) from the curated catalog
just dev        # stdio server, as MCP clients launch it
```

`just dev-http` serves Streamable HTTP on <http://127.0.0.1:8080/mcp> without auth (loopback only); while it runs, `just inspector-web` opens the MCP Inspector with one connection per era. More in `virtual-library-mcp/docs/DEVELOPMENT.md`.

## Conventions

- **Type annotations where they add value:** Pydantic models, public API methods, functions that can return `None`, complex data structures. Leave obvious locals and simple internal helpers unannotated.
- **Local time throughout:** `datetime.now()` without a timezone, a deliberate simplification for a learning project.
- **Tests exercise behavior through public interfaces**, prefer pytest fixtures to mocks, and cover critical paths rather than every edge case. There is no coverage target.
