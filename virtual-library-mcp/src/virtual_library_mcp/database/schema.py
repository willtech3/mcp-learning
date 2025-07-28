"""
SQLAlchemy database schema for the Virtual Library MCP Server.

This module defines the database tables that mirror our Pydantic models.
In the MCP architecture, these tables serve as the persistent storage layer
that backs our resources (read-only endpoints) and tools (operations with side effects).

Key MCP Integration Points:
1. Resources will query these tables to expose data via URIs
2. Tools will modify these tables to implement library operations
3. Subscriptions will monitor these tables for real-time updates
4. The schema supports all MCP protocol features through proper relationships
"""

import enum
from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import declarative_base, relationship, validates
from sqlalchemy.sql import func

# Base class for all SQLAlchemy models
# This provides common functionality like __tablename__ generation
Base = declarative_base()


# Python Enums for use with SQLAlchemy
class PatronStatusEnum(str, enum.Enum):
    """Database enum for patron status."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    PENDING = "pending"


class CirculationStatusEnum(str, enum.Enum):
    """Database enum for circulation status."""

    ACTIVE = "active"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    LOST = "lost"


class ReservationStatusEnum(str, enum.Enum):
    """Database enum for reservation status."""

    PENDING = "pending"
    AVAILABLE = "available"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class Author(Base):
    """
    Authors table - stores information about book authors.

    MCP Usage:
    - Resource: library://authors/list, library://authors/{id}
    - Relationships: One-to-many with books
    - Subscriptions: Changes trigger updates for author resources
    """

    __tablename__ = "authors"

    # Primary key matching Pydantic model pattern
    id = Column(String(50), primary_key=True)
    name = Column(String(200), nullable=False, index=True)
    biography = Column(Text, nullable=True)
    birth_date = Column(Date, nullable=True)
    death_date = Column(Date, nullable=True)
    nationality = Column(String(100), nullable=True)
    photo_url = Column(String(500), nullable=True)
    website = Column(String(500), nullable=True)

    # Timestamps for tracking changes (important for subscriptions)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # Relationships
    books = relationship("Book", back_populates="author", cascade="all, delete-orphan")

    # Indexes for efficient querying
    __table_args__ = (
        Index("idx_author_name", "name"),
        Index("idx_author_nationality", "nationality"),
        CheckConstraint("id LIKE 'author_%'", name="check_author_id_format"),
    )

    @validates("death_date")
    def validate_death_date(self, key, value):  # noqa: ARG002
        """Ensure death date is after birth date."""
        if value and self.birth_date and value < self.birth_date:
            raise ValueError("Death date cannot be before birth date")
        return value

    @property
    def is_living(self) -> bool:
        """Check if the author is still living."""
        return self.death_date is None


class Book(Base):
    """
    Books table - stores the library's book catalog.

    MCP Usage:
    - Resource: library://books/list, library://books/{isbn}
    - Tools: checkout_book, return_book, reserve_book modify this table
    - Subscriptions: Availability changes trigger real-time updates
    - Critical for demonstrating MCP's resource/tool separation
    """

    __tablename__ = "books"

    # ISBN as primary key (normalized without hyphens)
    isbn = Column(String(13), primary_key=True)
    title = Column(String(500), nullable=False, index=True)
    author_id = Column(String(50), ForeignKey("authors.id"), nullable=False)
    genre = Column(String(100), nullable=False, index=True)
    publication_year = Column(Integer, nullable=False)
    available_copies = Column(Integer, nullable=False, default=1)
    total_copies = Column(Integer, nullable=False)
    description = Column(Text, nullable=True)
    cover_url = Column(String(500), nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=True, default=func.now(), onupdate=func.now())

    # Relationships
    author = relationship("Author", back_populates="books")
    checkouts = relationship("CheckoutRecord", back_populates="book")
    reservations = relationship("ReservationRecord", back_populates="book")

    # Indexes for common query patterns in MCP resources
    __table_args__ = (
        Index("idx_book_title", "title"),
        Index("idx_book_genre", "genre"),
        Index("idx_book_author", "author_id"),
        Index("idx_book_availability", "available_copies"),
        CheckConstraint("available_copies >= 0", name="check_available_copies_non_negative"),
        CheckConstraint(
            "available_copies <= total_copies", name="check_available_not_exceed_total"
        ),
        CheckConstraint("total_copies > 0", name="check_total_copies_positive"),
        CheckConstraint("publication_year >= 1450", name="check_publication_year_valid"),
    )


class Patron(Base):
    """
    Patrons table - stores library member information.

    MCP Usage:
    - Resource: library://patrons/list, library://patrons/{id}
    - Tools: Operations like checkout/return are patron-specific
    - Privacy: MCP servers must respect data privacy in resources
    - Demonstrates user-specific state management in MCP
    """

    __tablename__ = "patrons"

    # Primary key
    id = Column(String(50), primary_key=True)
    name = Column(String(200), nullable=False, index=True)
    email = Column(String(255), nullable=False, unique=True)
    phone = Column(String(20), nullable=True)
    address = Column(String(500), nullable=True)
    membership_date = Column(Date, nullable=False)
    expiration_date = Column(Date, nullable=True)
    status = Column(Enum(PatronStatusEnum), nullable=False, default=PatronStatusEnum.ACTIVE)
    borrowing_limit = Column(Integer, nullable=False, default=5)
    current_checkouts = Column(Integer, nullable=False, default=0)
    total_checkouts = Column(Integer, nullable=False, default=0)
    outstanding_fines = Column(Float, nullable=False, default=0.0)

    # JSON field for preferences (demonstrates complex data in MCP)
    # Note: Using Text + JSON serialization for SQLite compatibility
    preferred_genres = Column(Text, nullable=True)  # JSON array
    notification_preferences = Column(Text, nullable=True)  # JSON object

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    last_activity = Column(DateTime, nullable=True)

    # Relationships
    checkouts = relationship("CheckoutRecord", back_populates="patron")
    returns = relationship("ReturnRecord", back_populates="patron")
    reservations = relationship("ReservationRecord", back_populates="patron")

    # Indexes and constraints
    __table_args__ = (
        Index("idx_patron_email", "email"),
        Index("idx_patron_status", "status"),
        CheckConstraint("id LIKE 'patron_%'", name="check_patron_id_format"),
        CheckConstraint("borrowing_limit >= 0", name="check_borrowing_limit_non_negative"),
        CheckConstraint("current_checkouts >= 0", name="check_current_checkouts_non_negative"),
        CheckConstraint("outstanding_fines >= 0", name="check_fines_non_negative"),
    )

    @property
    def is_active(self) -> bool:
        """Check if the patron's membership is currently active."""
        if self.status != PatronStatusEnum.ACTIVE:
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


class CheckoutRecord(Base):
    """
    Checkout records table - tracks book loans.

    MCP Usage:
    - Resource: library://checkouts/active, library://checkouts/history
    - Tools: checkout_book creates records, return_book updates them
    - Progress: Long operations (bulk checkouts) report progress
    - Demonstrates stateful operations in MCP servers
    """

    __tablename__ = "checkout_records"

    # Primary key
    id = Column(String(50), primary_key=True)
    patron_id = Column(String(50), ForeignKey("patrons.id"), nullable=False)
    book_isbn = Column(String(13), ForeignKey("books.isbn"), nullable=False)
    checkout_date = Column(DateTime, nullable=False, default=func.now())
    due_date = Column(Date, nullable=False)
    return_date = Column(DateTime, nullable=True)
    status = Column(
        Enum(CirculationStatusEnum), nullable=False, default=CirculationStatusEnum.ACTIVE
    )
    renewal_count = Column(Integer, nullable=False, default=0)
    fine_amount = Column(Float, nullable=False, default=0.0)
    fine_paid = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # Relationships
    patron = relationship("Patron", back_populates="checkouts")
    book = relationship("Book", back_populates="checkouts")
    return_record = relationship("ReturnRecord", back_populates="checkout", uselist=False)

    # Indexes for common queries
    __table_args__ = (
        Index("idx_checkout_patron", "patron_id"),
        Index("idx_checkout_book", "book_isbn"),
        Index("idx_checkout_status", "status"),
        Index("idx_checkout_due_date", "due_date"),
        CheckConstraint("id LIKE 'checkout_%'", name="check_checkout_id_format"),
        CheckConstraint("renewal_count >= 0 AND renewal_count <= 3", name="check_renewal_limit"),
        CheckConstraint("fine_amount >= 0", name="check_fine_non_negative"),
    )


class ReturnRecord(Base):
    """
    Return records table - tracks book returns.

    MCP Usage:
    - Resource: library://returns/recent
    - Tools: return_book creates these records
    - Auditing: Immutable records for compliance
    - Shows how MCP servers can maintain audit trails
    """

    __tablename__ = "return_records"

    # Primary key
    id = Column(String(50), primary_key=True)
    checkout_id = Column(String(50), ForeignKey("checkout_records.id"), nullable=False)
    patron_id = Column(String(50), ForeignKey("patrons.id"), nullable=False)
    book_isbn = Column(String(13), nullable=False)
    return_date = Column(DateTime, nullable=False, default=func.now())
    condition = Column(String(20), nullable=False, default="good")
    late_days = Column(Integer, nullable=False, default=0)
    fine_assessed = Column(Float, nullable=False, default=0.0)
    fine_paid = Column(Float, nullable=False, default=0.0)
    notes = Column(Text, nullable=True)
    processed_by = Column(String(100), nullable=True)

    # Timestamp (no updated_at as returns are immutable)
    created_at = Column(DateTime, nullable=False, default=func.now())

    # Relationships
    checkout = relationship("CheckoutRecord", back_populates="return_record")
    patron = relationship("Patron", back_populates="returns")

    # Indexes
    __table_args__ = (
        Index("idx_return_patron", "patron_id"),
        Index("idx_return_date", "return_date"),
        CheckConstraint("id LIKE 'return_%'", name="check_return_id_format"),
        CheckConstraint("late_days >= 0", name="check_late_days_non_negative"),
        CheckConstraint("fine_paid <= fine_assessed", name="check_fine_paid_not_exceed_assessed"),
    )


class ReservationRecord(Base):
    """
    Reservation records table - tracks book holds.

    MCP Usage:
    - Resource: library://reservations/queue
    - Tools: reserve_book creates, fulfill_reservation updates
    - Subscriptions: Queue position changes trigger notifications
    - Demonstrates real-time state updates in MCP
    """

    __tablename__ = "reservation_records"

    # Primary key
    id = Column(String(50), primary_key=True)
    patron_id = Column(String(50), ForeignKey("patrons.id"), nullable=False)
    book_isbn = Column(String(13), ForeignKey("books.isbn"), nullable=False)
    reservation_date = Column(DateTime, nullable=False, default=func.now())
    expiration_date = Column(Date, nullable=False)
    notification_date = Column(DateTime, nullable=True)
    pickup_deadline = Column(Date, nullable=True)
    status = Column(
        Enum(ReservationStatusEnum), nullable=False, default=ReservationStatusEnum.PENDING
    )
    queue_position = Column(Integer, nullable=False)
    notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # Relationships
    patron = relationship("Patron", back_populates="reservations")
    book = relationship("Book", back_populates="reservations")

    # Indexes and constraints
    __table_args__ = (
        Index("idx_reservation_patron", "patron_id"),
        Index("idx_reservation_book", "book_isbn"),
        Index("idx_reservation_status", "status"),
        Index("idx_reservation_queue", "book_isbn", "queue_position"),
        UniqueConstraint("book_isbn", "queue_position", name="unique_queue_position"),
        CheckConstraint("id LIKE 'reservation_%'", name="check_reservation_id_format"),
        CheckConstraint("queue_position > 0", name="check_queue_position_positive"),
    )


# Database event listeners for MCP integration
@event.listens_for(Book, "after_update")
def book_after_update(mapper, connection, target):  # noqa: ARG001
    """
    Event listener for book updates - triggers MCP subscriptions.

    In a full MCP implementation, this would:
    1. Check if available_copies changed
    2. Notify subscribed clients via the subscription system
    3. Update any cached resource representations
    """
    # This is where we'd integrate with the MCP subscription system
    # to notify clients of availability changes
    pass


@event.listens_for(ReservationRecord, "after_insert")
@event.listens_for(ReservationRecord, "after_update")
def reservation_queue_update(mapper, connection, target):  # noqa: ARG001
    """
    Event listener for reservation changes - manages queue positions.

    This demonstrates how MCP servers can maintain complex state
    that requires coordination across multiple records.
    """
    # Queue management logic would go here
    pass
