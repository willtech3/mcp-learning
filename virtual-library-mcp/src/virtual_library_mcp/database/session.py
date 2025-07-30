"""
Database session management for the Virtual Library MCP Server.

This module provides connection management and session handling for SQLAlchemy.
In the MCP architecture, proper session management is critical for:

1. Thread Safety: MCP servers may handle concurrent requests
2. Transaction Management: Tools need atomic operations
3. Connection Pooling: Efficient resource utilization
4. Error Recovery: Graceful handling of database issues

Key MCP Considerations:
- Sessions should be short-lived (per-request in MCP handlers)
- Use context managers to ensure proper cleanup
- Handle connection errors gracefully in MCP error responses
"""

import logging
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from ..config import get_config
from .schema import Base

# Configure logging for database operations
logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Manages database connections and sessions for the MCP server.

    This class provides:
    - Singleton pattern for consistent database access
    - Connection pooling for performance
    - Session factory with proper scoping
    - Database initialization and migration support
    """

    def __init__(self, database_url: str | None = None):
        """
        Initialize the database manager.

        Args:
            database_url: SQLAlchemy database URL. If None, uses SQLite default.
        """
        if database_url is None:
            # Use database path from configuration
            config = get_config()
            db_path = config.database_path

            # Make relative paths relative to project root
            if not db_path.is_absolute():
                db_path = Path.cwd() / db_path

            # Ensure parent directory exists
            db_path.parent.mkdir(exist_ok=True, parents=True)

            database_url = f"sqlite:///{db_path}"
            logger.info("Using SQLite database at: %s", db_path)

        self.database_url = database_url
        self._engine: Engine | None = None
        self._session_factory: sessionmaker | None = None

    @property
    def engine(self) -> Engine:
        """
        Get or create the database engine.

        The engine is created with:
        - Connection pooling (StaticPool for SQLite)
        - Foreign key constraints enabled for SQLite
        - Proper isolation level for concurrent access
        """
        if self._engine is None:
            # Configure engine based on database type
            if self.database_url.startswith("sqlite"):
                # SQLite-specific configuration for MCP server use
                self._engine = create_engine(
                    self.database_url,
                    # Use StaticPool to maintain a single connection
                    # This prevents "database is locked" errors in SQLite
                    poolclass=StaticPool,
                    # Enable foreign key constraints
                    connect_args={"check_same_thread": False},
                    # Echo SQL for debugging (disable in production)
                    echo=False,
                )

                # Enable foreign key constraints for SQLite
                @event.listens_for(self._engine, "connect")
                def set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ARG001
                    cursor = dbapi_connection.cursor()
                    cursor.execute("PRAGMA foreign_keys=ON")
                    cursor.close()
            else:
                # PostgreSQL or other databases
                self._engine = create_engine(
                    self.database_url,
                    # Connection pool settings for production use
                    pool_size=10,
                    max_overflow=20,
                    pool_pre_ping=True,  # Verify connections before use
                    echo=False,
                )

            logger.info("Database engine created: %s", self._engine.url)

        return self._engine

    @property
    def session_factory(self) -> sessionmaker:
        """Get or create the session factory."""
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                bind=self.engine,
                # Don't auto-commit (explicit transactions for MCP tools)
                autocommit=False,
                # Don't auto-flush (control when changes are sent to DB)
                autoflush=False,
                # Ensure sessions are bound to our engine
                expire_on_commit=False,  # Keep objects usable after commit
            )
        return self._session_factory

    def create_session(self) -> Session:
        """
        Create a new database session.

        Returns:
            A new SQLAlchemy session

        Note:
            Sessions should be used with context managers or properly closed
            to prevent connection leaks in the MCP server.
        """
        return self.session_factory()

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """
        Provide a transactional scope for database operations.

        This is the recommended way to use sessions in MCP handlers:

        ```python
        with db_manager.session_scope() as session:
            book = session.query(Book).filter_by(isbn=isbn).first()
            # Perform operations
        # Session is automatically committed or rolled back
        ```

        Yields:
            Database session

        Raises:
            Any database errors are logged and re-raised
        """
        session = self.create_session()
        try:
            yield session
            session.commit()
            logger.debug("Database transaction committed successfully")
        except Exception:
            logger.exception("Database error, rolling back")
            session.rollback()
            raise
        finally:
            session.close()

    def init_database(self, drop_existing: bool = False) -> None:
        """
        Initialize the database schema.

        Args:
            drop_existing: If True, drop all tables before creating

        Note:
            In production MCP servers, use proper migration tools like Alembic.
            This method is suitable for development and testing.
        """
        engine = self.engine

        if drop_existing:
            logger.warning("Dropping all existing tables...")
            Base.metadata.drop_all(bind=engine)

        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database initialization complete")

    def verify_connection(self) -> bool:
        """
        Verify the database connection is working.

        Returns:
            True if connection is successful, False otherwise

        This is useful for MCP server health checks.
        """
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database connection verified")
            return True
        except Exception:
            logger.exception("Database connection failed")
            return False

    def close(self) -> None:
        """
        Close the database connection and cleanup resources.

        Should be called when the MCP server shuts down.
        """
        if self._engine:
            self._engine.dispose()
            logger.info("Database engine disposed")
        self._engine = None
        self._session_factory = None


# Global database manager instance
# In MCP servers, we typically use a singleton for database access
_db_manager: DatabaseManager | None = None


def get_db_manager(database_url: str | None = None) -> DatabaseManager:
    """
    Get the global database manager instance.

    Args:
        database_url: Database URL (only used on first call)

    Returns:
        The database manager singleton

    This follows the singleton pattern to ensure consistent database
    access across all MCP handlers and tools.
    """
    global _db_manager  # noqa: PLW0603 - Singleton pattern for database manager

    if _db_manager is None:
        _db_manager = DatabaseManager(database_url)

    return _db_manager


def get_session() -> Session:
    """
    Get a new database session.

    This is a convenience function for quick session access.
    Prefer using session_scope() for proper transaction management.

    Returns:
        A new database session
    """
    return get_db_manager().create_session()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """
    Convenience context manager for database sessions.

    Example:
        ```python
        with session_scope() as session:
            books = session.query(Book).all()
        ```
    """
    with get_db_manager().session_scope() as session:
        yield session


# MCP-specific session utilities


def mcp_safe_commit(session: Session, operation: str) -> None:
    """
    Safely commit a session with MCP-appropriate error handling.

    Args:
        session: The database session
        operation: Description of the operation (for error messages)

    Raises:
        ValueError: If the commit fails (with MCP-friendly message)
    """
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        # Provide MCP-friendly error message
        raise ValueError(f"Database operation '{operation}' failed: {e!s}") from e


def mcp_safe_query[T](session: Session, query_func: Callable[[Session], T], error_msg: str) -> T:
    """
    Execute a query with MCP-appropriate error handling.

    Args:
        session: The database session
        query_func: Function that performs the query
        error_msg: Error message for MCP response

    Returns:
        Query result

    Raises:
        ValueError: If query fails (with MCP-friendly message)
    """
    try:
        return query_func(session)
    except Exception as e:
        # Log the detailed error
        logger.exception("Query failed")
        # Raise MCP-friendly error
        raise ValueError(f"{error_msg}: Database query failed") from e
