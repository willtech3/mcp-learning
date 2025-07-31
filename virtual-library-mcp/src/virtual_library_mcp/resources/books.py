"""Book Resources - Library Catalog Access

Exposes book catalog data via read-only resources.
Clients use these to browse books, view details, and check availability.

Resources:
- library://books/list - Paginated book catalog with search/filter
- library://books/{isbn} - Individual book details by ISBN
"""

import logging
from typing import Any

from fastmcp.exceptions import ResourceError
from pydantic import BaseModel, Field

from ..database.book_repository import BookRepository, BookSearchParams, BookSortOptions
from ..database.repository import PaginationParams
from ..database.session import session_scope
from ..models.book import Book

logger = logging.getLogger(__name__)


class BookListParams(BaseModel):
    """Parameters for book list filtering and pagination."""

    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    limit: int = Field(default=20, ge=1, le=100, description="Items per page")
    sort_by: BookSortOptions = Field(default=BookSortOptions.TITLE, description="Sort field")
    sort_order: str = Field(default="asc", pattern="^(asc|desc)$", description="Sort direction")

    # Search filters
    query: str | None = Field(default=None, description="General search term")
    genre: str | None = Field(default=None, description="Filter by genre")
    available_only: bool = Field(default=False, description="Show only available books")


class BookListResponse(BaseModel):
    """Response schema with books and pagination metadata."""

    books: list[Book] = Field(..., description="List of books in this page")
    total: int = Field(..., description="Total number of books matching filters")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Number of items per page")
    total_pages: int = Field(..., description="Total number of pages")
    has_next: bool = Field(..., description="Whether there's a next page")
    has_previous: bool = Field(..., description="Whether there's a previous page")


async def list_books_handler() -> dict[str, Any]:
    """Returns paginated book catalog.

    Client requests library://books/list to browse available books.
    Supports filtering by genre, search query, and availability.
    """
    try:
        # Use default parameters since this is now a static resource
        params = BookListParams()

        logger.debug(
            "MCP Resource Request - books/list: page=%d, limit=%d, sort=%s",
            params.page,
            params.limit,
            params.sort_by,
        )

        with session_scope() as session:
            repo = BookRepository(session)

            search_params = BookSearchParams(
                query=params.query, genre=params.genre, available_only=params.available_only
            )

            result = repo.search(
                search_params=search_params,
                pagination=PaginationParams(page=params.page, page_size=params.limit),
                sort_by=params.sort_by,
                sort_desc=(params.sort_order == "desc"),
            )

            # Convert to response schema
            response = BookListResponse(
                books=result.items,
                total=result.total,
                page=result.page,
                page_size=result.page_size,
                total_pages=result.total_pages,
                has_next=result.has_next,
                has_previous=result.has_previous,
            )

            return response.model_dump()

    except Exception as e:
        logger.exception("Error in books/list resource")
        raise ResourceError(f"Failed to retrieve book list: {e!s}") from e


async def get_book_handler(isbn: str) -> dict[str, Any]:
    """Returns details for a specific book.

    Client requests library://books/{isbn} to get full book information
    including title, author, description, and availability.
    """
    try:
        logger.debug("MCP Resource Request - books/%s", isbn)

        with session_scope() as session:
            repo = BookRepository(session)
            book = repo.get_by_isbn(isbn)

            if book is None:
                raise ResourceError(f"Book not found: {isbn}")

            return book.model_dump()

    except ResourceError:
        raise
    except Exception as e:
        logger.exception("Error in books/{isbn} resource")
        raise ResourceError(f"Failed to retrieve book details: {e!s}") from e


book_resources: list[dict[str, Any]] = [
    {
        "uri": "library://books/list",
        "name": "Book Catalog",
        "description": (
            "Browse the library's book catalog with pagination and filtering. "
            "Supports searching by title, author, genre, and availability."
        ),
        "mime_type": "application/json",
        "handler": list_books_handler,
    },
    {
        "uri_template": "library://books/{isbn}",
        "name": "Book Details",
        "description": "Get detailed information about a specific book by ISBN",
        "mime_type": "application/json",
        "handler": get_book_handler,
    },
]
