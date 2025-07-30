"""
Repository pattern implementation for the Virtual Library MCP Server.

This module provides a clean data access layer that abstracts database operations
from MCP protocol handlers. The repository pattern is crucial for MCP servers because:

1. **Protocol Separation**: MCP Resources and Tools can focus on protocol logic
   without database concerns
2. **Testability**: Repositories can be easily mocked for testing MCP handlers
3. **Consistency**: All data access follows the same patterns, making the codebase
   predictable
4. **MCP Compatibility**: Methods return Pydantic models that serialize cleanly
   to JSON for MCP responses

The base repository provides common CRUD operations, while specialized repositories
add domain-specific queries needed by MCP Resources (read operations) and Tools
(write operations).
"""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import asc, desc, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..database.schema import Base
from ..database.session import mcp_safe_commit, mcp_safe_query

# Type variables for generic repository
ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)
ResponseSchemaType = TypeVar("ResponseSchemaType", bound=BaseModel)


class RepositoryException(Exception):
    """Base exception for repository operations."""


class NotFoundError(RepositoryException):
    """Raised when an entity is not found."""


class DuplicateError(RepositoryException):
    """Raised when attempting to create a duplicate entity."""


class PaginationParams(BaseModel):
    """Standard pagination parameters for MCP list operations."""

    page: int = 1
    page_size: int = 20

    @property
    def offset(self) -> int:
        """Calculate offset for SQL queries."""
        return (self.page - 1) * self.page_size

    def validate_params(self) -> None:
        """Validate pagination parameters."""
        if self.page < 1:
            raise ValueError("Page must be >= 1")
        if self.page_size < 1 or self.page_size > 100:
            raise ValueError("Page size must be between 1 and 100")


class PaginatedResponse(BaseModel, Generic[ResponseSchemaType]):
    """
    Standard paginated response for MCP list operations.

    This structure ensures consistent pagination across all MCP Resources
    that return lists of items.
    """

    items: list[ResponseSchemaType]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool


class BaseRepository(
    ABC, Generic[ModelType, CreateSchemaType, UpdateSchemaType, ResponseSchemaType]
):
    """
    Abstract base repository providing common CRUD operations.

    This base class implements the repository pattern for MCP servers,
    ensuring consistent data access patterns across all entities.
    All methods use mcp_safe_query and mcp_safe_commit for proper
    error handling in the MCP context.
    """

    def __init__(self, session: Session):
        """Initialize repository with database session."""
        self.session = session

    @property
    @abstractmethod
    def model_class(self) -> type[ModelType]:
        """Return the SQLAlchemy model class."""

    @property
    @abstractmethod
    def response_schema(self) -> type[ResponseSchemaType]:
        """Return the Pydantic response schema."""

    def _to_response_model(self, db_obj: ModelType) -> ResponseSchemaType:
        """Convert database model to Pydantic response model."""
        return self.response_schema.model_validate(db_obj, from_attributes=True)

    def get_by_id(self, id: UUID | str) -> ResponseSchemaType | None:
        """
        Get entity by ID.

        Args:
            id: Entity ID (UUID or string)

        Returns:
            Pydantic model or None if not found

        Raises:
            RepositoryException: On database errors
        """
        query = select(self.model_class).where(self.model_class.id == str(id))
        result = mcp_safe_query(
            self.session,
            lambda s: s.execute(query),
            f"Failed to get {self.model_class.__name__} by ID",
        )

        if result is None:
            return None

        db_obj = result.scalar_one_or_none()
        if db_obj is None:
            return None

        return self._to_response_model(db_obj)

    def get_all(
        self,
        pagination: PaginationParams | None = None,
        order_by: str | None = None,
        order_desc: bool = False,
    ) -> list[ResponseSchemaType] | PaginatedResponse[ResponseSchemaType]:
        """
        Get all entities with optional pagination and sorting.

        Args:
            pagination: Pagination parameters
            order_by: Field name to order by
            order_desc: Whether to order descending

        Returns:
            List of entities or paginated response

        Raises:
            RepositoryException: On database errors
        """
        query = select(self.model_class)

        # Apply ordering
        if order_by and hasattr(self.model_class, order_by):
            order_field = getattr(self.model_class, order_by)
            query = query.order_by(desc(order_field) if order_desc else asc(order_field))

        if pagination:
            pagination.validate_params()

            # Get total count
            count_query = select(func.count()).select_from(self.model_class)
            total = (
                mcp_safe_query(
                    self.session,
                    lambda s: s.execute(count_query).scalar(),
                    "Failed to get total count",
                )
                or 0
            )

            # Apply pagination
            query = query.offset(pagination.offset).limit(pagination.page_size)
            results = mcp_safe_query(
                self.session,
                lambda s: s.execute(query).scalars().all(),
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
        results = mcp_safe_query(
            self.session, lambda s: s.execute(query).scalars().all(), "Failed to get all results"
        )
        return [self._to_response_model(item) for item in results]

    def create(self, data: CreateSchemaType) -> ResponseSchemaType:
        """
        Create new entity.

        Args:
            data: Pydantic create schema

        Returns:
            Created entity as Pydantic model

        Raises:
            DuplicateError: If entity already exists
            RepositoryException: On other database errors
        """
        try:
            db_obj = self.model_class(**data.model_dump())
            self.session.add(db_obj)
            mcp_safe_commit(self.session, f"create {self.model_class.__name__}")
            self.session.refresh(db_obj)
            return self._to_response_model(db_obj)
        except IntegrityError as e:
            self.session.rollback()
            raise DuplicateError(f"Entity already exists: {e!s}") from e
        except SQLAlchemyError as e:
            self.session.rollback()
            raise RepositoryException(f"Database error: {e!s}") from e

    def update(self, id: UUID | str, data: UpdateSchemaType) -> ResponseSchemaType | None:
        """
        Update existing entity.

        Args:
            id: Entity ID
            data: Pydantic update schema

        Returns:
            Updated entity or None if not found

        Raises:
            RepositoryException: On database errors
        """
        query = select(self.model_class).where(self.model_class.id == str(id))
        db_obj = mcp_safe_query(
            self.session,
            lambda s: s.execute(query).scalar_one_or_none(),
            f"Failed to get {self.model_class.__name__} for update",
        )

        if db_obj is None:
            return None

        # Update fields
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(db_obj, field, value)

        try:
            mcp_safe_commit(self.session, f"update {self.model_class.__name__}")
            self.session.refresh(db_obj)
            return self._to_response_model(db_obj)
        except SQLAlchemyError as e:
            self.session.rollback()
            raise RepositoryException(f"Update failed: {e!s}") from e

    def delete(self, id: UUID | str) -> bool:
        """
        Delete entity by ID.

        Args:
            id: Entity ID

        Returns:
            True if deleted, False if not found

        Raises:
            RepositoryException: On database errors
        """
        query = select(self.model_class).where(self.model_class.id == str(id))
        db_obj = mcp_safe_query(
            self.session,
            lambda s: s.execute(query).scalar_one_or_none(),
            f"Failed to get {self.model_class.__name__} for deletion",
        )

        if db_obj is None:
            return False

        try:
            self.session.delete(db_obj)
            mcp_safe_commit(self.session, f"delete {self.model_class.__name__}")
            return True
        except SQLAlchemyError as e:
            self.session.rollback()
            raise RepositoryException(f"Delete failed: {e!s}") from e

    def exists(self, id: UUID | str) -> bool:
        """
        Check if entity exists by ID.

        Args:
            id: Entity ID

        Returns:
            True if exists, False otherwise
        """
        query = (
            select(func.count()).select_from(self.model_class).where(self.model_class.id == str(id))
        )
        count = mcp_safe_query(
            self.session, lambda s: s.execute(query).scalar(), "Failed to check existence"
        )
        return count > 0
