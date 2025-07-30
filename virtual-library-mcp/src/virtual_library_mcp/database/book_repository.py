"""
Book repository implementation for the Virtual Library MCP Server.

This repository provides data access for books, supporting the MCP protocol's
resource and tool requirements:

1. **MCP Resources**: Read operations for browsing, searching, and filtering books
2. **MCP Tools**: Write operations for circulation (checkout/return)
3. **Pagination**: Consistent with MCP's request/response patterns
4. **Search**: Full-text search capabilities for better user experience

The repository abstracts SQLAlchemy queries into clean methods that return
Pydantic models, ensuring seamless JSON serialization for MCP responses.

Note: This learning project uses local timezone for all datetime operations
to simulate realistic library operations where business hours, due dates, and
patron interactions occur in local time.
"""

import enum
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload

from ..database.schema import Author as AuthorDB
from ..database.schema import Book as BookDB
from ..database.session import mcp_safe_commit, mcp_safe_query
from ..models.book import Book as BookModel
from .repository import (
    BaseRepository,
    DuplicateError,
    NotFoundError,
    PaginatedResponse,
    PaginationParams,
    RepositoryException,
)


class BookCreateSchema(BookModel):
    """Schema for creating a new book - same as base model."""


class BookUpdateSchema(BaseModel):
    """Schema for updating a book - all fields optional."""

    isbn: str | None = None
    title: str | None = None
    author_id: str | None = None
    genre: str | None = None
    publication_year: int | None = None
    available_copies: int | None = None
    total_copies: int | None = None
    description: str | None = None
    cover_url: str | None = None


class BookSearchParams(BaseModel):
    """
    Search parameters for finding books.

    These parameters map directly to MCP resource query parameters,
    enabling flexible book discovery through the protocol.
    """

    query: str | None = None  # General search term
    title: str | None = None  # Title contains
    author_name: str | None = None  # Author name contains
    genre: str | None = None  # Exact genre match
    isbn: str | None = None  # ISBN exact or partial match
    available_only: bool = False  # Only show available books
    publication_year_from: int | None = None
    publication_year_to: int | None = None


class BookSortOptions(str, enum.Enum):
    """Sorting options for book queries."""

    TITLE = "title"
    AUTHOR = "author"
    PUBLICATION_YEAR = "publication_year"
    AVAILABILITY = "availability"
    GENRE = "genre"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class BookRepository(BaseRepository[BookDB, BookCreateSchema, BookUpdateSchema, BookModel]):
    """
    Repository for book data access.

    This repository is designed for MCP server usage:
    - Read methods support MCP Resources (URIs like library://books/search)
    - Write methods support MCP Tools (operations like checkout_book)
    - All methods return Pydantic models for clean JSON serialization
    - Pagination follows MCP best practices for list responses
    """

    @property
    def model_class(self):
        return BookDB

    @property
    def response_schema(self):
        return BookModel

    def search(
        self,
        search_params: BookSearchParams,
        pagination: PaginationParams | None = None,
        sort_by: BookSortOptions = BookSortOptions.TITLE,
        sort_desc: bool = False,
    ) -> PaginatedResponse[BookModel]:
        """
        Search for books with various filters.

        This method powers MCP Resources like:
        - library://books/search?query=gatsby
        - library://books/search?genre=Fiction&available_only=true

        Args:
            search_params: Search and filter criteria
            pagination: Pagination parameters
            sort_by: Field to sort by
            sort_desc: Sort in descending order

        Returns:
            Paginated response with matching books
        """
        # Build base query with author join for author name search
        query = select(BookDB).join(AuthorDB, BookDB.author_id == AuthorDB.id)

        # Apply filters
        filters = []

        # General search across multiple fields
        if search_params.query:
            search_term = f"%{search_params.query}%"
            filters.append(
                or_(
                    BookDB.title.ilike(search_term),
                    BookDB.description.ilike(search_term),
                    BookDB.isbn.like(search_term),
                    AuthorDB.name.ilike(search_term),
                )
            )

        # Specific field searches
        if search_params.title:
            filters.append(BookDB.title.ilike(f"%{search_params.title}%"))

        if search_params.author_name:
            filters.append(AuthorDB.name.ilike(f"%{search_params.author_name}%"))

        if search_params.genre:
            filters.append(BookDB.genre == search_params.genre)

        if search_params.isbn:
            # Support both exact and partial ISBN matching
            if len(search_params.isbn) == 13:
                filters.append(BookDB.isbn == search_params.isbn)
            else:
                filters.append(BookDB.isbn.like(f"%{search_params.isbn}%"))

        if search_params.available_only:
            filters.append(BookDB.available_copies > 0)

        if search_params.publication_year_from:
            filters.append(BookDB.publication_year >= search_params.publication_year_from)

        if search_params.publication_year_to:
            filters.append(BookDB.publication_year <= search_params.publication_year_to)

        # Apply all filters
        if filters:
            query = query.where(and_(*filters))

        # Apply sorting
        sort_field = {
            BookSortOptions.TITLE: BookDB.title,
            BookSortOptions.AUTHOR: AuthorDB.name,
            BookSortOptions.PUBLICATION_YEAR: BookDB.publication_year,
            BookSortOptions.AVAILABILITY: BookDB.available_copies,
            BookSortOptions.GENRE: BookDB.genre,
            BookSortOptions.CREATED_AT: BookDB.created_at,
            BookSortOptions.UPDATED_AT: BookDB.updated_at,
        }.get(sort_by, BookDB.title)

        query = query.order_by(sort_field.desc() if sort_desc else sort_field.asc())

        # Handle pagination
        if not pagination:
            pagination = PaginationParams()

        pagination.validate_params()

        # Get total count
        count_query = (
            select(func.count()).select_from(BookDB).join(AuthorDB, BookDB.author_id == AuthorDB.id)
        )
        if filters:
            count_query = count_query.where(and_(*filters))

        total = (
            mcp_safe_query(
                self.session, lambda s: s.execute(count_query).scalar(), "Failed to count books"
            )
            or 0
        )

        # Apply pagination to main query
        query = query.offset(pagination.offset).limit(pagination.page_size)

        # Execute query with eager loading of author
        query = query.options(joinedload(BookDB.author))
        results = mcp_safe_query(
            self.session,
            lambda s: s.execute(query).unique().scalars().all(),
            "Failed to search books",
        )

        # Convert to Pydantic models
        items = [self._to_response_model(book) for book in results]

        return PaginatedResponse(
            items=items,
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            total_pages=(total + pagination.page_size - 1) // pagination.page_size,
            has_next=pagination.page * pagination.page_size < total,
            has_previous=pagination.page > 1,
        )

    def get_by_isbn(self, isbn: str) -> BookModel | None:
        """
        Get book by ISBN.

        Supports MCP Resources like: library://books/isbn/{isbn}

        Args:
            isbn: ISBN-13 (with or without hyphens)

        Returns:
            Book model or None if not found
        """
        # Normalize ISBN by removing hyphens
        normalized_isbn = isbn.replace("-", "")

        query = select(BookDB).where(BookDB.isbn == normalized_isbn)
        query = query.options(joinedload(BookDB.author))

        result = mcp_safe_query(
            self.session,
            lambda s: s.execute(query).unique().scalar_one_or_none(),
            "Failed to get book by ISBN",
        )

        if result is None:
            return None

        return self._to_response_model(result)

    def get_by_author(
        self,
        author_id: str,
        pagination: PaginationParams | None = None,
        available_only: bool = False,
    ) -> PaginatedResponse[BookModel]:
        """
        Get all books by a specific author.

        Supports MCP Resources like: library://authors/{id}/books

        Args:
            author_id: Author ID
            pagination: Pagination parameters
            available_only: Only return available books

        Returns:
            Paginated list of books
        """
        query = select(BookDB).where(BookDB.author_id == author_id)

        if available_only:
            query = query.where(BookDB.available_copies > 0)

        query = query.order_by(BookDB.publication_year.desc())

        # Use base class method for pagination
        return self._paginate_query(query, pagination)

    def get_by_genre(
        self,
        genre: str,
        pagination: PaginationParams | None = None,
        sort_by: BookSortOptions = BookSortOptions.TITLE,
    ) -> PaginatedResponse[BookModel]:
        """
        Get all books in a specific genre.

        Supports MCP Resources like: library://books/genre/{genre}

        Args:
            genre: Genre name (case-insensitive)
            pagination: Pagination parameters
            sort_by: Sorting option

        Returns:
            Paginated list of books
        """
        # Normalize genre to match database storage
        normalized_genre = genre.strip().title()

        query = select(BookDB).where(BookDB.genre == normalized_genre)
        query = query.options(joinedload(BookDB.author))

        # Apply sorting
        sort_map = {
            BookSortOptions.TITLE: BookDB.title,
            BookSortOptions.PUBLICATION_YEAR: BookDB.publication_year,
            BookSortOptions.AVAILABILITY: BookDB.available_copies,
        }
        query = query.order_by(sort_map.get(sort_by, BookDB.title))

        return self._paginate_query(query, pagination)

    def get_available_genres(self) -> list[str]:
        """
        Get list of all genres in the library.

        Supports MCP Resources like: library://books/genres

        Returns:
            List of unique genre names
        """
        query = select(BookDB.genre).distinct().order_by(BookDB.genre)
        results = mcp_safe_query(
            self.session, lambda s: s.execute(query).scalars().all(), "Failed to get genres"
        )
        return list(results)

    def update_availability(self, isbn: str, delta: int, operation: str = "checkout") -> BookModel:
        """
        Update book availability for circulation operations.

        This method supports MCP Tools like checkout_book and return_book.
        It ensures atomic updates with proper validation.

        Args:
            isbn: Book ISBN
            delta: Change in available copies (-1 for checkout, +1 for return)
            operation: Operation name for error messages

        Returns:
            Updated book model

        Raises:
            NotFoundError: If book not found
            RepositoryException: If operation would violate constraints
        """
        # Normalize ISBN
        normalized_isbn = isbn.replace("-", "")

        # Get book with lock for update
        query = select(BookDB).where(BookDB.isbn == normalized_isbn).with_for_update()
        book = mcp_safe_query(
            self.session,
            lambda s: s.execute(query).scalar_one_or_none(),
            "Failed to get book for availability update",
        )

        if book is None:
            raise NotFoundError(f"Book with ISBN {isbn} not found")

        # Validate the operation
        new_available = book.available_copies + delta

        if new_available < 0:
            raise RepositoryException(f"Cannot {operation}: No copies available")

        if new_available > book.total_copies:
            raise RepositoryException(f"Cannot {operation}: Would exceed total copies")

        # Update availability
        book.available_copies = new_available
        book.updated_at = datetime.now()

        try:
            mcp_safe_commit(self.session, f"{operation} book")
            self.session.refresh(book)
            return self._to_response_model(book)
        except Exception as e:
            self.session.rollback()
            raise RepositoryException(f"Failed to update availability: {e!s}") from e

    def update(self, book_id: str, data: BookUpdateSchema) -> BookModel | None:
        """
        Update book information.

        This method supports MCP Tools for library administration.
        It validates author existence when changing author_id and
        ensures ISBN remains unique if updated.

        Args:
            book_id: Book ID (ISBN)
            data: Update data with changed fields only

        Returns:
            Updated book model or None if not found

        Raises:
            NotFoundError: If new author_id doesn't exist
            DuplicateError: If new ISBN already exists
            RepositoryException: On other errors
        """
        # Get book with lock
        query = select(BookDB).where(BookDB.isbn == book_id).with_for_update()
        book = mcp_safe_query(
            self.session,
            lambda s: s.execute(query).scalar_one_or_none(),
            "Failed to get book for update",
        )

        if book is None:
            return None

        # Validate new author if changing
        if data.author_id is not None and data.author_id != book.author_id:
            author_exists = (
                mcp_safe_query(
                    self.session,
                    lambda s: s.execute(
                        select(func.count())
                        .select_from(AuthorDB)
                        .where(AuthorDB.id == data.author_id)
                    ).scalar(),
                    "Failed to check author existence",
                )
                > 0
            )

            if not author_exists:
                raise NotFoundError(f"Author {data.author_id} not found")

        # Validate new ISBN if changing
        if data.isbn is not None and data.isbn != book.isbn:
            isbn_exists = (
                mcp_safe_query(
                    self.session,
                    lambda s: s.execute(
                        select(func.count()).select_from(BookDB).where(BookDB.isbn == data.isbn)
                    ).scalar(),
                    "Failed to check ISBN existence",
                )
                > 0
            )

            if isbn_exists:
                raise DuplicateError(f"Book with ISBN {data.isbn} already exists")

        # Update fields
        update_dict = data.model_dump(exclude_unset=True)
        for field, value in update_dict.items():
            setattr(book, field, value)

        book.updated_at = datetime.now()

        try:
            mcp_safe_commit(self.session, "update book")
            self.session.refresh(book)
            return self._to_response_model(book)
        except Exception as e:
            self.session.rollback()
            raise RepositoryException(f"Failed to update book: {e!s}") from e

    def _paginate_query(self, query, pagination: PaginationParams | None):
        """Helper method to paginate a query."""
        if not pagination:
            pagination = PaginationParams()

        pagination.validate_params()

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = (
            mcp_safe_query(
                self.session,
                lambda s: s.execute(count_query).scalar(),
                "Failed to count in pagination",
            )
            or 0
        )

        # Apply pagination
        query = query.offset(pagination.offset).limit(pagination.page_size)
        results = mcp_safe_query(
            self.session,
            lambda s: s.execute(query).unique().scalars().all(),
            "Failed to get paginated results",
        )

        items = [self._to_response_model(item) for item in results]

        return PaginatedResponse(
            items=items,
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            total_pages=(total + pagination.page_size - 1) // pagination.page_size,
            has_next=pagination.page * pagination.page_size < total,
            has_previous=pagination.page > 1,
        )
