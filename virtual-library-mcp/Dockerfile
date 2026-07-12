# Virtual Library MCP Server — Cloud Run container
#
# Multi-stage build:
#   builder: resolves dependencies with uv and seeds the SQLite database,
#            so the image ships a ready-to-serve catalog (instant cold start,
#            no startup seeding, deterministic demo data)
#   runtime: slim image, non-root user, only the venv + app + seeded data
#
# The database is baked in and therefore PER-INSTANCE and EPHEMERAL: writes
# (checkouts, imports) live until the instance is recycled. That is the
# right trade-off for a demo catalog — swap SQLite for Cloud SQL when state
# must survive. Session affinity keeps an MCP client on one instance.

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer first for build caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code.
COPY . .

# Seed the catalog into the image (module mode keeps /app on sys.path).
RUN .venv/bin/python -m database.seed

# --------------------------------------------------------------------------

FROM python:3.12-slim AS runtime

# Run as an unprivileged user; SQLite needs write access to data/ for its
# journal files (and demo writes), nothing else is writable.
RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app

COPY --from=builder --chown=root:root /app/.venv /app/.venv
COPY --from=builder --chown=root:root /app /app
RUN chown -R app:app /app/data

USER app

# Cloud Run injects PORT; default to 8080 for local docker runs.
# The HTTP transport refuses to start without auth unless explicitly
# overridden, so a misconfigured deployment fails closed.
#
# HOME=/tmp: FastMCP's OAuth proxy persists dynamic client registrations
# under ~/.local/share/fastmcp. The app user's home is read-only by
# design, and on Cloud Run /tmp is a writable in-memory tmpfs. Stored
# registrations are per-instance and ephemeral, which FastMCP handles:
# clients simply re-register on first contact with a fresh instance.
ENV VIRTUAL_LIBRARY_TRANSPORT=http \
    VIRTUAL_LIBRARY_HTTP_HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp

EXPOSE 8080

CMD ["/bin/sh", "-c", "VIRTUAL_LIBRARY_HTTP_PORT=${PORT:-8080} exec /app/.venv/bin/python server.py"]
