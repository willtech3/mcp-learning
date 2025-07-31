"""
Circulation models for the Virtual Library MCP Server.

These models represent the circulation of books in the library system:
- CheckoutRecord: When a patron borrows a book
- ReturnRecord: When a patron returns a book
- ReservationRecord: When a patron reserves a book

In the MCP architecture, these models support tools (functions with side effects)
that modify the library state, such as:
- checkout_book: Creates a CheckoutRecord and updates book availability
- return_book: Creates a ReturnRecord and updates book availability
- reserve_book: Creates a ReservationRecord for unavailable books
"""

from datetime import date, datetime, timedelta
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CirculationStatus(str, Enum):
    """Status of a circulation record."""

    ACTIVE = "active"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    LOST = "lost"


class ReservationStatus(str, Enum):
    """Status of a reservation."""

    PENDING = "pending"
    AVAILABLE = "available"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class CheckoutRecord(BaseModel):
    """
    Represents a book checkout transaction.

    This record is created when a patron borrows a book and tracks
    the loan period, due dates, and any associated fines.
    """

    id: str = Field(
        ...,
        description="Unique identifier for the checkout record",
        pattern=r"^checkout_[a-zA-Z0-9]{6,}$",
        examples=["checkout_202312150001", "checkout_202403201234"],
    )

    patron_id: str = Field(
        ...,
        description="ID of the patron who checked out the book",
        pattern=r"^patron_[a-zA-Z0-9_]{6,}$",
        examples=["patron_smith001", "patron_doe_jane"],
    )

    book_isbn: str = Field(
        ...,
        description="ISBN of the checked out book",
        pattern=r"^\d{13}$",
        examples=["9780134685479", "9780061120084"],
    )

    checkout_date: datetime = Field(
        default_factory=datetime.now,
        description="Date and time when the book was checked out",
    )

    due_date: date = Field(
        ...,
        description="Date when the book should be returned",
        examples=["2024-01-01", "2024-02-15"],
    )

    return_date: datetime | None = Field(
        None,
        description="Actual date and time when the book was returned",
    )

    status: CirculationStatus = Field(
        default=CirculationStatus.ACTIVE,
        description="Current status of the checkout",
    )

    renewal_count: int = Field(
        default=0,
        description="Number of times this checkout has been renewed",
        ge=0,
        le=3,  # Maximum 3 renewals allowed
    )

    fine_amount: float = Field(
        default=0.0,
        description="Accumulated fine for this checkout",
        ge=0.0,
    )

    fine_paid: bool = Field(
        default=False,
        description="Whether the fine has been paid",
    )

    notes: str | None = Field(
        None,
        description="Additional notes about this checkout",
        max_length=1000,
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="When this record was created",
    )

    updated_at: datetime = Field(
        default_factory=datetime.now,
        description="When this record was last updated",
    )

    @model_validator(mode="after")
    def validate_dates(self) -> "CheckoutRecord":
        """Validate date relationships."""
        # Skip validation for completed checkouts (they may have been modified for testing/historical data)
        if self.status == CirculationStatus.COMPLETED:
            return self

        # Ensure due date is after checkout date for active checkouts
        if self.due_date <= self.checkout_date.date():
            raise ValueError("Due date must be after checkout date")

        # Ensure return date is after checkout date
        if self.return_date and self.return_date < self.checkout_date:
            raise ValueError("Return date cannot be before checkout date")

        return self

    @property
    def is_overdue(self) -> bool:
        """Check if the checkout is overdue."""
        if self.status == CirculationStatus.COMPLETED:
            return False
        return date.today() > self.due_date

    @property
    def days_overdue(self) -> int:
        """Calculate number of days overdue."""
        if not self.is_overdue:
            return 0
        return (date.today() - self.due_date).days

    @property
    def loan_period_days(self) -> int:
        """Calculate the loan period in days."""
        return (self.due_date - self.checkout_date.date()).days

    def calculate_fine(self, daily_rate: float = 0.25) -> float:
        """
        Calculate fine based on overdue days.

        Args:
            daily_rate: Fine amount per day (default $0.25)

        Returns:
            Total fine amount
        """
        if not self.is_overdue:
            return 0.0

        # Use return date if book was returned, otherwise use today
        end_date = self.return_date.date() if self.return_date else date.today()
        overdue_days = (end_date - self.due_date).days

        return max(0, overdue_days * daily_rate)

    def renew(self, extension_days: int = 14) -> None:
        """
        Renew the checkout for additional days.

        Args:
            extension_days: Number of days to extend (default 14)

        Raises:
            ValueError: If renewal limit reached or book is overdue
        """
        if self.renewal_count >= 3:
            raise ValueError("Maximum renewal limit (3) reached")

        if self.is_overdue:
            raise ValueError("Cannot renew overdue items")

        if self.status != CirculationStatus.ACTIVE:
            raise ValueError("Can only renew active checkouts")

        self.due_date = self.due_date + timedelta(days=extension_days)
        self.renewal_count += 1
        self.updated_at = datetime.now()

    def complete_return(self) -> None:
        """Mark the checkout as returned."""
        if self.status == CirculationStatus.COMPLETED:
            raise ValueError("Checkout already completed")

        # Calculate fine before changing status
        self.return_date = datetime.now()
        self.fine_amount = self.calculate_fine()

        # Now mark as completed
        self.status = CirculationStatus.COMPLETED
        self.updated_at = datetime.now()

    model_config = ConfigDict(
        # Validate field values on assignment for real-time MCP tool validation
        validate_assignment=True,
        # Use string values for enums in JSON serialization
        use_enum_values=True,
        # Allow field population by name for flexible MCP client compatibility
        populate_by_name=True,
        # Validate default values for data integrity
        validate_default=True,
        # Provide examples for MCP introspection and documentation
        json_schema_extra={
            "example": {
                "id": "checkout_202312150001",
                "patron_id": "patron_smith001",
                "book_isbn": "9780134685479",
                "checkout_date": "2023-12-15T10:30:00",
                "due_date": "2023-12-29",
                "status": "active",
                "renewal_count": 0,
                "fine_amount": 0.0,
                "fine_paid": False,
            }
        },
    )


class ReturnRecord(BaseModel):
    """
    Represents a book return transaction.

    This record is created when a patron returns a book and captures
    the condition of the book and any associated fines or issues.
    """

    id: str = Field(
        ...,
        description="Unique identifier for the return record",
        pattern=r"^return_[a-zA-Z0-9]{6,}$",
        examples=["return_202312290001", "return_202403251234"],
    )

    checkout_id: str = Field(
        ...,
        description="ID of the associated checkout record",
        pattern=r"^checkout_[a-zA-Z0-9]{6,}$",
    )

    patron_id: str = Field(
        ...,
        description="ID of the patron returning the book",
        pattern=r"^patron_[a-zA-Z0-9_]{6,}$",
    )

    book_isbn: str = Field(
        ...,
        description="ISBN of the returned book",
        pattern=r"^\d{13}$",
    )

    return_date: datetime = Field(
        default_factory=datetime.now,
        description="Date and time when the book was returned",
    )

    condition: str = Field(
        default="good",
        description="Condition of the returned book",
        pattern=r"^(excellent|good|fair|damaged|lost)$",
    )

    late_days: int = Field(
        default=0,
        description="Number of days the return was late",
        ge=0,
    )

    fine_assessed: float = Field(
        default=0.0,
        description="Fine amount assessed for this return",
        ge=0.0,
    )

    fine_paid: float = Field(
        default=0.0,
        description="Amount of fine paid at return",
        ge=0.0,
    )

    notes: str | None = Field(
        None,
        description="Additional notes about the return",
        max_length=1000,
    )

    processed_by: str | None = Field(
        None,
        description="Staff member who processed the return",
    )

    created_at: datetime = Field(
        default_factory=datetime.now,
        description="When this record was created",
    )

    @model_validator(mode="after")
    def validate_fines(self) -> "ReturnRecord":
        """Ensure fine paid doesn't exceed fine assessed."""
        if self.fine_paid > self.fine_assessed:
            raise ValueError("Fine paid cannot exceed fine assessed")
        return self

    @property
    def fine_outstanding(self) -> float:
        """Calculate outstanding fine amount."""
        return max(0, self.fine_assessed - self.fine_paid)

    @property
    def is_damaged(self) -> bool:
        """Check if the book was returned damaged."""
        return self.condition in ["damaged", "lost"]

    model_config = ConfigDict(
        # Validate field values on assignment for MCP tool validation
        validate_assignment=True,
        # Use string values for enums (condition status)
        use_enum_values=True,
        # Allow flexible field naming for MCP clients
        populate_by_name=True,
        # Ensure default values are valid
        validate_default=True,
        # Example for MCP resource documentation
        json_schema_extra={
            "example": {
                "id": "return_202312290001",
                "checkout_id": "checkout_202312150001",
                "patron_id": "patron_smith001",
                "book_isbn": "9780134685479",
                "return_date": "2023-12-29T14:20:00",
                "condition": "good",
                "late_days": 0,
                "fine_assessed": 0.0,
                "fine_paid": 0.0,
            }
        },
    )


class ReservationRecord(BaseModel):
    """
    Represents a book reservation.

    This record is created when a patron reserves a book that is
    currently unavailable, placing them in a queue for the next copy.
    """

    id: str = Field(
        ...,
        description="Unique identifier for the reservation",
        pattern=r"^reservation_[a-zA-Z0-9]{6,}$",
        examples=["reservation_202312150001", "reservation_202403201234"],
    )

    patron_id: str = Field(
        ...,
        description="ID of the patron who made the reservation",
        pattern=r"^patron_[a-zA-Z0-9_]{6,}$",
    )

    book_isbn: str = Field(
        ...,
        description="ISBN of the reserved book",
        pattern=r"^\d{13}$",
    )

    reservation_date: datetime = Field(
        default_factory=datetime.now,
        description="Date and time when the reservation was made",
    )

    expiration_date: date = Field(
        ...,
        description="Date when the reservation expires",
    )

    notification_date: datetime | None = Field(
        None,
        description="Date when patron was notified of availability",
    )

    pickup_deadline: date | None = Field(
        None,
        description="Deadline for patron to pick up the reserved book",
    )

    status: ReservationStatus = Field(
        default=ReservationStatus.PENDING,
        description="Current status of the reservation",
    )

    queue_position: int = Field(
        ...,
        description="Position in the reservation queue",
        ge=1,
    )

    notes: str | None = Field(
        None,
        description="Additional notes about the reservation",
        max_length=1000,
    )

    created_at: datetime = Field(
        default_factory=datetime.now,
        description="When this record was created",
    )

    updated_at: datetime = Field(
        default_factory=datetime.now,
        description="When this record was last updated",
    )

    @model_validator(mode="after")
    def validate_dates(self) -> "ReservationRecord":
        """Validate date relationships."""
        # Ensure expiration date is after reservation date
        if self.expiration_date <= self.reservation_date.date():
            raise ValueError("Expiration date must be after reservation date")

        # Ensure pickup deadline is after notification date
        if (
            self.pickup_deadline
            and self.notification_date
            and self.pickup_deadline <= self.notification_date.date()
        ):
            raise ValueError("Pickup deadline must be after notification date")

        return self

    @property
    def is_expired(self) -> bool:
        """Check if the reservation has expired."""
        if self.status in [ReservationStatus.FULFILLED, ReservationStatus.CANCELLED]:
            return False

        # Check pickup deadline if book is available
        if self.status == ReservationStatus.AVAILABLE and self.pickup_deadline:
            return date.today() > self.pickup_deadline

        # Check general expiration
        return date.today() > self.expiration_date

    @property
    def days_until_expiration(self) -> int:
        """Calculate days until reservation expires."""
        if self.is_expired:
            return 0

        if self.status == ReservationStatus.AVAILABLE and self.pickup_deadline:
            return (self.pickup_deadline - date.today()).days

        return (self.expiration_date - date.today()).days

    def notify_available(self, pickup_days: int = 3) -> None:
        """
        Notify patron that the book is available.

        Args:
            pickup_days: Number of days to pick up the book
        """
        if self.status != ReservationStatus.PENDING:
            raise ValueError("Can only notify for pending reservations")

        self.status = ReservationStatus.AVAILABLE
        self.notification_date = datetime.now()
        self.pickup_deadline = date.today() + timedelta(days=pickup_days)
        self.updated_at = datetime.now()

    def fulfill(self) -> None:
        """Mark the reservation as fulfilled."""
        if self.status != ReservationStatus.AVAILABLE:
            raise ValueError("Can only fulfill available reservations")

        self.status = ReservationStatus.FULFILLED
        self.updated_at = datetime.now()

    def cancel(self) -> None:
        """Cancel the reservation."""
        if self.status in [ReservationStatus.FULFILLED, ReservationStatus.CANCELLED]:
            raise ValueError("Cannot cancel completed reservations")

        self.status = ReservationStatus.CANCELLED
        self.updated_at = datetime.now()

    model_config = ConfigDict(
        # Validate field values on assignment for MCP reservation tools
        validate_assignment=True,
        # Use string values for ReservationStatus enum
        use_enum_values=True,
        # Support various field naming conventions from MCP clients
        populate_by_name=True,
        # Validate defaults to ensure data integrity
        validate_default=True,
        # Example for MCP resource introspection
        json_schema_extra={
            "example": {
                "id": "reservation_202312150001",
                "patron_id": "patron_smith001",
                "book_isbn": "9780134685479",
                "reservation_date": "2023-12-15T10:30:00",
                "expiration_date": "2024-01-15",
                "status": "pending",
                "queue_position": 1,
            }
        },
    )
