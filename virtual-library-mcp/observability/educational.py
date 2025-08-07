"""Educational context and hints for learning MCP."""


def add_educational_context(span, operation: str):
    """Add educational context to spans for learning."""

    # Add context about what this operation demonstrates
    educational_contexts = {
        "checkout_book": "Demonstrates tool execution with database transactions",
        "bulk_import": "Shows long-running operations with progress tracking",
        "book_insights": "Illustrates AI sampling integration",
        "search_catalog": "Examples full-text search patterns",
        "get_recommendations": "Shows resource caching strategies",
    }

    if operation in educational_contexts:
        span.set_attribute("educational.concept", educational_contexts[operation])

    # Add MCP protocol education
    span.set_attribute("mcp.protocol_version", "1.0")
    span.set_attribute("mcp.transport", "stdio")


def add_performance_hint(span, duration_ms: float, operation_type: str):
    """Add performance hints for educational purposes."""

    thresholds = {"resource": 100, "tool": 500, "sampling": 2000, "database": 50}

    threshold = thresholds.get(operation_type, 200)

    if duration_ms > threshold * 2:
        span.set_attribute(
            "performance.hint",
            f"Consider optimizing - {duration_ms}ms exceeds target {threshold}ms",
        )
    elif duration_ms < threshold / 2:
        span.set_attribute(
            "performance.hint",
            f"Excellent performance - {duration_ms}ms well under target {threshold}ms",
        )
