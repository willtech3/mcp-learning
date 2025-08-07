"""Context managers for tracing database operations."""

from contextlib import contextmanager

from . import logfire


@contextmanager
def trace_repository_operation(repository: str, operation: str, table: str | None = None):
    """Context manager for tracing repository operations."""
    with logfire.span(
        f"db.{repository}.{operation}",
        db_repository=repository,
        db_operation=operation,
        db_table=table or repository,
        db_system="sqlite",
    ) as span:
        try:
            yield span
        except Exception as e:
            span.set_attribute("db.error", str(e))
            raise
