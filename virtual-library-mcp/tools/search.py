"""Search Tool - Library Catalog Search

Provides full-text and filtered search across the book catalog.

MCP concepts demonstrated:
- Typed parameters: FastMCP turns the function signature into a rich JSON
  Schema (field names, types, constraints, descriptions) — exactly what an
  LLM needs to call the tool correctly without guessing.
- Structured output: the typed ``SearchResults`` return model becomes the
  tool's outputSchema, and results arrive as machine-readable
  structuredContent alongside the human-readable summary.
- Tool execution errors (SEP-1303): invalid usage raises ToolError, which
  reaches the model as an isError result it can self-correct from.
"""

import logging
from typing import Annotated, Literal

from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

from database.book_repository import BookRepository, BookSearchParams, BookSortOptions
from database.repository import PaginationParams
from database.session import get_session
from models.book import Book

logger = logging.getLogger(__name__)

SORT_OPTIONS: dict[str, BookSortOptions] = {
    "relevance": BookSortOptions.TITLE,  # until relevance scoring exists
    "title": BookSortOptions.TITLE,
    "author": BookSortOptions.AUTHOR,
    "publication_year": BookSortOptions.PUBLICATION_YEAR,
    "availability": BookSortOptions.AVAILABILITY,
}


class BookSummary(BaseModel):
    """A catalog entry as returned in search results."""

    isbn: str
    title: str
    author_id: str
    genre: str
    publication_year: int
    available_copies: int
    total_copies: int
    is_available: bool
    description: str | None = None


class PageInfo(BaseModel):
    """Pagination metadata for a result page."""

    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    has_previous: bool


class SearchResults(BaseModel):
    """Structured output for search_catalog (becomes the tool's outputSchema)."""

    summary: str
    books: list[BookSummary]
    pagination: PageInfo


def _to_summary(book: Book) -> BookSummary:
    return BookSummary(
        isbn=book.isbn,
        title=book.title,
        author_id=book.author_id,
        genre=book.genre,
        publication_year=book.publication_year,
        available_copies=book.available_copies,
        total_copies=book.total_copies,
        is_available=book.is_available,
        description=book.description,
    )


async def search_catalog(
    query: Annotated[
        str | None,
        Field(description="Full-text search across title, description, and ISBN", max_length=200),
    ] = None,
    genre: Annotated[
        str | None,
        Field(description="Filter by genre, e.g. 'Science Fiction' (case-insensitive)"),
    ] = None,
    author: Annotated[
        str | None,
        Field(
            description="Filter by author name (partial match, case-insensitive)", max_length=100
        ),
    ] = None,
    available_only: Annotated[
        bool, Field(description="Only return books with copies on the shelf")
    ] = False,
    page: Annotated[int, Field(description="Page number (1-indexed)", ge=1, le=1000)] = 1,
    page_size: Annotated[int, Field(description="Results per page", ge=1, le=50)] = 10,
    sort_by: Annotated[
        Literal["relevance", "title", "author", "publication_year", "availability"],
        Field(description="Sort order for results"),
    ] = "relevance",
    sort_desc: Annotated[bool, Field(description="Sort in descending order")] = False,
) -> SearchResults:
    """Search the library catalog for books.

    Supports full-text search, filtering by genre and author, pagination,
    and sorting. At least one of query, genre, or author must be provided.
    """
    query = query.strip() if query and query.strip() else None
    author = author.strip() if author and author.strip() else None
    genre = genre.strip().title() if genre and genre.strip() else None

    if not any([query, genre, author]):
        # ToolError (not a protocol error) so the model can retry with criteria.
        raise ToolError("Provide at least one search criterion: query, genre, or author.")

    with get_session() as session:
        repo = BookRepository(session)
        result = repo.search(
            search_params=BookSearchParams(
                query=query, genre=genre, author_name=author, available_only=available_only
            ),
            pagination=PaginationParams(page=page, page_size=page_size),
            sort_by=SORT_OPTIONS[sort_by],
            sort_desc=sort_desc,
        )

    books = [_to_summary(book) for book in result.items]
    if not books:
        summary = "No books found matching your search criteria."
    else:
        summary = f"Found {result.total} book(s) matching your search"
        if result.total > len(books):
            summary += f" (showing page {result.page} of {result.total_pages})"

    logger.info(
        "search_catalog | query=%s genre=%s author=%s -> %d results",
        query,
        genre,
        author,
        result.total,
    )

    return SearchResults(
        summary=summary,
        books=books,
        pagination=PageInfo(
            page=result.page,
            page_size=result.page_size,
            total=result.total,
            total_pages=result.total_pages,
            has_next=result.has_next,
            has_previous=result.has_previous,
        ),
    )
