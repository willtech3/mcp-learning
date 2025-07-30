"""Book Resources for Virtual Library MCP Server

This module implements MCP resources for browsing the library's book catalog.
Resources provide read-only access to data through well-defined URIs, following
the MCP protocol's resource specification.

MCP RESOURCE ANATOMY:
Each resource consists of:
1. **URI**: Unique identifier (e.g., "library://books/list")
2. **Name**: Human-readable name for display
3. **Description**: Explains what the resource provides
4. **MIME Type**: Content type (usually "application/json" for structured data)
5. **Handler**: Async function that returns the resource content

PROTOCOL FLOW:
1. Client requests resources/list to discover available resources
2. Server returns metadata about each resource
3. Client requests resources/read with specific URI
4. Server returns the actual content

This implementation demonstrates:
- Paginated list resources with cursor support
- Detail resources with URI parameters
- Error handling for missing resources
- Integration with the repository layer
"""

import logging
from typing import Any

from fastmcp import Context
from fastmcp.exceptions import ResourceError
from pydantic import BaseModel, Field

from ..database.book_repository import BookRepository, BookSearchParams, BookSortOptions
from ..database.repository import PaginationParams
from ..database.session import session_scope
from ..models.book import Book
from .uri_utils import URIParseError, extract_isbn_from_uri

logger = logging.getLogger(__name__)

# =============================================================================
# RESOURCE SCHEMAS
# =============================================================================
# MCP uses JSON-RPC, so all data must be JSON-serializable.
# Pydantic models ensure type safety and automatic JSON conversion.


class BookListParams(BaseModel):
    """Parameters for the book list resource.

    WHY: MCP resources can accept parameters to filter or paginate results.
    This follows the protocol's design for flexible, queryable resources.

    HOW: Parameters are passed in the resource URI or request body.
    The protocol handles parameter parsing and validation.
    """

    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    limit: int = Field(default=20, ge=1, le=100, description="Items per page")
    sort_by: BookSortOptions = Field(default=BookSortOptions.TITLE, description="Sort field")
    sort_order: str = Field(default="asc", pattern="^(asc|desc)$", description="Sort direction")

    # Search filters
    query: str | None = Field(default=None, description="General search term")
    genre: str | None = Field(default=None, description="Filter by genre")
    available_only: bool = Field(default=False, description="Show only available books")


class BookListResponse(BaseModel):
    """Response schema for book list resource.

    WHAT: This schema defines the structure of data returned by the list resource.
    It includes both the data (books) and metadata (pagination info).

    WHERE: This sits between the repository layer and the MCP protocol layer,
    ensuring consistent response format.
    """

    books: list[Book] = Field(..., description="List of books in this page")
    total: int = Field(..., description="Total number of books matching filters")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Number of items per page")
    total_pages: int = Field(..., description="Total number of pages")
    has_next: bool = Field(..., description="Whether there's a next page")
    has_previous: bool = Field(..., description="Whether there's a previous page")


# =============================================================================
# RESOURCE HANDLERS
# =============================================================================
# Each handler function implements the logic for a specific resource.
# FastMCP calls these handlers when clients request the resource.


async def list_books_handler(
    uri: str,  # noqa: ARG001
    context: Context,  # noqa: ARG001
    params: BookListParams | None = None,
) -> dict[str, Any]:
    """Handle requests for the book list resource.

    MCP PROTOCOL DETAILS:
    - This handler is called when a client requests "library://books/list"
    - The protocol automatically handles JSON serialization of the response
    - Errors are converted to proper JSON-RPC error responses

    Args:
        uri: The resource URI (always "library://books/list" for this handler)
        context: FastMCP context containing server state and helpers
        params: Optional parameters for filtering and pagination

    Returns:
        Dictionary containing the book list and pagination metadata

    Raises:
        ResourceError: If there's a problem accessing the data
    """
    try:
        # Default parameters if none provided
        if params is None:
            params = BookListParams()

        logger.debug(
            "MCP Resource Request - books/list: page=%d, limit=%d, sort=%s",
            params.page,
            params.limit,
            params.sort_by,
        )

        # Get database session
        # WHY: Each request gets its own session for isolation
        # HOW: The session is properly closed after the request
        with session_scope() as session:
            repo = BookRepository(session)

            # Build search parameters from request
            search_params = BookSearchParams(
                query=params.query, genre=params.genre, available_only=params.available_only
            )

            # Fetch paginated results
            # WHAT: The repository handles the complex SQL queries
            # WHERE: This abstracts database concerns from protocol concerns
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

            # Return as dict for JSON serialization
            # The protocol handles converting this to proper JSON-RPC format
            return response.model_dump()

    except Exception as e:
        logger.exception("Error in books/list resource")
        # MCP defines standard error codes:
        # -32002: Resource not found
        # -32603: Internal error
        raise ResourceError(f"Failed to retrieve book list: {e!s}") from e


async def get_book_handler(uri: str, context: Context) -> dict[str, Any]:  # noqa: ARG001
    """Handle requests for individual book details.

    MCP URI TEMPLATES:
    Resources can have parameterized URIs using templates.
    For example: "library://books/{isbn}" where {isbn} is replaced
    with the actual ISBN when requesting the resource.

    Args:
        uri: The full resource URI (e.g., "library://books/978-0-134-68547-9")
        context: FastMCP context

    Returns:
        Dictionary containing the book details

    Raises:
        ResourceError: If the book is not found or other errors occur
    """
    try:
        # Extract ISBN from URI using robust validation
        # WHY: MCP uses URI templates for parameterized resources
        # HOW: Enhanced parsing validates scheme, path structure, and provides better error messages
        isbn = extract_isbn_from_uri(uri)
        logger.debug("MCP Resource Request - books/%s", isbn)

        with session_scope() as session:
            repo = BookRepository(session)

            # Fetch the book by ISBN
            # WHAT: The repository returns a Pydantic model or raises NotFoundError
            book = repo.get_by_isbn(isbn)

            if book is None:
                # Return standard MCP error for resource not found
                raise ResourceError(f"Book not found: {isbn}")

            # Return book data as dict
            # The protocol adds metadata like URI and content type
            return book.model_dump()

    except URIParseError as e:
        # Convert URI parsing errors to ResourceError
        raise ResourceError(str(e)) from e
    except ResourceError:
        raise  # Re-raise MCP errors as-is
    except Exception as e:
        logger.exception("Error in books/{isbn} resource")
        raise ResourceError(f"Failed to retrieve book details: {e!s}") from e


# =============================================================================
# RESOURCE REGISTRATION
# =============================================================================
# Resources must be registered with the MCP server to be discoverable.
# This section defines the metadata and binds handlers to URIs.

# Define the book resources that will be registered with FastMCP
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
        # URI template for individual books
        # The {isbn} placeholder is replaced with actual ISBN values
        "uri_template": "library://books/{isbn}",
        "name": "Book Details",
        "description": "Get detailed information about a specific book by ISBN",
        "mime_type": "application/json",
        "handler": get_book_handler,
    },
]


# =============================================================================
# MCP RESOURCE LEARNINGS
# =============================================================================

"""
KEY INSIGHTS FROM IMPLEMENTING MCP RESOURCES:

1. **URI DESIGN MATTERS**:
   - Use hierarchical URIs that reflect your domain model
   - "library://books/list" is more intuitive than "library://list-books"
   - URI templates ("library://books/{isbn}") enable RESTful patterns

2. **PAGINATION IS ESSENTIAL**:
   - MCP recommends cursor-based pagination for large datasets
   - We use page-based here for simplicity, but cursor is more robust
   - Always include metadata (total, has_next) for client navigation

3. **ERROR HANDLING STANDARDS**:
   - Use standard JSON-RPC error codes when possible
   - -32002 for "not found" is universally understood
   - Include helpful error data for debugging

4. **RESPONSE STRUCTURE**:
   - Wrap lists in objects with metadata
   - Use consistent field names across resources
   - Include enough context for clients to understand the data

5. **HANDLER PATTERNS**:
   - Keep handlers thin - delegate to repositories
   - Use Pydantic for automatic validation and serialization
   - Log all requests for debugging protocol issues

6. **SEPARATION OF CONCERNS**:
   - Resources are read-only by design
   - Use Tools for any operation that modifies state
   - This separation makes the API more predictable

NEXT STEPS:
- Add more resources: authors, patrons, circulation status
- Implement resource subscriptions for real-time updates
- Add resource templates for more complex queries
- Consider cursor-based pagination for better performance
"""
