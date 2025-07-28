"""
Patron model for the Virtual Library MCP Server.

This model represents a library patron (member) who can borrow books. In the MCP
architecture, patrons will be exposed as resources and their actions (checkout,
return, reserve) will be implemented as tools (functions with side effects).

Patron resources can be accessed via:
- library://patrons/list
- library://patrons/{patron_id}
"""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class PatronStatus(str, Enum):
    """Enumeration of possible patron statuses."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    PENDING = "pending"


class Patron(BaseModel):
    """
    Represents a library patron who can borrow books.

    Patrons have borrowing limits and status tracking to ensure library
    policies are enforced. This model integrates with circulation records
    to track checkouts, returns, and reservations.
    """

    id: str = Field(
        ...,
        description="Unique identifier for the patron",
        pattern=r"^patron_[a-zA-Z0-9_]{6,}$",
        examples=["patron_smith001", "patron_doe_jane"],
    )

    name: str = Field(
        ...,
        description="Full name of the patron",
        min_length=2,
        max_length=200,
        examples=["John Smith", "Jane Doe", "Maria Garcia"],
    )

    email: EmailStr = Field(
        ...,
        description="Email address for patron notifications",
        examples=["john.smith@example.com", "jane.doe@library.org"],
    )

    phone: str | None = Field(
        None,
        description="Phone number for urgent notifications",
        pattern=r"^\+?[\d\s\-\(\)]+$",
        examples=["+1234567890", "555-123-4567"],
    )

    address: str | None = Field(
        None,
        description="Mailing address for the patron",
        max_length=500,
        examples=["123 Main St, Anytown, ST 12345"],
    )

    membership_date: date = Field(
        ...,
        description="Date when the patron joined the library",
        examples=["2023-01-15", "2024-03-20"],
    )

    expiration_date: date | None = Field(
        None,
        description="Date when the membership expires",
        examples=["2024-01-15", "2025-03-20"],
    )

    status: PatronStatus = Field(
        default=PatronStatus.ACTIVE,
        description="Current status of the patron's membership",
    )

    borrowing_limit: int = Field(
        default=5,
        description="Maximum number of books the patron can borrow at once",
        ge=0,
        le=20,
        examples=[5, 10, 3],
    )

    current_checkouts: int = Field(
        default=0,
        description="Number of books currently checked out by the patron",
        ge=0,
        examples=[0, 3, 5],
    )

    total_checkouts: int = Field(
        default=0,
        description="Total number of books ever checked out by the patron",
        ge=0,
        examples=[0, 50, 200],
    )

    outstanding_fines: float = Field(
        default=0.0,
        description="Amount of unpaid fines in dollars",
        ge=0.0,
        examples=[0.0, 5.50, 12.75],
    )

    # Preferences
    preferred_genres: list[str] = Field(
        default_factory=list,
        description="List of preferred book genres for recommendations",
        examples=[["Fiction", "Mystery"], ["Non-Fiction", "Biography"]],
    )

    notification_preferences: dict[str, bool] = Field(
        default_factory=lambda: {
            "email": True,
            "sms": False,
            "due_date_reminder": True,
            "new_arrivals": False,
        },
        description="Notification preferences for various alerts",
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the patron was added to the system",
    )

    updated_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the patron record was last updated",
    )

    last_activity: datetime | None = Field(
        None,
        description="Timestamp of the patron's last library activity",
    )

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: str | None) -> str | None:
        """Normalize phone number by removing common formatting."""
        if v is None:
            return v
        # Remove common formatting characters including +
        return (
            v.replace("-", "").replace(" ", "").replace("(", "").replace(")", "").replace("+", "")
        )

    @field_validator("membership_date")
    @classmethod
    def validate_membership_date(cls, v: date) -> date:
        """Validate membership date is not in the future."""
        if v > date.today():
            raise ValueError("Membership date cannot be in the future")
        return v

    @field_validator("current_checkouts")
    @classmethod
    def validate_current_checkouts(cls, v: int) -> int:
        """Validate current checkouts is non-negative."""
        # Just validate the value itself here
        return v

    @field_validator("preferred_genres")
    @classmethod
    def normalize_genres(cls, v: list[str]) -> list[str]:
        """Normalize genres to title case and remove duplicates."""
        normalized = [genre.strip().title() for genre in v]
        return list(dict.fromkeys(normalized))  # Remove duplicates while preserving order

    @model_validator(mode="after")
    def validate_dates_and_checkouts(self) -> "Patron":
        """Validate relationships between fields."""
        # Validate expiration date is after membership date
        if self.expiration_date and self.expiration_date <= self.membership_date:
            raise ValueError("Expiration date must be after membership date")

        # Validate current checkouts doesn't exceed borrowing limit
        if self.current_checkouts > self.borrowing_limit:
            raise ValueError("Current checkouts cannot exceed borrowing limit")

        return self

    @property
    def is_active(self) -> bool:
        """Check if the patron's membership is currently active."""
        if self.status != PatronStatus.ACTIVE:
            return False

        return not (self.expiration_date and self.expiration_date < date.today())

    @property
    def can_checkout(self) -> bool:
        """Check if the patron can checkout more books."""
        return (
            self.is_active
            and self.current_checkouts < self.borrowing_limit
            and self.outstanding_fines < 10.0  # Block checkouts if fines exceed $10
        )

    @property
    def available_checkouts(self) -> int:
        """Calculate how many more books the patron can checkout."""
        if not self.is_active:
            return 0
        return max(0, self.borrowing_limit - self.current_checkouts)

    @property
    def membership_duration_days(self) -> int:
        """Calculate how long the patron has been a member."""
        return (date.today() - self.membership_date).days

    def checkout_book(self) -> None:
        """
        Record a book checkout for the patron.

        Raises:
            ValueError: If the patron cannot checkout books
        """
        if not self.can_checkout:
            if not self.is_active:
                raise ValueError("Patron membership is not active")
            if self.current_checkouts >= self.borrowing_limit:
                raise ValueError(f"Borrowing limit of {self.borrowing_limit} reached")
            raise ValueError("Outstanding fines exceed $10.00")

        self.current_checkouts += 1
        self.total_checkouts += 1
        self.last_activity = datetime.now()
        self.updated_at = datetime.now()

    def return_book(self) -> None:
        """
        Record a book return for the patron.

        Raises:
            ValueError: If the patron has no books to return
        """
        if self.current_checkouts <= 0:
            raise ValueError("No books to return")

        self.current_checkouts -= 1
        self.last_activity = datetime.now()
        self.updated_at = datetime.now()

    def add_fine(self, amount: float) -> None:
        """Add a fine to the patron's account."""
        if amount < 0:
            raise ValueError("Fine amount must be positive")
        self.outstanding_fines += amount
        self.updated_at = datetime.now()

    def pay_fine(self, amount: float) -> None:
        """
        Record a fine payment.

        Args:
            amount: Amount to pay

        Raises:
            ValueError: If payment amount is invalid
        """
        if amount < 0:
            raise ValueError("Payment amount must be positive")
        if amount > self.outstanding_fines:
            raise ValueError("Payment exceeds outstanding fines")

        self.outstanding_fines -= amount
        self.updated_at = datetime.now()

    def renew_membership(self, years: int = 1) -> None:
        """Renew the patron's membership."""
        if years < 1:
            raise ValueError("Renewal period must be at least 1 year")

        if self.expiration_date is None or self.expiration_date < date.today():
            # If expired or no expiration, renew from today
            self.expiration_date = date.today().replace(year=date.today().year + years)
        else:
            # Extend from current expiration
            self.expiration_date = self.expiration_date.replace(
                year=self.expiration_date.year + years
            )

        self.status = PatronStatus.ACTIVE
        self.updated_at = datetime.now()

    model_config = ConfigDict(
        # Validate field values on assignment (critical for MCP real-time validation)
        validate_assignment=True,
        # Use Enum values instead of names (PatronStatus.ACTIVE = "active" not "ACTIVE")
        use_enum_values=True,
        # Populate models by field name (required for MCP JSON-RPC compatibility)
        populate_by_name=True,
        # Validate default values (ensures MCP resource consistency)
        validate_default=True,
        # Generate JSON schema with examples for MCP introspection
        json_schema_extra={
            "example": {
                "id": "patron_smith001",
                "name": "John Smith",
                "email": "john.smith@example.com",
                "phone": "+1234567890",
                "address": "123 Main St, Anytown, ST 12345",
                "membership_date": "2023-01-15",
                "expiration_date": "2024-01-15",
                "status": "active",
                "borrowing_limit": 5,
                "current_checkouts": 2,
                "total_checkouts": 45,
                "outstanding_fines": 0.0,
                "preferred_genres": ["Fiction", "Mystery"],
                "notification_preferences": {
                    "email": True,
                    "sms": False,
                    "due_date_reminder": True,
                    "new_arrivals": False,
                },
            }
        },
        # Forbid extra fields to ensure strict MCP message validation
        extra="forbid",
        # Use Python's standard string representation
        str_strip_whitespace=True,
    )
