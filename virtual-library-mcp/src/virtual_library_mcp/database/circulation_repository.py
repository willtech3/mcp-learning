"""
Circulation repository implementation for the Virtual Library MCP Server.

This repository manages all circulation operations:

1. **Checkouts**: Creating and managing book loans
2. **Returns**: Processing book returns with fine calculation
3. **Reservations**: Queue management for unavailable books
4. **Renewals**: Extending loan periods
5. **Overdue Management**: Tracking and reporting overdue items

This is the core repository for MCP Tools that perform library operations,
ensuring transactional integrity and proper state management across
books, patrons, and circulation records.
"""

import enum
from datetime import date, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import and_, desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..database.schema import Book as BookDB
from ..database.schema import CheckoutRecord as CheckoutDB
from ..database.schema import CirculationStatusEnum, ReservationStatusEnum
from ..database.schema import Patron as PatronDB
from ..database.schema import ReservationRecord as ReservationDB
from ..database.schema import ReturnRecord as ReturnDB
from ..database.session import mcp_safe_commit, mcp_safe_query
from ..models.circulation import CheckoutRecord as CheckoutModel
from ..models.circulation import CirculationStatus, ReservationStatus
from ..models.circulation import ReservationRecord as ReservationModel
from ..models.circulation import ReturnRecord as ReturnModel
from .book_repository import BookRepository
from .patron_repository import PatronRepository
from .repository import (
    NotFoundError,
    PaginatedResponse,
    PaginationParams,
    RepositoryException,
)


class CheckoutCreateSchema(BaseModel):
    """Schema for creating a checkout."""

    patron_id: str
    book_isbn: str
    due_date: date | None = None  # If not provided, use default loan period
    notes: str | None = None


class ReturnProcessSchema(BaseModel):
    """Schema for processing a return."""

    checkout_id: str
    condition: str = "good"
    notes: str | None = None
    processed_by: str | None = None


class ReservationCreateSchema(BaseModel):
    """Schema for creating a reservation."""

    patron_id: str
    book_isbn: str
    expiration_date: date | None = None  # If not provided, use default period
    notes: str | None = None


class CirculationStats(BaseModel):
    """Circulation statistics for reporting."""

    total_checkouts: int
    active_checkouts: int
    overdue_checkouts: int
    total_reservations: int
    pending_reservations: int
    returns_today: int
    returns_this_week: int
    returns_this_month: int


class CirculationSortOptions(str, enum.Enum):
    """Sorting options for circulation queries."""

    CHECKOUT_DATE = "checkout_date"
    DUE_DATE = "due_date"
    RETURN_DATE = "return_date"
    PATRON_NAME = "patron_name"
    BOOK_TITLE = "book_title"
    STATUS = "status"


class CirculationRepository:
    """
    Repository for circulation operations.

    This repository coordinates complex operations across multiple tables,
    ensuring data integrity for MCP Tools that modify library state.
    All operations are transactional to maintain consistency.
    """

    def __init__(self, session: Session):
        """Initialize with database session and sub-repositories."""
        self.session = session
        self.book_repo = BookRepository(session)
        self.patron_repo = PatronRepository(session)

    def checkout_book(self, checkout_data: CheckoutCreateSchema) -> CheckoutModel:
        """
        Process a book checkout.

        MCP Tool Examples:
        - checkout_book(patron_id="P-JANE123", book_id="B-PRIDE001")
        - checkout_book(patron_id="P-JOHN456", book_id="B-GATSBY001", due_date="2024-02-15")

        This method implements the core MCP Tool for borrowing books:
        1. Validates patron can checkout (active membership, within limits)
        2. Validates book is available (copies > 0)
        3. Creates checkout record with due date
        4. Updates book availability count
        5. Updates patron checkout count

        Args:
            checkout_data: Checkout creation data

        Returns:
            Created checkout record

        Raises:
            NotFoundError: If patron or book not found
            RepositoryException: If checkout not allowed
        """
        # Validate patron
        patron = mcp_safe_query(
            self.session,
            lambda s: s.execute(
                select(PatronDB).where(PatronDB.id == checkout_data.patron_id)
            ).scalar_one_or_none(),
            "Failed to get patron for checkout",
        )

        if not patron:
            raise NotFoundError(f"Patron {checkout_data.patron_id} not found")

        if not patron.can_checkout:
            if not patron.is_active:
                raise RepositoryException("Checkout denied - patron membership is not active")
            if patron.current_checkouts >= patron.borrowing_limit:
                raise RepositoryException(
                    f"Patron has reached borrowing limit of {patron.borrowing_limit}"
                )
            raise RepositoryException(
                "Checkout denied - patron has outstanding fines exceeding $10"
            )

        # Validate book availability
        book = mcp_safe_query(
            self.session,
            lambda s: s.execute(
                select(BookDB).where(BookDB.isbn == checkout_data.book_isbn).with_for_update()
            ).scalar_one_or_none(),
            "Failed to get book for checkout",
        )

        if not book:
            raise NotFoundError(f"Book {checkout_data.book_isbn} not found")

        if book.available_copies <= 0:
            raise RepositoryException(
                f"Book unavailable for checkout - no copies of '{book.title}' available"
            )

        # Calculate due date if not provided (14-day loan period)
        due_date = checkout_data.due_date or (datetime.now().date() + timedelta(days=14))

        # Generate checkout ID
        checkout_id = self._generate_checkout_id()

        try:
            # Create checkout record
            checkout = CheckoutDB(
                id=checkout_id,
                patron_id=checkout_data.patron_id,
                book_isbn=checkout_data.book_isbn,
                checkout_date=datetime.now(),
                due_date=due_date,
                status=CirculationStatusEnum.ACTIVE,
                notes=checkout_data.notes,
            )
            self.session.add(checkout)

            # Update book availability
            book.available_copies -= 1
            book.updated_at = datetime.now()

            # Update patron checkout count
            patron.current_checkouts += 1
            patron.total_checkouts += 1
            patron.last_activity = datetime.now()
            patron.updated_at = datetime.now()

            # Check for reservations to notify
            self._check_reservations_for_notification(book.isbn)

            # Commit transaction
            mcp_safe_commit(self.session, "create checkout")
            self.session.refresh(checkout)

            return self._checkout_to_model(checkout)

        except Exception as e:
            self.session.rollback()
            raise RepositoryException(f"Checkout failed: {e!s}") from e

    def return_book(self, return_data: ReturnProcessSchema) -> tuple[ReturnModel, CheckoutModel]:
        """
        Process a book return.

        This method implements the MCP Tool for returning books:
        1. Validates checkout exists and is active
        2. Calculates fines if overdue
        3. Creates return record
        4. Updates checkout status
        5. Updates book availability
        6. Updates patron checkout count

        Args:
            return_data: Return processing data

        Returns:
            Tuple of (return record, updated checkout record)

        Raises:
            NotFoundError: If checkout not found
            RepositoryException: If return not allowed
        """
        # Get checkout with relationships
        checkout = mcp_safe_query(
            self.session,
            lambda s: s.execute(
                select(CheckoutDB)
                .where(CheckoutDB.id == return_data.checkout_id)
                .options(joinedload(CheckoutDB.patron), joinedload(CheckoutDB.book))
            )
            .unique()
            .scalar_one_or_none(),
            "Failed to get checkout for return",
        )

        if not checkout:
            raise NotFoundError(f"Checkout {return_data.checkout_id} not found")

        if checkout.status != CirculationStatusEnum.ACTIVE:
            raise RepositoryException(
                f"Return failed - checkout is not active (current status: {checkout.status})"
            )

        # Calculate late days and fine
        return_date = datetime.now()
        late_days = max(0, (return_date.date() - checkout.due_date).days)
        fine_amount = late_days * 0.25  # $0.25 per day

        # Generate return ID
        return_id = self._generate_return_id()

        try:
            # Create return record
            return_record = ReturnDB(
                id=return_id,
                checkout_id=checkout.id,
                patron_id=checkout.patron_id,
                book_isbn=checkout.book_isbn,
                return_date=return_date,
                condition=return_data.condition,
                late_days=late_days,
                fine_assessed=fine_amount,
                fine_paid=0.0,  # Payment handled separately
                notes=return_data.notes,
                processed_by=return_data.processed_by,
            )
            self.session.add(return_record)

            # Update checkout record
            checkout.return_date = return_date
            checkout.status = CirculationStatusEnum.COMPLETED
            checkout.fine_amount = fine_amount
            checkout.updated_at = return_date

            # Update book availability
            checkout.book.available_copies += 1
            checkout.book.updated_at = return_date

            # Update patron
            checkout.patron.current_checkouts -= 1
            if fine_amount > 0:
                checkout.patron.outstanding_fines += fine_amount
            checkout.patron.last_activity = return_date
            checkout.patron.updated_at = return_date

            # Process reservation queue if book became available
            if checkout.book.available_copies == 1:  # First copy available
                self._process_reservation_queue(checkout.book_isbn)

            # Commit transaction
            mcp_safe_commit(self.session, "process return")
            self.session.refresh(return_record)
            self.session.refresh(checkout)

            return (self._return_to_model(return_record), self._checkout_to_model(checkout))

        except Exception as e:
            self.session.rollback()
            raise RepositoryException(f"Return failed: {e!s}") from e

    def create_reservation(self, reservation_data: ReservationCreateSchema) -> ReservationModel:
        """
        Create a book reservation.

        This method implements the MCP Tool for reserving unavailable books:
        1. Validates patron can make reservations
        2. Validates book exists
        3. Checks for existing reservation
        4. Creates reservation with queue position

        Args:
            reservation_data: Reservation creation data

        Returns:
            Created reservation record

        Raises:
            NotFoundError: If patron or book not found
            RepositoryException: If reservation not allowed
        """
        # Validate patron
        patron = mcp_safe_query(
            self.session,
            lambda s: s.execute(
                select(PatronDB).where(PatronDB.id == reservation_data.patron_id)
            ).scalar_one_or_none(),
            "Failed to get patron for reservation",
        )

        if not patron:
            raise NotFoundError(f"Patron {reservation_data.patron_id} not found")

        if not patron.is_active:
            raise RepositoryException("Reservation denied - patron membership is not active")

        # Validate book
        book = mcp_safe_query(
            self.session,
            lambda s: s.execute(
                select(BookDB).where(BookDB.isbn == reservation_data.book_isbn)
            ).scalar_one_or_none(),
            "Failed to get book for reservation",
        )

        if not book:
            raise NotFoundError(f"Book {reservation_data.book_isbn} not found")

        # Check for existing reservation
        existing = mcp_safe_query(
            self.session,
            lambda s: s.execute(
                select(ReservationDB).where(
                    and_(
                        ReservationDB.patron_id == reservation_data.patron_id,
                        ReservationDB.book_isbn == reservation_data.book_isbn,
                        ReservationDB.status.in_(
                            [ReservationStatusEnum.PENDING, ReservationStatusEnum.AVAILABLE]
                        ),
                    )
                )
            ).scalar_one_or_none(),
            "Failed to check existing reservation",
        )

        if existing:
            raise RepositoryException(
                "Reservation denied - patron already has an active reservation for this book"
            )

        # Get next queue position
        max_position = (
            mcp_safe_query(
                self.session,
                lambda s: s.execute(
                    select(func.max(ReservationDB.queue_position)).where(
                        and_(
                            ReservationDB.book_isbn == reservation_data.book_isbn,
                            ReservationDB.status == ReservationStatusEnum.PENDING,
                        )
                    )
                ).scalar(),
                "Failed to get max queue position",
            )
            or 0
        )

        # Calculate expiration date if not provided (90 days)
        expiration_date = reservation_data.expiration_date or (
            datetime.now().date() + timedelta(days=90)
        )

        # Generate reservation ID
        reservation_id = self._generate_reservation_id()

        try:
            # Create reservation
            reservation = ReservationDB(
                id=reservation_id,
                patron_id=reservation_data.patron_id,
                book_isbn=reservation_data.book_isbn,
                reservation_date=datetime.now(),
                expiration_date=expiration_date,
                status=ReservationStatusEnum.PENDING,
                queue_position=max_position + 1,
                notes=reservation_data.notes,
            )
            self.session.add(reservation)

            # Update patron activity
            patron.last_activity = datetime.now()
            patron.updated_at = datetime.now()

            # Commit transaction
            mcp_safe_commit(self.session, "create reservation")
            self.session.refresh(reservation)

            return self._reservation_to_model(reservation)

        except IntegrityError as e:
            self.session.rollback()
            raise RepositoryException(f"Reservation failed - queue position conflict: {e!s}") from e
        except Exception as e:
            self.session.rollback()
            raise RepositoryException(f"Reservation failed: {e!s}") from e

    def renew_checkout(self, checkout_id: str, extension_days: int = 14) -> CheckoutModel:
        """
        Renew a checkout for additional days.

        Args:
            checkout_id: Checkout to renew
            extension_days: Days to extend (default 14)

        Returns:
            Updated checkout record

        Raises:
            NotFoundError: If checkout not found
            RepositoryException: If renewal not allowed
        """
        checkout = mcp_safe_query(
            self.session,
            lambda s: s.execute(
                select(CheckoutDB).where(CheckoutDB.id == checkout_id)
            ).scalar_one_or_none(),
            "Failed to get checkout for renewal",
        )

        if not checkout:
            raise NotFoundError(f"Checkout {checkout_id} not found")

        if checkout.status != CirculationStatusEnum.ACTIVE:
            raise RepositoryException("Renewal denied - can only renew active checkouts")

        if checkout.renewal_count >= 3:
            raise RepositoryException("Renewal denied - maximum renewal limit (3) reached")

        if datetime.now().date() > checkout.due_date:
            raise RepositoryException("Renewal denied - cannot renew overdue items")

        # Check for reservations
        pending_reservations = (
            mcp_safe_query(
                self.session,
                lambda s: s.execute(
                    select(func.count())
                    .select_from(ReservationDB)
                    .where(
                        and_(
                            ReservationDB.book_isbn == checkout.book_isbn,
                            ReservationDB.status == ReservationStatusEnum.PENDING,
                        )
                    )
                ).scalar(),
                "Failed to count pending reservations",
            )
            or 0
        )

        if pending_reservations > 0:
            raise RepositoryException("Renewal denied - other patrons are waiting for this book")

        try:
            # Update checkout
            checkout.due_date = checkout.due_date + timedelta(days=extension_days)
            checkout.renewal_count += 1
            checkout.updated_at = datetime.now()

            mcp_safe_commit(self.session, "renew checkout")
            self.session.refresh(checkout)

            return self._checkout_to_model(checkout)

        except Exception as e:
            self.session.rollback()
            raise RepositoryException(f"Renewal failed: {e!s}") from e

    def get_active_checkouts(
        self,
        patron_id: str | None = None,
        pagination: PaginationParams | None = None,
        include_overdue_only: bool = False,
    ) -> PaginatedResponse[CheckoutModel]:
        """
        Get active checkouts with optional filters.

        Supports MCP Resources like:
        - library://checkouts/active
        - library://patrons/{id}/checkouts
        - library://checkouts/overdue

        Args:
            patron_id: Filter by patron
            pagination: Pagination parameters
            include_overdue_only: Only show overdue items

        Returns:
            Paginated list of active checkouts
        """
        query = select(CheckoutDB).where(CheckoutDB.status == CirculationStatusEnum.ACTIVE)

        if patron_id:
            query = query.where(CheckoutDB.patron_id == patron_id)

        if include_overdue_only:
            query = query.where(CheckoutDB.due_date < datetime.now().date())

        # Join for sorting by patron/book names
        query = query.join(PatronDB).join(BookDB)
        query = query.order_by(CheckoutDB.due_date)

        # Eager load relationships
        query = query.options(joinedload(CheckoutDB.patron), joinedload(CheckoutDB.book))

        return self._paginate_checkouts(query, pagination)

    def get_patron_history(
        self,
        patron_id: str,
        include_active: bool = True,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[CheckoutModel]:
        """
        Get checkout history for a patron.

        Args:
            patron_id: Patron ID
            include_active: Include active checkouts
            pagination: Pagination parameters

        Returns:
            Paginated checkout history
        """
        query = select(CheckoutDB).where(CheckoutDB.patron_id == patron_id)

        if not include_active:
            query = query.where(CheckoutDB.status != CirculationStatusEnum.ACTIVE)

        query = query.order_by(desc(CheckoutDB.checkout_date))
        query = query.options(joinedload(CheckoutDB.book))

        return self._paginate_checkouts(query, pagination)

    def get_reservation_queue(self, book_isbn: str) -> list[ReservationModel]:
        """
        Get reservation queue for a book.

        Args:
            book_isbn: Book ISBN

        Returns:
            Ordered list of pending reservations
        """
        query = (
            select(ReservationDB)
            .where(
                and_(
                    ReservationDB.book_isbn == book_isbn,
                    ReservationDB.status == ReservationStatusEnum.PENDING,
                )
            )
            .order_by(ReservationDB.queue_position)
        )

        query = query.options(joinedload(ReservationDB.patron))

        results = mcp_safe_query(
            self.session,
            lambda s: s.execute(query).unique().scalars().all(),
            "Failed to get reservation queue",
        )
        return [self._reservation_to_model(r) for r in results]

    def get_circulation_stats(self) -> CirculationStats:
        """
        Get circulation statistics for dashboard/reporting.

        Returns:
            Circulation statistics
        """
        # Total checkouts
        total_checkouts = (
            mcp_safe_query(
                self.session,
                lambda s: s.execute(select(func.count()).select_from(CheckoutDB)).scalar(),
                "Failed to count total checkouts",
            )
            or 0
        )

        # Active checkouts
        active_checkouts = (
            mcp_safe_query(
                self.session,
                lambda s: s.execute(
                    select(func.count())
                    .select_from(CheckoutDB)
                    .where(CheckoutDB.status == CirculationStatusEnum.ACTIVE)
                ).scalar(),
                "Failed to count active checkouts",
            )
            or 0
        )

        # Overdue checkouts
        overdue_checkouts = (
            mcp_safe_query(
                self.session,
                lambda s: s.execute(
                    select(func.count())
                    .select_from(CheckoutDB)
                    .where(
                        and_(
                            CheckoutDB.status == CirculationStatusEnum.ACTIVE,
                            CheckoutDB.due_date < datetime.now().date(),
                        )
                    )
                ).scalar(),
                "Failed to count overdue checkouts",
            )
            or 0
        )

        # Total reservations
        total_reservations = (
            mcp_safe_query(
                self.session,
                lambda s: s.execute(select(func.count()).select_from(ReservationDB)).scalar(),
                "Failed to count total reservations",
            )
            or 0
        )

        # Pending reservations
        pending_reservations = (
            mcp_safe_query(
                self.session,
                lambda s: s.execute(
                    select(func.count())
                    .select_from(ReservationDB)
                    .where(ReservationDB.status == ReservationStatusEnum.PENDING)
                ).scalar(),
                "Failed to count pending reservations",
            )
            or 0
        )

        # Returns today
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        returns_today = (
            mcp_safe_query(
                self.session,
                lambda s: s.execute(
                    select(func.count())
                    .select_from(ReturnDB)
                    .where(ReturnDB.return_date >= today_start)
                ).scalar(),
                "Failed to count returns today",
            )
            or 0
        )

        # Returns this week
        week_start = today_start - timedelta(days=today_start.weekday())
        returns_week = (
            mcp_safe_query(
                self.session,
                lambda s: s.execute(
                    select(func.count())
                    .select_from(ReturnDB)
                    .where(ReturnDB.return_date >= week_start)
                ).scalar(),
                "Failed to count returns this week",
            )
            or 0
        )

        # Returns this month
        month_start = today_start.replace(day=1)
        returns_month = (
            mcp_safe_query(
                self.session,
                lambda s: s.execute(
                    select(func.count())
                    .select_from(ReturnDB)
                    .where(ReturnDB.return_date >= month_start)
                ).scalar(),
                "Failed to count returns this month",
            )
            or 0
        )

        return CirculationStats(
            total_checkouts=total_checkouts,
            active_checkouts=active_checkouts,
            overdue_checkouts=overdue_checkouts,
            total_reservations=total_reservations,
            pending_reservations=pending_reservations,
            returns_today=returns_today,
            returns_this_week=returns_week,
            returns_this_month=returns_month,
        )

    def _check_reservations_for_notification(self, book_isbn: str) -> None:
        """Check if any reservations need notification after checkout."""
        # This would trigger MCP subscription notifications in a full implementation

    def _process_reservation_queue(self, book_isbn: str) -> None:
        """
        Process reservation queue when a book becomes available.

        Updates the first pending reservation to available status
        and sets pickup deadline.
        """
        first_in_queue = mcp_safe_query(
            self.session,
            lambda s: s.execute(
                select(ReservationDB)
                .where(
                    and_(
                        ReservationDB.book_isbn == book_isbn,
                        ReservationDB.status == ReservationStatusEnum.PENDING,
                    )
                )
                .order_by(ReservationDB.queue_position)
                .limit(1)
            ).scalar_one_or_none(),
            "Failed to get first reservation in queue",
        )

        if first_in_queue:
            first_in_queue.status = ReservationStatusEnum.AVAILABLE
            first_in_queue.notification_date = datetime.now()
            first_in_queue.pickup_deadline = datetime.now().date() + timedelta(days=3)
            first_in_queue.updated_at = datetime.now()

    def _generate_checkout_id(self) -> str:
        """Generate unique checkout ID."""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        count = (
            mcp_safe_query(
                self.session,
                lambda s: s.execute(
                    select(func.count())
                    .select_from(CheckoutDB)
                    .where(CheckoutDB.id.like(f"checkout_{timestamp}%"))
                ).scalar(),
                "Failed to count checkouts for ID generation",
            )
            or 0
        )
        return f"checkout_{timestamp}{count + 1:04d}"

    def _generate_return_id(self) -> str:
        """Generate unique return ID."""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        count = (
            mcp_safe_query(
                self.session,
                lambda s: s.execute(
                    select(func.count())
                    .select_from(ReturnDB)
                    .where(ReturnDB.id.like(f"return_{timestamp}%"))
                ).scalar(),
                "Failed to count returns for ID generation",
            )
            or 0
        )
        return f"return_{timestamp}{count + 1:04d}"

    def _generate_reservation_id(self) -> str:
        """Generate unique reservation ID."""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        count = (
            mcp_safe_query(
                self.session,
                lambda s: s.execute(
                    select(func.count())
                    .select_from(ReservationDB)
                    .where(ReservationDB.id.like(f"reservation_{timestamp}%"))
                ).scalar(),
                "Failed to count reservations for ID generation",
            )
            or 0
        )
        return f"reservation_{timestamp}{count + 1:04d}"

    def _checkout_to_model(self, checkout: CheckoutDB) -> CheckoutModel:
        """Convert checkout DB object to Pydantic model."""
        return CheckoutModel(
            id=checkout.id,
            patron_id=checkout.patron_id,
            book_isbn=checkout.book_isbn,
            checkout_date=checkout.checkout_date,
            due_date=checkout.due_date,
            return_date=checkout.return_date,
            status=CirculationStatus(checkout.status.value),
            renewal_count=checkout.renewal_count,
            fine_amount=checkout.fine_amount,
            fine_paid=checkout.fine_paid,
            notes=checkout.notes,
            created_at=checkout.created_at,
            updated_at=checkout.updated_at,
        )

    def _return_to_model(self, return_record: ReturnDB) -> ReturnModel:
        """Convert return DB object to Pydantic model."""
        return ReturnModel(
            id=return_record.id,
            checkout_id=return_record.checkout_id,
            patron_id=return_record.patron_id,
            book_isbn=return_record.book_isbn,
            return_date=return_record.return_date,
            condition=return_record.condition,
            late_days=return_record.late_days,
            fine_assessed=return_record.fine_assessed,
            fine_paid=return_record.fine_paid,
            notes=return_record.notes,
            processed_by=return_record.processed_by,
            created_at=return_record.created_at,
        )

    def _reservation_to_model(self, reservation: ReservationDB) -> ReservationModel:
        """Convert reservation DB object to Pydantic model."""
        return ReservationModel(
            id=reservation.id,
            patron_id=reservation.patron_id,
            book_isbn=reservation.book_isbn,
            reservation_date=reservation.reservation_date,
            expiration_date=reservation.expiration_date,
            notification_date=reservation.notification_date,
            pickup_deadline=reservation.pickup_deadline,
            status=ReservationStatus(reservation.status.value),
            queue_position=reservation.queue_position,
            notes=reservation.notes,
            created_at=reservation.created_at,
            updated_at=reservation.updated_at,
        )

    def _paginate_checkouts(self, query, pagination: PaginationParams | None):
        """Helper to paginate checkout queries."""
        if not pagination:
            pagination = PaginationParams()

        pagination.validate_params()

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = (
            mcp_safe_query(
                self.session,
                lambda s: s.execute(count_query).scalar(),
                "Failed to count total for pagination",
            )
            or 0
        )

        # Apply pagination
        query = query.offset(pagination.offset).limit(pagination.page_size)
        results = mcp_safe_query(
            self.session,
            lambda s: s.execute(query).unique().scalars().all(),
            "Failed to get paginated checkouts",
        )

        items = [self._checkout_to_model(item) for item in results]

        return PaginatedResponse(
            items=items,
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            total_pages=(total + pagination.page_size - 1) // pagination.page_size,
            has_next=pagination.page * pagination.page_size < total,
            has_previous=pagination.page > 1,
        )
