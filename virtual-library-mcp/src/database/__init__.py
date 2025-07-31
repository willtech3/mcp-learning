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

from .author_repository import AuthorRepository
from .book_repository import BookRepository
from .circulation_repository import CirculationRepository
from .patron_repository import PatronRepository
from .repository import (
    BaseRepository,
    DuplicateError,
    NotFoundError,
    PaginatedResponse,
    PaginationParams,
    RepositoryException,
)
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
    "AuthorRepository",
    "Base",
    "BaseRepository",
    "Book",
    "BookRepository",
    "CheckoutRecord",
    "CirculationRepository",
    "CirculationStatusEnum",
    "DatabaseManager",
    "DuplicateError",
    "NotFoundError",
    "PaginatedResponse",
    "PaginationParams",
    "Patron",
    "PatronRepository",
    "PatronStatusEnum",
    "RepositoryException",
    "ReservationRecord",
    "ReservationStatusEnum",
    "ReturnRecord",
    "get_db_manager",
    "get_session",
    "mcp_safe_commit",
    "mcp_safe_query",
    "session_scope",
]
