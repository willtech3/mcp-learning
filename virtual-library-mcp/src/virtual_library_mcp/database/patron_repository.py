"""
Patron repository implementation for the Virtual Library MCP Server.

This repository manages library patron data and provides:

1. **Member Management**: CRUD operations for patron accounts
2. **Circulation Status**: Track current checkouts and borrowing capacity
3. **Fine Management**: Handle outstanding fines and payments
4. **Activity Tracking**: Monitor patron library usage
5. **MCP Integration**: Clean data access for Tools and Resources

The repository supports MCP's user-centric operations, ensuring proper
validation and state management for circulation workflows.
"""

import enum
import json
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import joinedload

from ..database.schema import CirculationStatusEnum, PatronStatusEnum
from ..database.schema import Patron as PatronDB
from ..database.session import mcp_safe_commit, mcp_safe_query
from ..models.patron import Patron as PatronModel
from ..models.patron import PatronStatus
from .repository import (
    BaseRepository,
    DuplicateError,
    NotFoundError,
    PaginatedResponse,
    PaginationParams,
    RepositoryException,
)


class PatronCreateSchema(BaseModel):
    """Schema for creating a new patron."""

    name: str
    email: str
    phone: str | None = None
    address: str | None = None
    membership_date: date | None = None
    expiration_date: date | None = None
    borrowing_limit: int = 5
    preferred_genres: list[str] = []
    notification_preferences: dict[str, bool] = {
        "email": True,
        "sms": False,
        "due_date_reminder": True,
        "new_arrivals": False,
    }


class PatronUpdateSchema(BaseModel):
    """Schema for updating a patron - all fields optional."""

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    expiration_date: date | None = None
    status: PatronStatus | None = None
    borrowing_limit: int | None = None
    preferred_genres: list[str] | None = None
    notification_preferences: dict[str, bool] | None = None


class PatronSearchParams(BaseModel):
    """
    Search parameters for finding patrons.

    These parameters enable flexible patron discovery for MCP Resources.
    """

    query: str | None = None  # General search term
    name: str | None = None  # Name contains
    email: str | None = None  # Email contains
    status: PatronStatus | None = None  # Exact status match
    has_checkouts: bool | None = None  # Currently has books checked out
    has_fines: bool | None = None  # Has outstanding fines
    membership_expired: bool | None = None  # Membership is expired


class PatronSortOptions(str, enum.Enum):
    """Sorting options for patron queries."""

    NAME = "name"
    EMAIL = "email"
    MEMBERSHIP_DATE = "membership_date"
    LAST_ACTIVITY = "last_activity"
    CURRENT_CHECKOUTS = "current_checkouts"
    OUTSTANDING_FINES = "outstanding_fines"
    CREATED_AT = "created_at"


class PatronWithStats(PatronModel):
    """Patron model extended with circulation statistics."""

    active_checkouts: list[dict[str, Any]] = []
    recent_returns: list[dict[str, Any]] = []
    total_fines_paid: float = 0.0


class PatronRepository(
    BaseRepository[PatronDB, PatronCreateSchema, PatronUpdateSchema, PatronModel]
):
    """
    Repository for patron data access.

    This repository is designed for MCP server usage:
    - Supports patron management Resources (library://patrons/*)
    - Enables circulation Tools (checkout, return, reserve)
    - Manages patron state for borrowing workflows
    - Handles fine tracking and payment processing
    """

    @property
    def model_class(self):
        return PatronDB

    @property
    def response_schema(self):
        return PatronModel

    def _to_response_model(self, db_obj: PatronDB) -> PatronModel:
        """
        Convert database patron to Pydantic model with JSON fields parsed.

        Args:
            db_obj: Database patron object

        Returns:
            Patron model with parsed JSON fields
        """
        # Parse JSON fields
        preferred_genres = []
        if db_obj.preferred_genres:
            try:
                preferred_genres = json.loads(db_obj.preferred_genres)
            except json.JSONDecodeError:
                preferred_genres = []

        notification_preferences = {
            "email": True,
            "sms": False,
            "due_date_reminder": True,
            "new_arrivals": False,
        }
        if db_obj.notification_preferences:
            try:
                notification_preferences = json.loads(db_obj.notification_preferences)
            except json.JSONDecodeError:
                pass

        # Convert to model
        return PatronModel(
            id=db_obj.id,
            name=db_obj.name,
            email=db_obj.email,
            phone=db_obj.phone,
            address=db_obj.address,
            membership_date=db_obj.membership_date,
            expiration_date=db_obj.expiration_date,
            status=PatronStatus(db_obj.status.value),
            borrowing_limit=db_obj.borrowing_limit,
            current_checkouts=db_obj.current_checkouts,
            total_checkouts=db_obj.total_checkouts,
            outstanding_fines=db_obj.outstanding_fines,
            preferred_genres=preferred_genres,
            notification_preferences=notification_preferences,
            created_at=db_obj.created_at,
            updated_at=db_obj.updated_at,
            last_activity=db_obj.last_activity,
        )

    def create(self, data: PatronCreateSchema) -> PatronModel:
        """
        Create a new patron with generated ID.

        Args:
            data: Patron creation data

        Returns:
            Created patron model

        Raises:
            DuplicateError: If email already exists
        """
        # Check for duplicate email
        existing = mcp_safe_query(
            self.session,
            lambda s: s.execute(
                select(PatronDB).where(PatronDB.email == data.email)
            ).scalar_one_or_none(),
            "Failed to check for duplicate email",
        )

        if existing:
            raise DuplicateError(f"Patron with email {data.email} already exists")

        # Generate patron ID
        patron_id = self._generate_patron_id(data.name)

        # Set default membership date if not provided
        membership_date = data.membership_date or datetime.now().date()

        # Convert JSON fields
        preferred_genres_json = json.dumps(data.preferred_genres)
        notification_prefs_json = json.dumps(data.notification_preferences)

        try:
            db_patron = PatronDB(
                id=patron_id,
                name=data.name,
                email=data.email,
                phone=data.phone,
                address=data.address,
                membership_date=membership_date,
                expiration_date=data.expiration_date,
                borrowing_limit=data.borrowing_limit,
                preferred_genres=preferred_genres_json,
                notification_preferences=notification_prefs_json,
            )
            self.session.add(db_patron)
            mcp_safe_commit(self.session, "create patron")
            self.session.refresh(db_patron)

            return self._to_response_model(db_patron)
        except Exception as e:
            self.session.rollback()
            raise RepositoryException(f"Failed to create patron: {e!s}") from e

    def search(
        self,
        search_params: PatronSearchParams,
        pagination: PaginationParams | None = None,
        sort_by: PatronSortOptions = PatronSortOptions.NAME,
        sort_desc: bool = False,
    ) -> PaginatedResponse[PatronModel]:
        """
        Search for patrons with various filters.

        Supports MCP Resources like:
        - library://patrons/search?name=smith
        - library://patrons/search?has_fines=true&status=active

        Args:
            search_params: Search and filter criteria
            pagination: Pagination parameters
            sort_by: Field to sort by
            sort_desc: Sort in descending order

        Returns:
            Paginated response with matching patrons
        """
        query = select(PatronDB)

        # Apply filters
        filters = []

        # General search across multiple fields
        if search_params.query:
            search_term = f"%{search_params.query}%"
            filters.append(
                or_(
                    PatronDB.name.ilike(search_term),
                    PatronDB.email.ilike(search_term),
                    PatronDB.phone.like(search_term) if search_params.query.isdigit() else False,
                )
            )

        # Specific field searches
        if search_params.name:
            filters.append(PatronDB.name.ilike(f"%{search_params.name}%"))

        if search_params.email:
            filters.append(PatronDB.email.ilike(f"%{search_params.email}%"))

        if search_params.status:
            filters.append(PatronDB.status == PatronStatusEnum(search_params.status.value))

        if search_params.has_checkouts is not None:
            if search_params.has_checkouts:
                filters.append(PatronDB.current_checkouts > 0)
            else:
                filters.append(PatronDB.current_checkouts == 0)

        if search_params.has_fines is not None:
            if search_params.has_fines:
                filters.append(PatronDB.outstanding_fines > 0)
            else:
                filters.append(PatronDB.outstanding_fines == 0)

        if search_params.membership_expired is not None:
            today = datetime.now().date()
            if search_params.membership_expired:
                filters.append(
                    and_(PatronDB.expiration_date.is_not(None), PatronDB.expiration_date < today)
                )
            else:
                filters.append(
                    or_(PatronDB.expiration_date.is_(None), PatronDB.expiration_date >= today)
                )

        # Apply all filters
        if filters:
            query = query.where(and_(*filters))

        # Apply sorting
        sort_field = {
            PatronSortOptions.NAME: PatronDB.name,
            PatronSortOptions.EMAIL: PatronDB.email,
            PatronSortOptions.MEMBERSHIP_DATE: PatronDB.membership_date,
            PatronSortOptions.LAST_ACTIVITY: PatronDB.last_activity,
            PatronSortOptions.CURRENT_CHECKOUTS: PatronDB.current_checkouts,
            PatronSortOptions.OUTSTANDING_FINES: PatronDB.outstanding_fines,
            PatronSortOptions.CREATED_AT: PatronDB.created_at,
        }.get(sort_by, PatronDB.name)

        query = query.order_by(desc(sort_field) if sort_desc else sort_field)

        # Handle pagination
        if not pagination:
            pagination = PaginationParams()

        pagination.validate_params()

        # Get total count
        count_query = select(func.count()).select_from(PatronDB)
        if filters:
            count_query = count_query.where(and_(*filters))

        total = (
            mcp_safe_query(
                self.session, lambda s: s.execute(count_query).scalar(), "Failed to count patrons"
            )
            or 0
        )

        # Apply pagination
        query = query.offset(pagination.offset).limit(pagination.page_size)

        # Execute query
        results = mcp_safe_query(
            self.session, lambda s: s.execute(query).scalars().all(), "Failed to search patrons"
        )

        # Convert to Pydantic models
        items = [self._to_response_model(patron) for patron in results]

        return PaginatedResponse(
            items=items,
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            total_pages=(total + pagination.page_size - 1) // pagination.page_size,
            has_next=pagination.page * pagination.page_size < total,
            has_previous=pagination.page > 1,
        )

    def get_by_email(self, email: str) -> PatronModel | None:
        """
        Get patron by email address.

        Args:
            email: Email address

        Returns:
            Patron model or None if not found
        """
        query = select(PatronDB).where(PatronDB.email == email)
        result = mcp_safe_query(
            self.session,
            lambda s: s.execute(query).scalar_one_or_none(),
            "Failed to get patron by email",
        )

        if result is None:
            return None

        return self._to_response_model(result)

    def get_with_activity(self, patron_id: str) -> PatronWithStats | None:
        """
        Get patron with recent activity and statistics.

        Supports MCP Resources like: library://patrons/{id}/activity

        Args:
            patron_id: Patron ID

        Returns:
            Patron with activity stats or None if not found
        """
        # Get patron with checkouts eagerly loaded
        query = select(PatronDB).where(PatronDB.id == patron_id)
        query = query.options(joinedload(PatronDB.checkouts), joinedload(PatronDB.returns))

        patron = mcp_safe_query(
            self.session,
            lambda s: s.execute(query).unique().scalar_one_or_none(),
            "Failed to get patron with stats",
        )

        if patron is None:
            return None

        # Get active checkouts
        active_checkouts = []
        for checkout in patron.checkouts:
            if checkout.status == CirculationStatusEnum.ACTIVE:
                active_checkouts.append(
                    {
                        "checkout_id": checkout.id,
                        "book_isbn": checkout.book_isbn,
                        "checkout_date": checkout.checkout_date,
                        "due_date": checkout.due_date,
                        "renewal_count": checkout.renewal_count,
                    }
                )

        # Get recent returns (last 10)
        recent_returns = []
        sorted_returns = sorted(
            [c for c in patron.checkouts if c.return_date],
            key=lambda x: x.return_date,
            reverse=True,
        )[:10]

        for ret in sorted_returns:
            recent_returns.append(
                {
                    "book_isbn": ret.book_isbn,
                    "checkout_date": ret.checkout_date,
                    "return_date": ret.return_date,
                    "was_overdue": ret.status == CirculationStatusEnum.OVERDUE,
                }
            )

        # Calculate total fines paid
        total_fines_paid = sum(
            c.fine_amount for c in patron.checkouts if c.fine_paid and c.fine_amount > 0
        )

        # Convert to extended model
        patron_dict = self._to_response_model(patron).model_dump()
        return PatronWithStats(
            **patron_dict,
            active_checkouts=active_checkouts,
            recent_returns=recent_returns,
            total_fines_paid=total_fines_paid,
        )

    def update_checkout_count(self, patron_id: str, delta: int) -> PatronModel:
        """
        Update patron's checkout count for circulation operations.

        Args:
            patron_id: Patron ID
            delta: Change in checkouts (+1 for checkout, -1 for return)

        Returns:
            Updated patron model

        Raises:
            NotFoundError: If patron not found
            RepositoryException: If operation would violate constraints
        """
        query = select(PatronDB).where(PatronDB.id == patron_id).with_for_update()
        patron = mcp_safe_query(
            self.session,
            lambda s: s.execute(query).scalar_one_or_none(),
            "Failed to get patron for checkout update",
        )

        if patron is None:
            raise NotFoundError(f"Patron {patron_id} not found")

        # Validate the operation
        new_checkouts = patron.current_checkouts + delta

        if new_checkouts < 0:
            raise RepositoryException("Cannot have negative checkouts")

        if delta > 0 and new_checkouts > patron.borrowing_limit:
            raise RepositoryException(f"Would exceed borrowing limit of {patron.borrowing_limit}")

        # Update counts
        patron.current_checkouts = new_checkouts
        if delta > 0:
            patron.total_checkouts += 1
        patron.last_activity = datetime.now()
        patron.updated_at = datetime.now()

        try:
            mcp_safe_commit(self.session, "update patron checkout count")
            self.session.refresh(patron)
            return self._to_response_model(patron)
        except Exception as e:
            self.session.rollback()
            raise RepositoryException(f"Failed to update checkout count: {e!s}") from e

    def update_fines(self, patron_id: str, amount: float, operation: str = "add") -> PatronModel:
        """
        Update patron's fine balance.

        Args:
            patron_id: Patron ID
            amount: Fine amount (positive)
            operation: "add" or "pay"

        Returns:
            Updated patron model

        Raises:
            NotFoundError: If patron not found
            RepositoryException: On validation errors
        """
        if amount < 0:
            raise RepositoryException("Fine amount must be positive")

        query = select(PatronDB).where(PatronDB.id == patron_id).with_for_update()
        patron = mcp_safe_query(
            self.session,
            lambda s: s.execute(query).scalar_one_or_none(),
            "Failed to get patron for fines update",
        )

        if patron is None:
            raise NotFoundError(f"Patron {patron_id} not found")

        if operation == "add":
            patron.outstanding_fines += amount
        elif operation == "pay":
            if amount > patron.outstanding_fines:
                raise RepositoryException("Payment exceeds outstanding fines")
            patron.outstanding_fines -= amount
        else:
            raise RepositoryException(f"Invalid operation: {operation}")

        patron.updated_at = datetime.now()

        try:
            mcp_safe_commit(self.session, f"update patron fines - {operation}")
            self.session.refresh(patron)
            return self._to_response_model(patron)
        except Exception as e:
            self.session.rollback()
            raise RepositoryException(f"Failed to update fines: {e!s}") from e

    def get_expiring_memberships(self, days_ahead: int = 30) -> list[PatronModel]:
        """
        Get patrons with memberships expiring soon.

        Supports MCP Resources for notification systems.

        Args:
            days_ahead: Number of days to look ahead

        Returns:
            List of patrons with expiring memberships
        """
        cutoff_date = datetime.now().date() + timedelta(days=days_ahead)

        query = (
            select(PatronDB)
            .where(
                and_(
                    PatronDB.expiration_date.is_not(None),
                    PatronDB.expiration_date <= cutoff_date,
                    PatronDB.expiration_date >= datetime.now().date(),
                    PatronDB.status == PatronStatusEnum.ACTIVE,
                )
            )
            .order_by(PatronDB.expiration_date)
        )

        results = mcp_safe_query(
            self.session,
            lambda s: s.execute(query).scalars().all(),
            "Failed to get patrons with expiring memberships",
        )
        return [self._to_response_model(patron) for patron in results]

    def _generate_patron_id(self, name: str) -> str:
        """
        Generate a unique patron ID from the name.

        Args:
            name: Patron's full name

        Returns:
            Generated patron ID
        """
        # Create base ID from name
        base_id = "patron_" + "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")

        # Ensure minimum length
        if len(base_id) < 14:  # patron_ + at least 7 chars
            base_id = base_id[:7] + base_id[7:].ljust(7, "0")

        # Check for uniqueness and add suffix if needed
        suffix = 1
        patron_id = base_id

        while self.exists(patron_id):
            patron_id = f"{base_id}{suffix:03d}"
            suffix += 1

        return patron_id
