"""Tests for Book Resources

This test module validates the MCP resource implementations for books.
It tests both the list resource (with pagination) and detail resource (by ISBN).

MCP TESTING PHILOSOPHY:
- Test the protocol interface, not implementation details
- Validate response structure matches MCP specifications
- Ensure error handling follows JSON-RPC standards
- Test resource behavior under various conditions
"""

import inspect
import re
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastmcp import Context
from fastmcp.exceptions import ResourceError

from database.book_repository import BookSortOptions
from database.repository import PaginatedResponse
from models.book import Book
from resources.books import (
    BookListResponse,
    book_resources,
    get_book_handler,
    list_books_handler,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sample_book():
    """Create a sample book for testing."""
    return Book(
        isbn="978-0-134-68547-9",
        title="The Art of Computer Programming",
        author_id="author_knuth_donald",  # Fixed: pattern requires 6+ chars after underscore
        genre="Computer Science",
        publication_year=1968,
        available_copies=3,
        total_copies=5,
        description="A comprehensive monograph on algorithms",
        cover_url="https://example.com/tacp.jpg",
    )


@pytest.fixture
def sample_book_list(sample_book):
    """Create a list of sample books."""
    books = [sample_book]
    for i in range(1, 5):
        books.append(
            Book(
                isbn=f"978-0-134-68547-{i}",
                title=f"Sample Book {i}",
                author_id=f"author_sample_{i:06d}",  # Fixed: pattern requires 6+ chars
                genre="Fiction",
                publication_year=2020 + i,
                available_copies=i,
                total_copies=i + 2,
                description=f"Description for book {i}",
            )
        )
    return books


@pytest.fixture
def mock_context():
    """Create a mock FastMCP context."""
    return AsyncMock(spec=Context)


# =============================================================================
# LIST RESOURCE TESTS
# =============================================================================


class TestBookListResource:
    """Test the /books/list resource handler."""

    @pytest.mark.asyncio
    async def test_list_books_default_params(self, sample_book_list, mock_context):
        """Test listing books with default parameters."""
        # Create mock repository response
        paginated_response = PaginatedResponse(
            items=sample_book_list[:2],
            total=5,
            page=1,
            page_size=20,
            total_pages=1,
            has_next=False,
            has_previous=False,
        )

        # Mock the repository
        with patch("resources.books.session_scope") as mock_session_scope:
            mock_session = AsyncMock()
            mock_session_scope.return_value.__enter__.return_value = mock_session

            with patch("resources.books.BookRepository") as MockBookRepo:
                # Create a mock instance with the search method
                mock_repo = Mock()
                # Make search return the paginated response (not async)
                mock_repo.search.return_value = paginated_response
                MockBookRepo.return_value = mock_repo
                # Call handler with no params (FastMCP 2.0 pattern)
                result = await list_books_handler()

                # Verify response structure matches MCP expectations
                assert isinstance(result, dict)
                assert "books" in result
                assert "total" in result
                assert "page" in result
                assert "total_pages" in result
                assert "has_next" in result
                assert "has_previous" in result

                # Verify data
                assert len(result["books"]) == 2
                assert result["total"] == 5
                assert result["page"] == 1
                assert result["page_size"] == 20
                assert result["total_pages"] == 1
                assert result["has_next"] is False
                assert result["has_previous"] is False

                # Verify repository was called with default params
                mock_repo.search.assert_called_once()
                call_args = mock_repo.search.call_args
                pagination = call_args.kwargs["pagination"]
                assert pagination.page == 1
                assert pagination.page_size == 20
                assert call_args.kwargs["sort_by"] == BookSortOptions.TITLE
                assert call_args.kwargs["sort_desc"] is False

    @pytest.mark.asyncio
    async def test_list_books_always_uses_defaults(self, sample_book_list, mock_context):
        """Test that list books always uses default parameters (static resource)."""
        # Create response with default pagination
        paginated_response = PaginatedResponse(
            items=sample_book_list[:2],
            total=5,
            page=1,
            page_size=20,  # Default limit
            total_pages=1,
            has_next=False,
            has_previous=False,
        )

        with patch("resources.books.session_scope") as mock_session_scope:
            mock_session = AsyncMock()
            mock_session_scope.return_value.__enter__.return_value = mock_session

            with patch("resources.books.BookRepository") as MockBookRepo:
                # Create a mock instance with the search method
                mock_repo = Mock()
                # Make search return the paginated response (not async)
                mock_repo.search.return_value = paginated_response
                MockBookRepo.return_value = mock_repo

                # Handler doesn't accept parameters anymore (static resource)
                await list_books_handler()

                # Verify it always uses default values
                call_args = mock_repo.search.call_args
                pagination = call_args.kwargs["pagination"]
                assert pagination.page == 1  # Default page
                assert pagination.page_size == 20  # Default limit
                assert call_args.kwargs["sort_by"] == BookSortOptions.TITLE  # Default sort
                assert call_args.kwargs["sort_desc"] is False  # Default order

                # Verify search params are defaults
                search_params = call_args.kwargs["search_params"]
                assert search_params.query is None
                assert search_params.genre is None
                assert search_params.available_only is False

    @pytest.mark.asyncio
    async def test_list_books_error_handling(self, mock_context):
        """Test error handling in list resource."""
        with patch("resources.books.session_scope") as mock_session_scope:
            mock_session = AsyncMock()
            mock_session_scope.return_value.__enter__.return_value = mock_session

            with patch("resources.books.BookRepository") as MockBookRepo:
                mock_repo = Mock()
                mock_repo.search.side_effect = Exception("Database connection failed")
                MockBookRepo.return_value = mock_repo
                # Should raise ResourceError with proper code
                with pytest.raises(ResourceError):
                    await list_books_handler()


# =============================================================================
# DETAIL RESOURCE TESTS
# =============================================================================


class TestBookDetailResource:
    """Test the /books/{isbn} resource handler."""

    @pytest.mark.asyncio
    async def test_get_book_by_isbn(self, sample_book, mock_context):
        """Test retrieving a book by ISBN."""
        isbn = "978-0-134-68547-9"

        with patch("resources.books.session_scope") as mock_session_scope:
            mock_session = AsyncMock()
            mock_session_scope.return_value.__enter__.return_value = mock_session

            with patch("resources.books.BookRepository") as MockBookRepo:
                mock_repo = Mock()
                mock_repo.get_by_isbn.return_value = sample_book
                MockBookRepo.return_value = mock_repo
                result = await get_book_handler(isbn=isbn)

                # Verify response is book data
                assert isinstance(result, dict)
                assert result["isbn"] == isbn.replace("-", "")  # ISBN is normalized
                assert result["title"] == "The Art of Computer Programming"
                assert result["author_id"] == "author_knuth_donald"

                # Verify repository was called correctly
                mock_repo.get_by_isbn.assert_called_once_with(isbn)

    @pytest.mark.asyncio
    async def test_get_book_not_found(self, mock_context):
        """Test 404 behavior for non-existent book."""
        isbn = "978-0-000-00000-0"

        with patch("resources.books.session_scope") as mock_session_scope:
            mock_session = AsyncMock()
            mock_session_scope.return_value.__enter__.return_value = mock_session

            with patch("resources.books.BookRepository") as MockBookRepo:
                mock_repo = Mock()
                mock_repo.get_by_isbn.return_value = None  # Book not found
                MockBookRepo.return_value = mock_repo
                with pytest.raises(ResourceError) as exc_info:
                    await get_book_handler(isbn=isbn)

                # Verify proper error message
                assert f"Book not found: {isbn}" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_book_invalid_isbn(self, mock_context):
        """Test error handling for invalid ISBN values.

        FastMCP 2.0 extracts the ISBN from the URI template, so we test
        handling of invalid ISBN values rather than URI parsing.
        """
        # Test with an invalid ISBN that the repository can't find
        invalid_isbn = "invalid-isbn-format"

        with patch("resources.books.session_scope") as mock_session_scope:
            mock_session = AsyncMock()
            mock_session_scope.return_value.__enter__.return_value = mock_session

            with patch("resources.books.BookRepository") as MockBookRepo:
                mock_repo = Mock()
                # Repository returns None for invalid ISBN
                mock_repo.get_by_isbn.return_value = None
                MockBookRepo.return_value = mock_repo

                with pytest.raises(ResourceError) as exc_info:
                    await get_book_handler(isbn=invalid_isbn)

                # Should return book not found error
                assert f"Book not found: {invalid_isbn}" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_book_database_error(self, mock_context):
        """Test error handling for database failures."""
        isbn = "978-0-134-68547-9"

        with patch("resources.books.session_scope") as mock_session_scope:
            mock_session = AsyncMock()
            mock_session_scope.return_value.__enter__.return_value = mock_session

            with patch("resources.books.BookRepository") as MockBookRepo:
                mock_repo = Mock()
                mock_repo.get_by_isbn.side_effect = Exception("Connection timeout")
                MockBookRepo.return_value = mock_repo
                with pytest.raises(ResourceError) as exc_info:
                    await get_book_handler(isbn=isbn)

                assert "Connection timeout" in str(exc_info.value)


# =============================================================================
# MCP PROTOCOL COMPLIANCE TESTS
# =============================================================================


class TestMCPCompliance:
    """Test that resources follow MCP protocol specifications."""

    def test_resource_metadata_structure(self):
        """Test that resource definitions follow MCP structure."""

        # Verify we have the expected resources
        assert len(book_resources) == 2

        # Check list resource
        list_resource = next(r for r in book_resources if "uri" in r)
        assert list_resource["uri"] == "library://books/list"
        assert "name" in list_resource
        assert "description" in list_resource
        assert list_resource["mime_type"] == "application/json"
        assert callable(list_resource["handler"])

        # Check detail resource with template
        detail_resource = next(r for r in book_resources if "uri_template" in r)
        assert detail_resource["uri_template"] == "library://books/{isbn}"
        assert "name" in detail_resource
        assert "description" in detail_resource
        assert detail_resource["mime_type"] == "application/json"
        assert callable(detail_resource["handler"])

    def test_response_schema_validation(self):
        """Test that response schemas are properly structured."""
        # Create a response and validate it can be serialized
        response = BookListResponse(
            books=[],
            total=0,
            page=1,
            page_size=20,
            total_pages=0,
            has_next=False,
            has_previous=False,
        )

        # Should serialize to dict without errors
        data = response.model_dump()
        assert isinstance(data, dict)
        assert all(
            key in data
            for key in [
                "books",
                "total",
                "page",
                "page_size",
                "total_pages",
                "has_next",
                "has_previous",
            ]
        )


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_resource_registration_with_fastmcp():
    """Test that resources can be registered with FastMCP server."""

    # This test verifies the structure is correct for FastMCP registration
    for resource in book_resources:
        # Each resource must have either uri or uri_template
        assert "uri" in resource or "uri_template" in resource

        # Required fields
        assert "name" in resource
        assert "description" in resource
        assert "mime_type" in resource
        assert "handler" in resource

        # Handler must be async callable
        handler = resource["handler"]
        assert callable(handler)
        assert hasattr(handler, "__name__")

        # Verify handler signature matches FastMCP 2.0 expectations
        sig = inspect.signature(handler)
        params = list(sig.parameters.keys())

        if "uri_template" in resource:
            # Template resources should have parameters matching URI template
            # Extract parameter names from URI template
            template_params = re.findall(r"\{(\w+)\}", resource["uri_template"])
            for param in template_params:
                assert param in params, f"Handler missing parameter '{param}' from URI template"
        else:
            # Static resources should have no parameters
            assert len(params) == 0, "Static resource handlers should have no parameters"
