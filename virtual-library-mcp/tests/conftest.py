"""Test configuration and fixtures for Virtual Library MCP Server.

This conftest.py file demonstrates MCP testing best practices:
1. Isolated test databases - Each test gets a clean database
2. Configuration overrides - Test-specific MCP server configurations
3. Async support - Testing async MCP operations
4. Resource cleanup - Proper teardown of test resources

MCP-specific testing considerations:
- Protocol message validation
- Transport layer mocking
- Capability negotiation testing
- Resource subscription lifecycle
- Tool execution sandboxing
"""

import asyncio
import os
from collections.abc import AsyncGenerator, Generator
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import ServerConfig, reset_config
from src.database.author_repository import (
    AuthorCreateSchema,
    AuthorRepository,
)
from src.database.book_repository import BookCreateSchema, BookRepository
from src.database.patron_repository import (
    PatronCreateSchema,
    PatronRepository,
)
from src.database.schema import Base

# === Pytest Configuration ===


def pytest_configure(config):
    """Configure pytest with custom markers for MCP testing."""
    config.addinivalue_line("markers", "mcp_protocol: mark test as testing MCP protocol compliance")
    config.addinivalue_line("markers", "mcp_transport: mark test as testing MCP transport layer")
    config.addinivalue_line("markers", "mcp_capabilities: mark test as testing MCP capabilities")


# === Test Database Fixtures ===


@pytest.fixture
def test_db_path(tmp_path: Path) -> Generator[Path, None, None]:
    """Provide a temporary database path for each test.

    MCP servers need persistent storage, but tests should be isolated.
    This fixture ensures each test gets its own database file.
    """
    db_path = tmp_path / "test_library.db"
    yield db_path

    # Cleanup: Remove database file if it exists
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def test_database_url(test_db_path: Path) -> str:
    """Provide a SQLAlchemy database URL for testing."""
    return f"sqlite:///{test_db_path}"


@pytest.fixture
def test_db_session(test_database_url: str) -> Generator[Session, None, None]:
    """Provide a SQLAlchemy session for database tests.

    This fixture demonstrates how MCP servers handle database connections
    in a test environment.
    """
    # Create engine with test-specific settings
    engine = create_engine(
        test_database_url,
        echo=False,  # Set to True for SQL debugging
        connect_args={"check_same_thread": False},  # SQLite specific
    )

    # Create all tables
    Base.metadata.create_all(bind=engine)

    # Create session factory
    session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    # Create session
    session = session_local()

    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


# === Configuration Fixtures ===


@pytest.fixture
def test_config(test_db_path: Path) -> Generator[ServerConfig, None, None]:
    """Provide a test-specific MCP server configuration.

    This fixture demonstrates configuration isolation for MCP testing:
    - Isolated database
    - Test-specific settings
    - Predictable behavior
    """
    # Reset global config to ensure isolation
    reset_config()

    # Create test configuration
    config = ServerConfig(
        # Test-specific server identification
        server_name="test-virtual-library",
        server_version="0.0.1-test",
        # Use test database
        database_path=test_db_path,
        # Test-friendly settings
        debug=True,
        log_level="DEBUG",
        # Disable features that might interfere with tests
        enable_subscriptions=False,  # Unless specifically testing subscriptions
        enable_progress_notifications=False,  # Unless testing progress
        # Reduce limits for faster tests
        max_concurrent_operations=2,
        resource_cache_ttl=0,  # Disable caching in tests
    )

    yield config

    # Cleanup: Reset global config
    reset_config()


@pytest.fixture
def minimal_config(test_db_path: Path) -> Generator[ServerConfig, None, None]:
    """Provide minimal MCP server configuration for basic tests.

    This demonstrates the minimum configuration needed for an MCP server.
    """
    reset_config()

    config = ServerConfig(
        database_path=test_db_path,
        # Everything else uses defaults
    )

    yield config

    reset_config()


@pytest.fixture
def production_like_config(test_db_path: Path) -> Generator[ServerConfig, None, None]:
    """Provide production-like configuration for integration tests.

    This helps test MCP server behavior in production-like conditions.
    """
    reset_config()

    config = ServerConfig(
        server_name="virtual-library-prod",
        server_version="1.0.0",
        database_path=test_db_path,
        # Production settings
        debug=False,
        log_level="WARNING",
        # All MCP capabilities enabled
        enable_sampling=True,
        enable_subscriptions=True,
        enable_progress_notifications=True,
        # Production limits
        max_concurrent_operations=50,
        resource_cache_ttl=300,
    )

    yield config

    reset_config()


# === Environment Fixtures ===


@pytest.fixture
def clean_env() -> Generator[None, None, None]:
    """Provide a clean environment without VIRTUAL_LIBRARY_* variables.

    MCP servers often use environment variables for configuration.
    This fixture ensures tests start with a clean slate.
    """
    # Save current environment
    original_env = os.environ.copy()

    # Remove all VIRTUAL_LIBRARY_* variables
    for key in list(os.environ.keys()):
        if key.startswith("VIRTUAL_LIBRARY_"):
            del os.environ[key]

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def test_env(clean_env) -> dict[str, str]:
    """Provide a test environment with common test settings.

    This demonstrates environment-based configuration for MCP servers.
    """
    test_vars = {
        "VIRTUAL_LIBRARY_DEBUG": "true",
        "VIRTUAL_LIBRARY_LOG_LEVEL": "DEBUG",
        "VIRTUAL_LIBRARY_SERVER_NAME": "test-server",
    }

    os.environ.update(test_vars)
    return test_vars


# === Async Support Fixtures ===


@pytest.fixture(scope="session")
def event_loop():
    """Provide an event loop for async tests.

    MCP servers are often async, especially when handling
    multiple concurrent operations or subscriptions.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def async_test_config(test_db_path: Path) -> AsyncGenerator[ServerConfig, None]:
    """Async version of test_config for async tests."""
    reset_config()

    config = ServerConfig(
        server_name="async-test-library",
        database_path=test_db_path,
        debug=True,
    )

    yield config

    # Async cleanup if needed
    await asyncio.sleep(0)  # Placeholder for async cleanup
    reset_config()


# === MCP Protocol Testing Fixtures ===


@pytest.fixture
def json_rpc_request() -> dict:
    """Provide a sample JSON-RPC request for protocol testing.

    MCP uses JSON-RPC 2.0 for all communication.
    """
    return {
        "jsonrpc": "2.0",
        "id": "test-request-1",
        "method": "tools/list",
        "params": {},
    }


@pytest.fixture
def mcp_initialization_request() -> dict:
    """Provide an MCP initialization request.

    This is the first message in any MCP session.
    """
    return {
        "jsonrpc": "2.0",
        "id": "init-1",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "sampling": {},
                "roots": {
                    "listChanged": True,
                },
            },
            "clientInfo": {
                "name": "test-client",
                "version": "1.0.0",
            },
        },
    }


# === Test Data Fixtures ===


@pytest.fixture
def sample_book_data() -> dict:
    """Provide sample book data for testing.

    This demonstrates the kind of data MCP resources might expose.
    """
    return {
        "id": "test-book-1",
        "isbn": "978-0-123456-78-9",
        "title": "Test Book",
        "author": "Test Author",
        "publisher": "Test Publisher",
        "publication_year": 2024,
        "genre": "Fiction",
        "available": True,
        "total_copies": 3,
        "available_copies": 2,
    }


@pytest.fixture
def sample_patron_data() -> dict:
    """Provide sample patron data for testing."""
    return {
        "id": "test-patron-1",
        "name": "Test Patron",
        "email": "test@example.com",
        "phone": "+1-555-0123",
        "membership_date": "2024-01-01",
        "membership_type": "regular",
        "active": True,
    }


@pytest.fixture
def sample_patron(test_db_session):
    """Create a sample patron in the test database."""
    patron_repo = PatronRepository(test_db_session)
    patron_data = PatronCreateSchema(name="Test Patron", email="test@example.com", phone="555-0123")
    patron = patron_repo.create(patron_data)
    test_db_session.commit()
    return patron


@pytest.fixture
def sample_book(test_db_session):
    """Create a sample book with author in the test database."""
    # Create author first
    author_repo = AuthorRepository(test_db_session)
    author_data = AuthorCreateSchema(
        name="Test Author",
        birth_date=date(1970, 1, 1),
        nationality="American",
        biography="Test author bio",
    )
    author = author_repo.create(author_data)

    # Create book
    book_repo = BookRepository(test_db_session)
    book_data = BookCreateSchema(
        isbn="9781234567890",
        title="Test Book",
        author_id=author.id,
        genre="Fiction",
        publication_year=2023,
        total_copies=3,
    )
    book = book_repo.create(book_data)
    test_db_session.commit()
    return book


@pytest.fixture
def sample_books(test_db_session):
    """Create multiple sample books for testing."""
    author_repo = AuthorRepository(test_db_session)
    book_repo = BookRepository(test_db_session)

    # Create several authors
    authors = []
    for i in range(3):
        author_data = AuthorCreateSchema(
            name=f"Author {i}",
            birth_date=date(1970 + i, 1, 1),
            nationality="American",
            biography=f"Biography {i}",
        )
        author = author_repo.create(author_data)
        authors.append(author)

    # Create books
    books = []
    genres = ["Fiction", "Science Fiction", "Mystery"]
    for i in range(10):
        book_data = BookCreateSchema(
            isbn=f"978123456789{i}",
            title=f"Book {i}",
            author_id=authors[i % 3].id,
            genre=genres[i % 3],
            publication_year=2020 + (i % 4),
            total_copies=3,
        )
        book = book_repo.create(book_data)
        books.append(book)

    test_db_session.commit()
    return books


# === Utility Functions ===


def assert_json_rpc_response(response: dict, request_id: str | None = None) -> None:
    """Assert that a response is a valid JSON-RPC 2.0 response.

    MCP protocol compliance requires proper JSON-RPC formatting.
    """
    assert response.get("jsonrpc") == "2.0"

    if request_id is not None:
        assert response.get("id") == request_id

    # Must have either result or error, not both
    has_result = "result" in response
    has_error = "error" in response

    assert has_result != has_error, "Response must have either result or error, not both"

    if has_error:
        error = response["error"]
        assert isinstance(error, dict)
        assert "code" in error
        assert "message" in error
        assert isinstance(error["code"], int)
        assert isinstance(error["message"], str)


def assert_mcp_error(response: dict, error_code: int) -> None:
    """Assert that a response is an MCP error with specific code.

    MCP defines standard error codes that servers must use.
    """
    assert_json_rpc_response(response)
    assert "error" in response
    assert response["error"]["code"] == error_code


# === Cleanup Fixtures ===


@pytest.fixture(autouse=True)
def cleanup_after_test():
    """Automatic cleanup after each test.

    Ensures tests don't interfere with each other.
    """
    yield

    # Reset global configuration
    reset_config()

    # Clear any test-specific environment variables
    for key in list(os.environ.keys()):
        if key.startswith(("TEST_", "VIRTUAL_LIBRARY_TEST_")):
            del os.environ[key]
