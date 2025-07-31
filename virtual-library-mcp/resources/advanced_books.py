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

from database.book_repository import BookRepository, BookSearchParams
from database.repository import PaginationParams
from database.session import session_scope

logger = logging.getLogger(__name__)


class FilteredBooksParams(BaseModel):
    """Common parameters for filtered book lists."""

    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    limit: int = Field(default=20, ge=1, le=100, description="Items per page")
    sort_by: str = Field(
        default="title",
        pattern="^(title|author|publication_year|rating)$",
        description="Sort field",
    )
    sort_order: str = Field(default="asc", pattern="^(asc|desc)$", description="Sort direction")
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


async def get_books_by_author_handler(author_id: str) -> dict[str, Any]:
    """Returns books written by the specified author.

    Client requests library://books/by-author/{author_name} to browse
    all books by that author with pagination and sorting options.
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

            # Create search parameters for author filter
            search_params = BookSearchParams(
                author_name=author_id,  # Search by author name
                available_only=params.available_only,
            )

            # Map sort fields to repository sort options
            sort_mapping = {
                "title": book_repo.sort_options.TITLE,
                "author": book_repo.sort_options.AUTHOR,
                "publication_year": book_repo.sort_options.PUBLICATION_YEAR,
                "rating": book_repo.sort_options.RATING,
            }
            sort_by = sort_mapping.get(params.sort_by, book_repo.sort_options.TITLE)

            # Fetch filtered results
            result = book_repo.search(
                search_params=search_params,
                pagination=PaginationParams(page=params.page, page_size=params.limit),
                sort_by=sort_by,
                sort_desc=(params.sort_order == "desc"),
            )

            # Convert books to simplified format for response
            books_data = []
            for book in result.items:
                books_data.append(
                    {
                        "isbn": book.isbn,
                        "title": book.title,
                        "author": book.author,
                        "genre": book.genre,
                        "publication_year": book.publication_year,
                        "average_rating": book.average_rating,
                        "total_copies": book.total_copies,
                        "available_copies": book.available_copies,
                        "is_available": book.is_available,
                    }
                )

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

            return response.model_dump()

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

            # Create search parameters for genre filter
            search_params = BookSearchParams(
                genre=genre,  # Exact genre match
                available_only=params.available_only,
            )

            # Map sort fields to repository sort options
            sort_mapping = {
                "title": book_repo.sort_options.TITLE,
                "author": book_repo.sort_options.AUTHOR,
                "publication_year": book_repo.sort_options.PUBLICATION_YEAR,
                "rating": book_repo.sort_options.RATING,
            }
            sort_by = sort_mapping.get(params.sort_by, book_repo.sort_options.TITLE)

            # Fetch filtered results
            result = book_repo.search(
                search_params=search_params,
                pagination=PaginationParams(page=params.page, page_size=params.limit),
                sort_by=sort_by,
                sort_desc=(params.sort_order == "desc"),
            )

            # Convert books to response format
            books_data = []
            for book in result.items:
                books_data.append(
                    {
                        "isbn": book.isbn,
                        "title": book.title,
                        "author": book.author,
                        "genre": book.genre,
                        "publication_year": book.publication_year,
                        "publisher": book.publisher,
                        "description": book.description[:200] + "..."
                        if book.description and len(book.description) > 200
                        else book.description,
                        "average_rating": book.average_rating,
                        "total_copies": book.total_copies,
                        "available_copies": book.available_copies,
                        "is_available": book.is_available,
                    }
                )

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

            return response.model_dump()

    except Exception as e:
        logger.exception("Error in books/by-genre resource")
        raise ResourceError(f"Failed to retrieve books by genre: {e!s}") from e


advanced_book_resources: list[dict[str, Any]] = [
    {
        "uri_template": "library://books/by-author/{author_id}",
        "name": "Books by Author",
        "description": (
            "Browse all books by a specific author. Supports pagination and sorting "
            "by title, publication year, or rating. Use URL-encoded author names "
            "for authors with spaces or special characters."
        ),
        "mime_type": "application/json",
        "handler": get_books_by_author_handler,
    },
    {
        "uri_template": "library://books/by-genre/{genre}",
        "name": "Books by Genre",
        "description": (
            "Browse all books in a specific genre. Perfect for readers looking "
            "for their next book in a favorite category. Supports filtering by "
            "availability and sorting options."
        ),
        "mime_type": "application/json",
        "handler": get_books_by_genre_handler,
    },
]
