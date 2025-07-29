"""
Database package for the Virtual Library MCP Server.

This package provides:
- SQLAlchemy schema definitions (schema.py)
- Session management and connection handling (session.py)
- Database initialization utilities

In the MCP architecture, the database layer is critical for:
1. Persisting state between server restarts
2. Supporting concurrent access from multiple MCP clients
3. Enabling subscriptions through change tracking
4. Maintaining data integrity for tools (operations with side effects)
"""

from .schema import (
    Author,
    Base,
    Book,
    CheckoutRecord,
    CirculationStatusEnum,
    Patron,
    PatronStatusEnum,
    ReservationRecord,
    ReservationStatusEnum,
    ReturnRecord,
)
from .session import (
    DatabaseManager,
    get_db_manager,
    get_session,
    mcp_safe_commit,
    mcp_safe_query,
    session_scope,
)

__all__ = [
    "Author",
    "Base",
    "Book",
    "CheckoutRecord",
    "CirculationStatusEnum",
    "DatabaseManager",
    "Patron",
    "PatronStatusEnum",
    "ReservationRecord",
    "ReservationStatusEnum",
    "ReturnRecord",
    "get_db_manager",
    "get_session",
    "mcp_safe_commit",
    "mcp_safe_query",
    "session_scope",
]
