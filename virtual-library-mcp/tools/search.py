"""Search Tool - Library Catalog Search

Provides full-text and filtered search across the book catalog.
Clients use this tool to find books with pagination and sorting.

Usage: tool.call("search_catalog", {"query": "python", "page_size": 20})
"""

import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator

from database.book_repository import BookRepository, BookSearchParams, BookSortOptions
from database.repository import PaginationParams
from database.session import get_session
from models.book import Book
# Observability is handled by middleware, not decorators

logger = logging.getLogger(__name__)


class SearchCatalogInput(BaseModel):
    """Input schema for the search_catalog tool."""

    query: str | None = Field(
        default=None,
        description="General search term to match against title, author, description, or ISBN",
        min_length=1,
        max_length=200,
        examples=["gatsby", "python programming", "978-0134685479"],
    )

    genre: str | None = Field(
        default=None,
        description="Filter by book genre (exact match, case-insensitive)",
        examples=["Fiction", "Non-Fiction", "Science Fiction", "Biography"],
    )

    author: str | None = Field(
        default=None,
        description="Filter by author name (partial match, case-insensitive)",
        min_length=1,
        max_length=100,
        examples=["Fitzgerald", "King", "Rowling"],
    )

    available_only: bool = Field(
        default=False,
        description="Only return books with available copies",
    )

    page: int = Field(
        default=1,
        description="Page number (1-indexed)",
        ge=1,
        le=1000,
    )

    page_size: int = Field(
        default=10,
        description="Number of results per page",
        ge=1,
        le=50,  # Limit to prevent resource exhaustion
    )

    # Sorting parameters
    sort_by: str = Field(
        default="relevance",
        description="Field to sort results by",
        pattern="^(relevance|title|author|publication_year|availability)$",
    )

    sort_desc: bool = Field(
        default=False,
        description="Sort in descending order",
    )

    @field_validator("query", "author")
    @classmethod
    def strip_whitespace(cls, v: str | None) -> str | None:
        """Strip leading/trailing whitespace from string inputs."""
        if v is not None:
            v = v.strip()
            if not v:  # Empty after stripping
                return None
        return v

    @field_validator("genre")
    @classmethod
    def normalize_genre(cls, v: str | None) -> str | None:
        """Normalize genre to title case for consistent matching."""
        if v is not None:
            v = v.strip().title()
            if not v:
                return None
        return v

    def to_search_params(self) -> BookSearchParams:
        """Convert tool input to repository search parameters."""
        return BookSearchParams(
            query=self.query,
            genre=self.genre,
            author_name=self.author,
            available_only=self.available_only,
        )

    def to_pagination_params(self) -> PaginationParams:
        """Convert tool input to pagination parameters."""
        return PaginationParams(page=self.page, page_size=self.page_size)


def format_book_for_tool_response(book: Book) -> dict[str, Any]:
    """Format a book model for tool response."""
    return {
        "isbn": book.isbn,
        "title": book.title,
        "author_id": book.author_id,
        "genre": book.genre,
        "publication_year": book.publication_year,
        "available_copies": book.available_copies,
        "total_copies": book.total_copies,
        "description": book.description,
        "cover_url": book.cover_url,
        "is_available": book.is_available,
    }


async def search_catalog_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    """Process catalog search request.

    Validates input, searches books by query/genre/author,
    returns paginated results with availability status.

    Client calls: tool.call("search_catalog", {"query": "...", "page": 1})
    """
    try:
        # Validate input
        try:
            params = SearchCatalogInput.model_validate(arguments)
        except Exception as e:
            logger.warning("Invalid search parameters: %s", e)
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Invalid search parameters: {e}"}],
            }

        # Require at least one search criterion
        if not any([params.query, params.genre, params.author]):
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": "Please provide at least one search criterion (query, genre, or author)",
                    }
                ],
            }

        # Execute search
        with get_session() as session:
            try:
                repo = BookRepository(session)

                # Map sort parameter to enum
                sort_by = BookSortOptions.TITLE
                if params.sort_by == "title":
                    sort_by = BookSortOptions.TITLE
                elif params.sort_by == "author":
                    sort_by = BookSortOptions.AUTHOR
                elif params.sort_by == "publication_year":
                    sort_by = BookSortOptions.PUBLICATION_YEAR
                elif params.sort_by == "availability":
                    sort_by = BookSortOptions.AVAILABILITY
                # "relevance" uses default (title) until we implement scoring

                # Execute search
                result = repo.search(
                    search_params=params.to_search_params(),
                    pagination=params.to_pagination_params(),
                    sort_by=sort_by,
                    sort_desc=params.sort_desc,
                )

            except Exception as e:
                logger.exception("Search execution failed")
                return {
                    "isError": True,
                    "content": [{"type": "text", "text": f"Search failed: {e!s}"}],
                }

        # Format response
        books_data = [format_book_for_tool_response(book) for book in result.items]

        # Build response message
        if not books_data:
            message = "No books found matching your search criteria."
        else:
            message = f"Found {result.total} book(s) matching your search"
            if result.total > len(books_data):
                message += f" (showing page {result.page} of {result.total_pages})"

        return {
            "content": [{"type": "text", "text": message}],
            "data": {
                "books": books_data,
                "pagination": {
                    "page": result.page,
                    "page_size": result.page_size,
                    "total": result.total,
                    "total_pages": result.total_pages,
                    "has_next": result.has_next,
                    "has_previous": result.has_previous,
                },
            },
        }

    except Exception as e:
        logger.exception("Unexpected error in search_catalog tool")
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"An unexpected error occurred: {e!s}"}],
        }


search_catalog = {
    "name": "search_catalog",
    "description": (
        "Search the library catalog for books. Supports full-text search, "
        "filtering by genre and author, pagination, and sorting. "
        "At least one search criterion must be provided."
    ),
    "inputSchema": SearchCatalogInput.model_json_schema(),
    "handler": search_catalog_handler,
}
