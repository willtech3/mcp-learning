"""Custom metrics for Virtual Library MCP Server."""

import logfire

# MCP Protocol Metrics
mcp_request_counter = logfire.metric_counter(
    "mcp.requests.total", description="Total MCP requests by method"
)

mcp_request_duration = logfire.metric_histogram(
    "mcp.request.duration_ms", unit="milliseconds", description="MCP request duration by method"
)

# Library Business Metrics
books_circulation = logfire.metric_counter(
    "library.books.circulation", description="Book circulation events (checkout/return)"
)

patron_activity = logfire.metric_gauge(
    "library.patrons.active", description="Number of patrons with active checkouts"
)

# AI/Sampling Metrics
ai_generation_requests = logfire.metric_counter(
    "ai.generation.requests", description="AI generation requests by type"
)

ai_generation_tokens = logfire.metric_histogram(
    "ai.generation.tokens", unit="tokens", description="Token usage for AI generation"
)

# Bulk Operation Metrics
bulk_import_progress = logfire.metric_gauge(
    "bulk.import.progress", description="Current bulk import progress percentage"
)


def record_circulation_event(event_type: str, book_genre: str):
    """Record a circulation event."""
    books_circulation.add(1, {"event_type": event_type, "genre": book_genre})


def update_import_progress(current: int, total: int, operation_id: str):
    """Update bulk import progress."""
    if total > 0:
        progress = (current / total) * 100
        bulk_import_progress.set(progress, {"operation_id": operation_id})
