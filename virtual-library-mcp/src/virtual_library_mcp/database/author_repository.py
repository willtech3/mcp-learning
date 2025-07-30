"""
Author repository implementation for the Virtual Library MCP Server.

This repository provides data access for authors, supporting:

1. **MCP Resources**: Read operations for browsing authors and their bibliographies
2. **Relationships**: Efficient queries for author-book relationships
3. **Search**: Finding authors by name or nationality
4. **Statistics**: Book counts and other author metrics

The repository ensures clean separation between the MCP protocol layer
and database operations, returning Pydantic models for JSON serialization.
"""

import enum
from datetime import date

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload

from ..database.schema import Author as AuthorDB
from ..database.schema import Book as BookDB
from ..database.session import mcp_safe_commit, mcp_safe_query
from ..models.author import Author as AuthorModel
from .repository import (
    BaseRepository,
    PaginatedResponse,
    PaginationParams,
    RepositoryException,
)


class AuthorCreateSchema(BaseModel):
    """Schema for creating a new author."""

    name: str
    biography: str | None = None
    birth_date: date | None = None
    death_date: date | None = None
    nationality: str | None = None
    photo_url: str | None = None
    website: str | None = None


class AuthorUpdateSchema(BaseModel):
    """Schema for updating an author - all fields optional."""

    name: str | None = None
    biography: str | None = None
    birth_date: date | None = None
    death_date: date | None = None
    nationality: str | None = None
    photo_url: str | None = None
    website: str | None = None


class AuthorSearchParams(BaseModel):
    """
    Search parameters for finding authors.

    These parameters support MCP Resource queries for author discovery.
    """

    query: str | None = None  # General search term
    name: str | None = None  # Name contains
    nationality: str | None = None  # Exact nationality match
    is_living: bool | None = None  # Filter by living/deceased status
    has_books: bool | None = None  # Only authors with books in library


class AuthorSortOptions(str, enum.Enum):
    """Sorting options for author queries."""

    NAME = "name"
    BIRTH_DATE = "birth_date"
    NATIONALITY = "nationality"
    BOOK_COUNT = "book_count"
    CREATED_AT = "created_at"


class AuthorWithStats(AuthorModel):
    """Author model extended with statistics."""

    total_books: int = 0
    available_books: int = 0


class AuthorRepository(
    BaseRepository[AuthorDB, AuthorCreateSchema, AuthorUpdateSchema, AuthorModel]
):
    """
    Repository for author data access.

    This repository supports MCP server operations:
    - Read methods for MCP Resources (library://authors/*)
    - Relationship queries for author-book connections
    - Search and filtering for author discovery
    """

    @property
    def model_class(self):
        return AuthorDB

    @property
    def response_schema(self):
        return AuthorModel

    def create(self, data: AuthorCreateSchema) -> AuthorModel:
        """
        Create a new author with generated ID.

        Args:
            data: Author creation data

        Returns:
            Created author model
        """
        # Generate author ID
        author_id = self._generate_author_id(data.name)

        try:
            db_author = AuthorDB(id=author_id, **data.model_dump())
            self.session.add(db_author)
            mcp_safe_commit(self.session, "create author")
            self.session.refresh(db_author)

            # Convert to Pydantic model with book_ids
            return self._to_response_model_with_books(db_author)
        except Exception as e:
            self.session.rollback()
            raise RepositoryException(f"Failed to create author: {e!s}") from e

    def search(
        self,
        search_params: AuthorSearchParams,
        pagination: PaginationParams | None = None,
        sort_by: AuthorSortOptions = AuthorSortOptions.NAME,
        sort_desc: bool = False,
    ) -> PaginatedResponse[AuthorModel]:
        """
        Search for authors with various filters.
        
        MCP Resource Examples:
        - library://authors/search?name=fitzgerald
        - library://authors/search?nationality=American&is_living=false
        - library://authors/search?name=jane+austen&sort_by=birth_year
        - library://authors/search?birth_year_from=1900&birth_year_to=1950
        - library://authors/search?death_year_from=2000&is_living=false
        - library://authors/search?page_size=20&offset=40
        
        Supports partial name matching and filtering by nationality,
        birth/death years, and living status.

        Args:
            search_params: Search and filter criteria
            pagination: Pagination parameters
            sort_by: Field to sort by
            sort_desc: Sort in descending order

        Returns:
            Paginated response with matching authors
        """
        query = select(AuthorDB)

        # Apply filters
        filters = []

        # General search across multiple fields
        if search_params.query:
            search_term = f"%{search_params.query}%"
            filters.append(
                or_(
                    AuthorDB.name.ilike(search_term),
                    AuthorDB.biography.ilike(search_term),
                    AuthorDB.nationality.ilike(search_term),
                )
            )

        # Specific field searches
        if search_params.name:
            filters.append(AuthorDB.name.ilike(f"%{search_params.name}%"))

        if search_params.nationality:
            filters.append(AuthorDB.nationality == search_params.nationality.strip().title())

        if search_params.is_living is not None:
            if search_params.is_living:
                filters.append(AuthorDB.death_date.is_(None))
            else:
                filters.append(AuthorDB.death_date.is_not(None))

        # Filter authors with/without books
        if search_params.has_books is not None:
            if search_params.has_books:
                # Use EXISTS subquery to find authors with books
                book_exists = select(BookDB).where(BookDB.author_id == AuthorDB.id).exists()
                filters.append(book_exists)
            else:
                # Find authors without books
                book_not_exists = ~select(BookDB).where(BookDB.author_id == AuthorDB.id).exists()
                filters.append(book_not_exists)

        # Apply all filters
        if filters:
            query = query.where(and_(*filters))

        # Apply sorting
        if sort_by == AuthorSortOptions.BOOK_COUNT:
            # Special handling for book count sorting
            book_count_subquery = (
                select(func.count(BookDB.isbn))
                .where(BookDB.author_id == AuthorDB.id)
                .scalar_subquery()
            )
            query = query.order_by(
                book_count_subquery.desc() if sort_desc else book_count_subquery.asc()
            )
        else:
            sort_field = {
                AuthorSortOptions.NAME: AuthorDB.name,
                AuthorSortOptions.BIRTH_DATE: AuthorDB.birth_date,
                AuthorSortOptions.NATIONALITY: AuthorDB.nationality,
                AuthorSortOptions.CREATED_AT: AuthorDB.created_at,
            }.get(sort_by, AuthorDB.name)

            query = query.order_by(sort_field.desc() if sort_desc else sort_field.asc())

        # Handle pagination
        if not pagination:
            pagination = PaginationParams()

        pagination.validate_params()

        # Get total count
        count_query = select(func.count()).select_from(AuthorDB)
        if filters:
            count_query = count_query.where(and_(*filters))

        total = (
            mcp_safe_query(
                self.session, lambda s: s.execute(count_query).scalar(), "Failed to count authors"
            )
            or 0
        )

        # Apply pagination
        query = query.offset(pagination.offset).limit(pagination.page_size)

        # Execute query with eager loading of books
        query = query.options(joinedload(AuthorDB.books))
        results = mcp_safe_query(
            self.session,
            lambda s: s.execute(query).unique().scalars().all(),
            "Failed to search authors",
        )

        # Convert to Pydantic models with book_ids
        items = [self._to_response_model_with_books(author) for author in results]

        return PaginatedResponse(
            items=items,
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            total_pages=(total + pagination.page_size - 1) // pagination.page_size,
            has_next=pagination.page * pagination.page_size < total,
            has_previous=pagination.page > 1,
        )

    def get_by_id_with_stats(self, author_id: str) -> AuthorWithStats | None:
        """
        Get author with book statistics.

        Supports MCP Resources like: library://authors/{id}/stats

        Args:
            author_id: Author ID

        Returns:
            Author with statistics or None if not found
        """
        query = select(AuthorDB).where(AuthorDB.id == author_id)
        query = query.options(joinedload(AuthorDB.books))

        author = mcp_safe_query(
            self.session,
            lambda s: s.execute(query).unique().scalar_one_or_none(),
            "Failed to get author with stats",
        )

        if author is None:
            return None

        # Calculate statistics
        total_books = len(author.books)
        available_books = sum(1 for book in author.books if book.available_copies > 0)

        # Convert to model with stats
        author_dict = self._to_response_model_with_books(author).model_dump()
        return AuthorWithStats(
            **author_dict, total_books=total_books, available_books=available_books
        )

    def get_nationalities(self) -> list[str]:
        """
        Get list of all nationalities in the system.

        Supports MCP Resources like: library://authors/nationalities

        Returns:
            List of unique nationality names
        """
        query = (
            select(AuthorDB.nationality)
            .distinct()
            .where(AuthorDB.nationality.is_not(None))
            .order_by(AuthorDB.nationality)
        )

        results = mcp_safe_query(
            self.session, lambda s: s.execute(query).scalars().all(), "Failed to get nationalities"
        )
        return list(results)

    def _generate_author_id(self, name: str) -> str:
        """
        Generate a unique author ID from the name.

        Args:
            name: Author's full name

        Returns:
            Generated author ID
        """
        # Create base ID from name
        base_id = "author_" + "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")

        # Check for uniqueness and add suffix if needed
        suffix = 1
        author_id = base_id

        while self.exists(author_id):
            author_id = f"{base_id}_{suffix:02d}"
            suffix += 1

        return author_id

    def _to_response_model_with_books(self, db_author: AuthorDB) -> AuthorModel:
        """
        Convert database author to Pydantic model with book_ids populated.

        Args:
            db_author: Database author object

        Returns:
            Author model with book_ids
        """
        # Get book ISBNs from relationship
        book_ids = [book.isbn for book in db_author.books] if db_author.books else []

        # Convert to dict and add book_ids
        author_dict = {
            "id": db_author.id,
            "name": db_author.name,
            "biography": db_author.biography,
            "birth_date": db_author.birth_date,
            "death_date": db_author.death_date,
            "nationality": db_author.nationality,
            "photo_url": db_author.photo_url,
            "website": db_author.website,
            "created_at": db_author.created_at,
            "updated_at": db_author.updated_at,
            "book_ids": book_ids,
        }

        return AuthorModel(**author_dict)
