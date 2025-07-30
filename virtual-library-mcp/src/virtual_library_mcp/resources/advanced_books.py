"""Advanced Book Resources for Virtual Library MCP Server

This module extends the basic book resources with advanced filtering capabilities
using URI templates. It demonstrates:
- Dynamic URI parameters for filtering
- Multiple filtering dimensions (author, genre)
- Efficient query building based on URI structure

MCP URI TEMPLATE CONCEPTS:
1. **Path Parameters**: /books/by-author/{author_id} captures dynamic values
2. **Resource Hierarchies**: Shows relationships (books belong to authors/genres)
3. **RESTful Design**: Intuitive URIs that describe the data structure
4. **Filtering vs Searching**: Path-based filtering for discrete values
"""

import logging
from typing import Any

from fastmcp import Context
from fastmcp.exceptions import ResourceError
from pydantic import BaseModel, Field

from ..database.book_repository import BookRepository, BookSearchParams
from ..database.repository import PaginationParams
from ..database.session import session_scope

# Import our centralized URI utilities
from .uri_utils import URIParseError, extract_author_id_from_books_uri, extract_genre_from_books_uri

logger = logging.getLogger(__name__)


# Helper functions are now imported from uri_utils module
# This demonstrates the DRY principle - Don't Repeat Yourself


# =============================================================================
# RESOURCE SCHEMAS
# =============================================================================


class FilteredBooksParams(BaseModel):
    """Parameters for filtered book lists.

    WHY: Even filtered resources benefit from pagination and sorting options.
    This provides consistency across all list-based resources.
    """

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


# =============================================================================
# RESOURCE HANDLERS
# =============================================================================


async def get_books_by_author_handler(
    uri: str,
    context: Context,  # noqa: ARG001
    params: FilteredBooksParams | None = None,
) -> dict[str, Any]:
    """Handle requests for books by a specific author.

    MCP FILTERED RESOURCES:
    This demonstrates how URI templates can create intuitive filtering
    patterns. Instead of query parameters (?author=X), we use path
    segments (/by-author/X) for cleaner, more RESTful URIs.

    The author ID is part of the resource identity, making it cacheable
    and bookmarkable.

    Args:
        uri: The resource URI (e.g., "library://books/by-author/Jane%20Austen")
        context: FastMCP context
        params: Pagination and sorting parameters

    Returns:
        Dictionary containing books by the specified author
    """
    try:
        # Extract author from URI
        author_id = extract_author_id_from_books_uri(uri)

        # Default parameters if none provided
        if params is None:
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

    except URIParseError as e:
        # Convert URI parsing errors to ResourceError
        raise ResourceError(str(e)) from e
    except Exception as e:
        logger.exception("Error in books/by-author resource")
        raise ResourceError(f"Failed to retrieve books by author: {e!s}") from e


async def get_books_by_genre_handler(
    uri: str,
    context: Context,  # noqa: ARG001
    params: FilteredBooksParams | None = None,
) -> dict[str, Any]:
    """Handle requests for books in a specific genre.

    MCP GENRE FILTERING:
    Similar to author filtering, but demonstrates how the same pattern
    can be applied to different attributes. This consistency makes
    the API predictable and easy to use.

    Args:
        uri: The resource URI (e.g., "library://books/by-genre/Science%20Fiction")
        context: FastMCP context
        params: Pagination and sorting parameters

    Returns:
        Dictionary containing books in the specified genre
    """
    try:
        # Extract genre from URI
        genre = extract_genre_from_books_uri(uri)

        # Default parameters if none provided
        if params is None:
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

    except URIParseError as e:
        # Convert URI parsing errors to ResourceError
        raise ResourceError(str(e)) from e
    except Exception as e:
        logger.exception("Error in books/by-genre resource")
        raise ResourceError(f"Failed to retrieve books by genre: {e!s}") from e


# =============================================================================
# RESOURCE REGISTRATION
# =============================================================================

# Define advanced book resources for FastMCP registration
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


# =============================================================================
# MCP URI TEMPLATE LEARNINGS
# =============================================================================

"""
KEY INSIGHTS FROM IMPLEMENTING URI TEMPLATE RESOURCES:

1. **URI DESIGN PRINCIPLES**:
   - Use meaningful path segments (/by-author/ not /a/)
   - Be consistent across similar resources
   - URL-encode special characters properly
   - Keep URIs hackable and predictable

2. **PARAMETER EXTRACTION**:
   - Always validate extracted parameters
   - Handle URL encoding/decoding properly
   - Provide clear error messages for malformed URIs
   - Consider case sensitivity

3. **FILTERING PATTERNS**:
   - Path parameters for primary filters (author, genre)
   - Query parameters for secondary filters (availability)
   - Consistent parameter names across resources
   - Clear documentation of encoding requirements

4. **ERROR HANDLING**:
   - Validate URI structure before processing
   - Distinguish between "not found" and "bad request"
   - Include the invalid URI in error messages
   - Handle edge cases (empty strings, special chars)

5. **PERFORMANCE CONSIDERATIONS**:
   - URI templates enable better caching
   - Database indexes on filter fields
   - Limit result sizes by default
   - Consider pre-computing common filters

BEST PRACTICES:
- Test with various author names (spaces, apostrophes, accents)
- Document URL encoding requirements clearly
- Provide examples in descriptions
- Consider internationalization (non-ASCII characters)
- Keep URI templates simple and intuitive
"""
