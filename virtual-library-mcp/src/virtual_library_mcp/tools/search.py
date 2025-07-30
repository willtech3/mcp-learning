"""
Search tool implementation for the Virtual Library MCP Server.

This tool demonstrates comprehensive MCP tool implementation with:
1. JSON Schema input validation
2. Full-text and field-specific search
3. Pagination support
4. Proper error handling
5. Structured response formatting

MCP TOOL STRUCTURE:
Each tool consists of:
- Metadata: name, description, input schema
- Handler: async function that processes requests
- Validation: Automatic via JSON Schema
- Error handling: Both protocol and execution errors
"""

import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ..database.book_repository import BookRepository, BookSearchParams, BookSortOptions
from ..database.repository import PaginationParams
from ..database.session import get_session
from ..models.book import Book

logger = logging.getLogger(__name__)


# =============================================================================
# INPUT VALIDATION SCHEMA
# =============================================================================

class SearchCatalogInput(BaseModel):
    """
    Input schema for the search_catalog tool.

    MCP INPUT VALIDATION:
    The Model Context Protocol uses JSON Schema for input validation.
    This Pydantic model generates the JSON Schema automatically and
    provides runtime validation when the tool is invoked.

    The schema serves multiple purposes:
    1. Tells clients what parameters are available
    2. Validates inputs before processing
    3. Provides clear error messages for invalid inputs
    4. Documents the tool's interface
    """

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

    # Pagination parameters
    # MCP BEST PRACTICE: Always support pagination for list operations
    page: int = Field(
        default=1,
        description="Page number (1-indexed)",
        ge=1,
        le=1000,  # Prevent excessive pagination
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


# =============================================================================
# TOOL RESPONSE FORMATTING
# =============================================================================

def format_book_for_tool_response(book: Book) -> dict[str, Any]:
    """
    Format a book model for tool response.

    MCP RESPONSE FORMAT:
    Tool responses should be structured and consistent.
    This function ensures all book data is properly
    formatted for JSON serialization in the MCP response.
    """
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


# =============================================================================
# TOOL HANDLER IMPLEMENTATION
# =============================================================================

async def search_catalog_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Handler for the search_catalog tool.

    MCP TOOL EXECUTION:
    This handler demonstrates the complete lifecycle of a tool execution:
    1. Input validation via Pydantic schema
    2. Repository interaction with proper session management
    3. Error handling at multiple levels
    4. Structured response formatting

    The handler is async to support the MCP server's event loop
    and allow for concurrent tool executions.

    Args:
        arguments: Raw arguments from the MCP tools/call request

    Returns:
        Structured response with search results or error information

    Raises:
        No exceptions - all errors are caught and returned as error responses
    """
    try:
        # STEP 1: Validate input arguments
        # WHY: The MCP protocol requires input validation before processing
        # HOW: Pydantic automatically validates against the schema
        # WHAT: This catches type errors, missing required fields, invalid ranges
        try:
            params = SearchCatalogInput.model_validate(arguments)
        except Exception as e:
            # MCP ERROR HANDLING: Invalid parameters
            # Return error with details about what validation failed
            logger.warning("Invalid search parameters: %s", e)
            return {
                "isError": True,
                "content": [{
                    "type": "text",
                    "text": f"Invalid search parameters: {e}"
                }]
            }

        # STEP 2: Check if at least one search criterion is provided
        # WHY: Empty searches could return the entire catalog, causing performance issues
        if not any([params.query, params.genre, params.author]):
            return {
                "isError": True,
                "content": [{
                    "type": "text",
                    "text": "Please provide at least one search criterion (query, genre, or author)"
                }]
            }

        # STEP 3: Execute search with database session
        # WHY: Each tool execution needs its own database session for isolation
        # HOW: Context manager ensures proper cleanup even on error
        with get_session() as session:
            try:
                repo = BookRepository(session)

                # Convert sort_by string to enum
                # Handle special case of "relevance" which maps to title for now
                sort_by = BookSortOptions.TITLE  # Default
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
                # MCP ERROR HANDLING: Database or search error
                # This catches repository exceptions, database errors, etc.
                logger.exception("Search execution failed")
                return {
                    "isError": True,
                    "content": [{
                        "type": "text",
                        "text": f"Search failed: {e!s}"
                    }]
                }

        # STEP 4: Format successful response
        # MCP RESPONSE FORMAT: Tools return content arrays with typed items
        books_data = [format_book_for_tool_response(book) for book in result.items]

        # Build response message
        if not books_data:
            message = "No books found matching your search criteria."
        else:
            message = f"Found {result.total} book(s) matching your search"
            if result.total > len(books_data):
                message += f" (showing page {result.page} of {result.total_pages})"

        # Return structured response
        # WHY: MCP tools must return consistent response format
        # WHAT: content array with text and optional structured data
        return {
            "content": [{
                "type": "text",
                "text": message
            }],
            # Include structured data for client processing
            "data": {
                "books": books_data,
                "pagination": {
                    "page": result.page,
                    "page_size": result.page_size,
                    "total": result.total,
                    "total_pages": result.total_pages,
                    "has_next": result.has_next,
                    "has_previous": result.has_previous,
                }
            }
        }

    except Exception as e:
        # MCP ERROR HANDLING: Catch-all for unexpected errors
        # This ensures the tool never crashes the server
        logger.exception("Unexpected error in search_catalog tool")
        return {
            "isError": True,
            "content": [{
                "type": "text",
                "text": f"An unexpected error occurred: {e!s}"
            }]
        }


# =============================================================================
# TOOL REGISTRATION
# =============================================================================

# Tool metadata for MCP server registration
# WHY: The server needs this metadata to expose the tool to clients
# HOW: FastMCP uses this to handle tools/list requests and routing
# WHAT: Complete tool definition with schema and handler

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


# =============================================================================
# MCP PROTOCOL LEARNINGS
# =============================================================================

# Key Takeaways from Tool Implementation:
#
# 1. INPUT VALIDATION IS CRITICAL:
#    MCP tools must validate all inputs before processing. Using Pydantic
#    provides automatic JSON Schema generation and runtime validation,
#    ensuring protocol compliance and preventing errors.
#
# 2. ERROR HANDLING LAYERS:
#    Tools need multiple levels of error handling:
#    - Validation errors (invalid input)
#    - Business logic errors (no search criteria)
#    - Execution errors (database failures)
#    - Unexpected errors (catch-all)
#
# 3. STRUCTURED RESPONSES:
#    Tools return content arrays with typed items. The isError flag
#    indicates execution failures (not protocol errors). Additional
#    structured data can be included for client processing.
#
# 4. PAGINATION BEST PRACTICES:
#    List operations should always support pagination to handle large
#    result sets efficiently. Page size limits prevent resource exhaustion.
#
# 5. ASYNC EXECUTION:
#    Tool handlers are async to work with the MCP server's event loop.
#    This allows concurrent tool executions and non-blocking I/O.
#
# Next Steps:
# - Implement more tools (checkout, return, reserve)
# - Add tool-specific permissions/authorization
# - Implement long-running tools with progress notifications
# - Add tool result caching for expensive operations

