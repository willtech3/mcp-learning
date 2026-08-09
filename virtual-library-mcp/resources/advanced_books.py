"""Advanced Book Resources - URI Template Filtering

Exposes filtered book views using URI templates for intuitive access.
Clients filter books by author or genre using parameterized URIs.

Resources:
- library://books/by-author/{author_id} - Books by specific author
- library://books/by-genre/{genre} - Books in specific genre
"""

import logging
from typing import Any

from fastmcp.exceptions import ResourceError
from pydantic import BaseModel, Field

from database.author_repository import AuthorRepository
from database.book_repository import BookRepository, BookSortOptions
from database.repository import PaginationParams
from database.session import session_scope
from models.book import Book

logger = logging.getLogger(__name__)


class FilteredBooksParams(BaseModel):
    """Common parameters for filtered book lists."""

    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    limit: int = Field(default=20, ge=1, le=100, description="Items per page")
    available_only: bool = Field(default=False, description="Show only available books")


class FilteredBooksResponse(BaseModel):
    """Response schema for filtered book lists."""

    filter_type: str = Field(..., description="Type of filter applied (author/genre)")
    filter_value: str = Field(..., description="The filter value")
    books: list[dict[str, Any]] = Field(..., description="List of books matching filter")
    total: int = Field(..., description="Total books matching filter")
    page: int = Field(..., description="Current page")
    page_size: int = Field(..., description="Items per page")
    total_pages: int = Field(..., description="Total number of pages")
    has_next: bool = Field(..., description="Whether there's a next page")
    has_previous: bool = Field(..., description="Whether there's a previous page")


def _book_data(book: Book, author_name: str) -> dict[str, Any]:
    """Return only catalog fields that exist in the current data model."""
    description = book.description
    if description and len(description) > 200:
        description = f"{description[:200].rstrip()}..."

    return {
        "isbn": book.isbn,
        "title": book.title,
        "author_id": book.author_id,
        "author": author_name,
        "genre": book.genre,
        "publication_year": book.publication_year,
        "description": description,
        "total_copies": book.total_copies,
        "available_copies": book.available_copies,
        "is_available": book.is_available,
    }


async def get_books_by_author_handler(author_id: str) -> dict[str, Any]:
    """Returns books written by the specified author.

    Client requests library://books/by-author/{author_id} to browse
    the first page of books by that author.
    """
    try:
        # Use default parameters for pagination
        params = FilteredBooksParams()

        logger.debug(
            "MCP Resource Request - books/by-author/%s: page=%d, limit=%d",
            author_id,
            params.page,
            params.limit,
        )

        with session_scope() as session:
            book_repo = BookRepository(session)
            author_repo = AuthorRepository(session)
            author = author_repo.get_by_id(author_id)

            # Fetch filtered results
            result = book_repo.get_by_author(
                author_id=author_id,
                pagination=PaginationParams(page=params.page, page_size=params.limit),
                available_only=params.available_only,
            )

            # Convert books to simplified format for response
            author_name = author.name if author else "Unknown author"
            books_data = [_book_data(book, author_name) for book in result.items]

            # Build response
            response = FilteredBooksResponse(
                filter_type="author",
                filter_value=author_id,
                books=books_data,
                total=result.total,
                page=result.page,
                page_size=result.page_size,
                total_pages=result.total_pages,
                has_next=result.has_next,
                has_previous=result.has_previous,
            )

            return response.model_dump(mode="json")

    except Exception as e:
        logger.exception("Error in books/by-author resource")
        raise ResourceError(f"Failed to retrieve books by author: {e!s}") from e


async def get_books_by_genre_handler(genre: str) -> dict[str, Any]:
    """Returns books in the specified genre.

    Client requests library://books/by-genre/{genre} to browse
    all books in that genre category with pagination support.
    """
    try:
        # Use default parameters for pagination
        params = FilteredBooksParams()

        logger.debug(
            "MCP Resource Request - books/by-genre/%s: page=%d, limit=%d",
            genre,
            params.page,
            params.limit,
        )

        with session_scope() as session:
            book_repo = BookRepository(session)
            author_repo = AuthorRepository(session)

            # Fetch filtered results
            result = book_repo.get_by_genre(
                genre=genre,
                pagination=PaginationParams(page=params.page, page_size=params.limit),
                sort_by=BookSortOptions.TITLE,
            )

            # Convert books to response format
            author_names: dict[str, str] = {}
            for book in result.items:
                if book.author_id not in author_names:
                    author = author_repo.get_by_id(book.author_id)
                    author_names[book.author_id] = author.name if author else "Unknown author"
            books_data = [_book_data(book, author_names[book.author_id]) for book in result.items]

            # Build response
            response = FilteredBooksResponse(
                filter_type="genre",
                filter_value=genre,
                books=books_data,
                total=result.total,
                page=result.page,
                page_size=result.page_size,
                total_pages=result.total_pages,
                has_next=result.has_next,
                has_previous=result.has_previous,
            )

            return response.model_dump(mode="json")

    except Exception as e:
        logger.exception("Error in books/by-genre resource")
        raise ResourceError(f"Failed to retrieve books by genre: {e!s}") from e


advanced_book_resources: list[dict[str, Any]] = [
    {
        "uri_template": "library://books/by-author/{author_id}",
        "name": "Books by Author",
        "description": (
            "Browse books by a stable author identifier. Returns current copy "
            "availability and readable author metadata for the first catalog page."
        ),
        "mime_type": "application/json",
        "handler": get_books_by_author_handler,
    },
    {
        "uri_template": "library://books/by-genre/{genre}",
        "name": "Books by Genre",
        "description": (
            "Browse all books in a specific genre. Perfect for readers looking "
            "for their next book in a favorite category. Returns the first catalog "
            "page sorted by title with current copy availability."
        ),
        "mime_type": "application/json",
        "handler": get_books_by_genre_handler,
    },
]
