"""
Tests for the search_catalog tool.

These tests verify:
1. Input validation and error handling
2. Search functionality across different parameters
3. Pagination behavior
4. Sorting options
5. MCP protocol compliance
"""

from contextlib import contextmanager

import pytest
from pydantic import ValidationError
from virtual_library_mcp.database.author_repository import AuthorCreateSchema, AuthorRepository
from virtual_library_mcp.database.book_repository import BookCreateSchema, BookRepository
from virtual_library_mcp.tools.search import SearchCatalogInput, search_catalog_handler

# =============================================================================
# INPUT VALIDATION TESTS
# =============================================================================


class TestSearchCatalogInput:
    """Test input validation for the search tool."""

    def test_valid_minimal_input(self):
        """Test minimal valid input with just a query."""
        params = SearchCatalogInput(query="gatsby")
        assert params.query == "gatsby"
        assert params.genre is None
        assert params.author is None
        assert params.available_only is False
        assert params.page == 1
        assert params.page_size == 10
        assert params.sort_by == "relevance"
        assert params.sort_desc is False

    def test_valid_full_input(self):
        """Test all parameters with valid values."""
        params = SearchCatalogInput(
            query="python",
            genre="Technology",
            author="Smith",
            available_only=True,
            page=2,
            page_size=20,
            sort_by="publication_year",
            sort_desc=True,
        )
        assert params.query == "python"
        assert params.genre == "Technology"  # Should be title-cased
        assert params.author == "Smith"
        assert params.available_only is True
        assert params.page == 2
        assert params.page_size == 20
        assert params.sort_by == "publication_year"
        assert params.sort_desc is True

    def test_whitespace_stripping(self):
        """Test that whitespace is properly stripped from string inputs."""
        params = SearchCatalogInput(
            query="  gatsby  ", author="  Fitzgerald  ", genre="  fiction  "
        )
        assert params.query == "gatsby"
        assert params.author == "Fitzgerald"
        assert params.genre == "Fiction"  # Also title-cased

    def test_empty_strings_become_none(self):
        """Test that empty strings after stripping become None."""
        params = SearchCatalogInput(
            query="   ",  # Just whitespace
            author="   ",  # Need whitespace to avoid min_length validation
            genre="  ",
        )
        assert params.query is None
        assert params.author is None
        assert params.genre is None

    def test_genre_normalization(self):
        """Test genre is normalized to title case."""
        params = SearchCatalogInput(genre="science FICTION")
        assert params.genre == "Science Fiction"

    def test_invalid_page_number(self):
        """Test validation rejects invalid page numbers."""
        with pytest.raises(ValidationError) as exc_info:
            SearchCatalogInput(query="test", page=0)
        assert "greater than or equal to 1" in str(exc_info.value)

        with pytest.raises(ValidationError) as exc_info:
            SearchCatalogInput(query="test", page=1001)
        assert "less than or equal to 1000" in str(exc_info.value)

    def test_invalid_page_size(self):
        """Test validation rejects invalid page sizes."""
        with pytest.raises(ValidationError) as exc_info:
            SearchCatalogInput(query="test", page_size=0)
        assert "greater than or equal to 1" in str(exc_info.value)

        with pytest.raises(ValidationError) as exc_info:
            SearchCatalogInput(query="test", page_size=51)
        assert "less than or equal to 50" in str(exc_info.value)

    def test_invalid_sort_by(self):
        """Test validation rejects invalid sort options."""
        with pytest.raises(ValidationError) as exc_info:
            SearchCatalogInput(query="test", sort_by="invalid")
        assert "String should match pattern" in str(exc_info.value)

    def test_query_length_limits(self):
        """Test query length validation."""
        # Max length should be accepted
        params = SearchCatalogInput(query="a" * 200)
        assert len(params.query) == 200

        # Too long should fail
        with pytest.raises(ValidationError) as exc_info:
            SearchCatalogInput(query="a" * 201)
        assert "String should have at most 200 characters" in str(exc_info.value)

    def test_author_length_limits(self):
        """Test author length validation."""
        # Max length should be accepted
        params = SearchCatalogInput(author="a" * 100)
        assert len(params.author) == 100

        # Too long should fail
        with pytest.raises(ValidationError) as exc_info:
            SearchCatalogInput(author="a" * 101)
        assert "String should have at most 100 characters" in str(exc_info.value)


# =============================================================================
# TOOL HANDLER TESTS
# =============================================================================


@pytest.mark.asyncio
class TestSearchCatalogHandler:
    """Test the search_catalog tool handler."""

    async def test_handler_with_invalid_arguments(self):
        """Test handler returns error for invalid arguments."""
        # Missing all search criteria
        result = await search_catalog_handler({})
        assert result["isError"] is True
        assert "at least one search criterion" in result["content"][0]["text"]

        # Invalid page number
        result = await search_catalog_handler({"query": "test", "page": -1})
        assert result["isError"] is True
        assert "Invalid search parameters" in result["content"][0]["text"]

        # Invalid sort_by
        result = await search_catalog_handler({"query": "test", "sort_by": "invalid_field"})
        assert result["isError"] is True
        assert "Invalid search parameters" in result["content"][0]["text"]

    async def test_handler_with_valid_query(self, test_session, mock_get_session):
        """Test handler with a valid search query."""
        # Setup test data
        author_repo = AuthorRepository(test_session)
        book_repo = BookRepository(test_session)

        # Create test author
        author = author_repo.create(
            AuthorCreateSchema(name="F. Scott Fitzgerald", biography="American novelist")
        )

        # Create test books
        book_repo.create(
            BookCreateSchema(
                isbn="9780333791035",
                title="The Great Gatsby",
                author_id=author.id,
                genre="Fiction",
                publication_year=1925,
                available_copies=2,
                total_copies=3,
                description="A classic American novel",
            )
        )

        # Search for the book
        result = await search_catalog_handler({"query": "gatsby"})

        assert result.get("isError") is not True
        assert "Found 1 book(s)" in result["content"][0]["text"]
        assert result["data"]["books"][0]["title"] == "The Great Gatsby"
        assert result["data"]["pagination"]["total"] == 1

    async def test_handler_with_genre_filter(self, test_session, mock_get_session):
        """Test handler with genre filtering."""
        # Setup test data
        author_repo = AuthorRepository(test_session)
        book_repo = BookRepository(test_session)

        author = author_repo.create(AuthorCreateSchema(name="Test Author", biography="Test bio"))

        # Create books in different genres
        book_repo.create(
            BookCreateSchema(
                isbn="1111111111111",
                title="Fiction Book",
                author_id=author.id,
                genre="Fiction",
                publication_year=2020,
                total_copies=1,
            )
        )

        book_repo.create(
            BookCreateSchema(
                isbn="2222222222222",
                title="SciFi Book",
                author_id=author.id,
                genre="Science Fiction",
                publication_year=2021,
                total_copies=1,
            )
        )

        # Search by genre
        result = await search_catalog_handler(
            {
                "genre": "fiction"  # Should be normalized to "Fiction"
            }
        )

        assert result.get("isError") is not True
        books = result["data"]["books"]
        assert len(books) == 1
        assert books[0]["genre"] == "Fiction"

    async def test_handler_with_author_filter(self, test_session, mock_get_session):
        """Test handler with author name filtering."""
        # Setup test data
        author_repo = AuthorRepository(test_session)
        book_repo = BookRepository(test_session)

        fitzgerald = author_repo.create(
            AuthorCreateSchema(name="F. Scott Fitzgerald", biography="American novelist")
        )

        hemingway = author_repo.create(
            AuthorCreateSchema(name="Ernest Hemingway", biography="American novelist")
        )

        # Create books by different authors
        book_repo.create(
            BookCreateSchema(
                isbn="1111111111111",
                title="The Great Gatsby",
                author_id=fitzgerald.id,
                genre="Fiction",
                publication_year=1925,
                total_copies=1,
            )
        )

        book_repo.create(
            BookCreateSchema(
                isbn="2222222222222",
                title="The Sun Also Rises",
                author_id=hemingway.id,
                genre="Fiction",
                publication_year=1926,
                total_copies=1,
            )
        )

        # Search by author name
        result = await search_catalog_handler({"author": "fitzgerald"})

        assert result.get("isError") is not True
        books = result["data"]["books"]
        assert len(books) == 1
        assert books[0]["title"] == "The Great Gatsby"

    async def test_handler_with_availability_filter(self, test_session, mock_get_session):
        """Test handler with availability filtering."""
        # Setup test data
        author_repo = AuthorRepository(test_session)
        book_repo = BookRepository(test_session)

        author = author_repo.create(AuthorCreateSchema(name="Test Author", biography="Test bio"))

        # Create books with different availability
        book_repo.create(
            BookCreateSchema(
                isbn="1111111111111",
                title="Available Book",
                author_id=author.id,
                genre="Fiction",
                publication_year=2020,
                available_copies=2,
                total_copies=2,
            )
        )

        book_repo.create(
            BookCreateSchema(
                isbn="2222222222222",
                title="Unavailable Book",
                author_id=author.id,
                genre="Fiction",
                publication_year=2021,
                available_copies=0,
                total_copies=1,
            )
        )

        # Search with availability filter
        result = await search_catalog_handler({"genre": "Fiction", "available_only": True})

        assert result.get("isError") is not True
        books = result["data"]["books"]
        assert len(books) == 1
        assert books[0]["title"] == "Available Book"
        assert books[0]["is_available"] is True

    async def test_handler_pagination(self, test_session, mock_get_session):
        """Test handler pagination behavior."""
        # Setup test data
        author_repo = AuthorRepository(test_session)
        book_repo = BookRepository(test_session)

        author = author_repo.create(AuthorCreateSchema(name="Test Author", biography="Test bio"))

        # Create multiple books
        for i in range(15):
            book_repo.create(
                BookCreateSchema(
                    isbn=f"{i:013d}",
                    title=f"Book {i:02d}",
                    author_id=author.id,
                    genre="Fiction",
                    publication_year=2020,  # Use a fixed valid year
                    total_copies=1,
                )
            )

        # Get first page
        result = await search_catalog_handler({"genre": "Fiction", "page": 1, "page_size": 10})

        assert result.get("isError") is not True
        assert len(result["data"]["books"]) == 10
        assert result["data"]["pagination"]["page"] == 1
        assert result["data"]["pagination"]["total"] == 15
        assert result["data"]["pagination"]["total_pages"] == 2
        assert result["data"]["pagination"]["has_next"] is True
        assert result["data"]["pagination"]["has_previous"] is False

        # Get second page
        result = await search_catalog_handler({"genre": "Fiction", "page": 2, "page_size": 10})

        assert result.get("isError") is not True
        assert len(result["data"]["books"]) == 5
        assert result["data"]["pagination"]["page"] == 2
        assert result["data"]["pagination"]["has_next"] is False
        assert result["data"]["pagination"]["has_previous"] is True

    async def test_handler_sorting(self, test_session, mock_get_session):
        """Test handler sorting options."""
        # Setup test data
        author_repo = AuthorRepository(test_session)
        book_repo = BookRepository(test_session)

        author = author_repo.create(AuthorCreateSchema(name="Test Author", biography="Test bio"))

        # Create books with different attributes
        books_data = [
            ("1111111111111", "Zebra Book", 2020, 1),
            ("2222222222222", "Alpha Book", 2022, 3),
            ("3333333333333", "Beta Book", 2021, 0),
        ]

        for isbn, title, year, available in books_data:
            book_repo.create(
                BookCreateSchema(
                    isbn=isbn,
                    title=title,
                    author_id=author.id,
                    genre="Fiction",
                    publication_year=year,
                    available_copies=available,
                    total_copies=3,
                )
            )

        # Sort by title ascending (default)
        result = await search_catalog_handler(
            {"genre": "Fiction", "sort_by": "title", "sort_desc": False}
        )

        assert result.get("isError") is not True
        books = result["data"]["books"]
        assert books[0]["title"] == "Alpha Book"
        assert books[1]["title"] == "Beta Book"
        assert books[2]["title"] == "Zebra Book"

        # Sort by publication year descending
        result = await search_catalog_handler(
            {"genre": "Fiction", "sort_by": "publication_year", "sort_desc": True}
        )

        books = result["data"]["books"]
        assert books[0]["publication_year"] == 2022
        assert books[1]["publication_year"] == 2021
        assert books[2]["publication_year"] == 2020

        # Sort by availability
        result = await search_catalog_handler(
            {"genre": "Fiction", "sort_by": "availability", "sort_desc": True}
        )

        books = result["data"]["books"]
        assert books[0]["available_copies"] == 3
        assert books[1]["available_copies"] == 1
        assert books[2]["available_copies"] == 0

    async def test_handler_no_results(self, test_session, mock_get_session):
        """Test handler when no books match the search."""
        result = await search_catalog_handler({"query": "nonexistent_book_xyz"})

        assert result.get("isError") is not True
        assert "No books found" in result["content"][0]["text"]
        assert result["data"]["books"] == []
        assert result["data"]["pagination"]["total"] == 0

    async def test_handler_error_handling(self, test_session, monkeypatch):
        """Test handler error handling for database errors."""

        # Mock the search method to raise an exception
        def mock_search(*args, **kwargs):
            raise RuntimeError("Database connection error")

        monkeypatch.setattr(BookRepository, "search", mock_search)

        result = await search_catalog_handler({"query": "test"})

        assert result["isError"] is True
        assert "Search failed" in result["content"][0]["text"]
        assert "Database connection error" in result["content"][0]["text"]

    async def test_handler_combined_filters(self, test_session, mock_get_session):
        """Test handler with multiple filters combined."""
        # Setup test data
        author_repo = AuthorRepository(test_session)
        book_repo = BookRepository(test_session)

        fitzgerald = author_repo.create(
            AuthorCreateSchema(name="F. Scott Fitzgerald", biography="American novelist")
        )

        # Create multiple books
        book_repo.create(
            BookCreateSchema(
                isbn="1111111111111",
                title="The Great Gatsby",
                author_id=fitzgerald.id,
                genre="Fiction",
                publication_year=1925,
                available_copies=2,
                total_copies=2,
                description="A story about the American Dream",
            )
        )

        book_repo.create(
            BookCreateSchema(
                isbn="2222222222222",
                title="Tender Is the Night",
                author_id=fitzgerald.id,
                genre="Fiction",
                publication_year=1934,
                available_copies=0,
                total_copies=1,
                description="A novel about a psychiatrist",
            )
        )

        # Search with multiple filters
        result = await search_catalog_handler(
            {
                "query": "american",  # Should match Gatsby's description
                "author": "fitzgerald",
                "genre": "Fiction",
                "available_only": True,
            }
        )

        assert result.get("isError") is not True
        books = result["data"]["books"]
        assert len(books) == 1
        assert books[0]["title"] == "The Great Gatsby"
        assert books[0]["is_available"] is True


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def test_session(test_db_session):
    """Provide a test database session."""
    # Import at module level is preferred, but we need it here for test isolation
    from virtual_library_mcp.database.schema import Base  # noqa: PLC0415

    # Create tables
    engine = test_db_session.bind
    Base.metadata.create_all(bind=engine)

    return test_db_session


@pytest.fixture
def mock_get_session(test_session, monkeypatch):
    """Mock get_session to return the test session.

    This ensures that the search handler uses the same database session
    as the test, allowing it to see the test data we create.
    """

    @contextmanager
    def _mock_get_session():
        """Return the test session instead of creating a new one."""
        yield test_session

    # Patch the get_session function in the search module
    monkeypatch.setattr("virtual_library_mcp.tools.search.get_session", _mock_get_session)

    return test_session
