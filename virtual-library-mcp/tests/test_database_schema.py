"""
Tests for database schema and session management.

These tests verify:
1. Database tables are created correctly
2. Relationships work as expected
3. Constraints are enforced
4. Session management works properly
"""

from datetime import date, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from virtual_library_mcp.database import (
    Author,
    Book,
    CheckoutRecord,
    CirculationStatusEnum,
    Patron,
    PatronStatusEnum,
    get_db_manager,
    session_scope,
)


@pytest.fixture
def db_manager():
    """Create a test database manager with in-memory SQLite."""
    manager = get_db_manager("sqlite:///:memory:")
    manager.init_database()
    yield manager
    manager.close()


@pytest.fixture
def session(db_manager):
    """Provide a database session for tests."""
    with db_manager.session_scope() as session:
        yield session


class TestDatabaseSchema:
    """Test database schema creation and basic operations."""

    def test_tables_created(self, session):
        """Verify all expected tables are created."""
        from sqlalchemy import inspect  # noqa: PLC0415 - Test-specific import

        inspector = inspect(session.bind)
        tables = inspector.get_table_names()

        expected_tables = {
            "authors",
            "books",
            "patrons",
            "checkout_records",
            "return_records",
            "reservation_records",
        }

        assert set(tables) == expected_tables

    def test_author_creation(self, session):
        """Test creating an author."""
        author = Author(
            id="author_test001",
            name="Test Author",
            biography="A test author for unit tests",
            birth_date=date(1950, 1, 1),
            nationality="American",
        )

        session.add(author)
        session.commit()

        # Verify author was saved
        saved_author = session.query(Author).filter_by(id="author_test001").first()
        assert saved_author is not None
        assert saved_author.name == "Test Author"
        assert saved_author.is_living is True

    def test_book_creation(self, session):
        """Test creating a book with author relationship."""
        # Create author first
        author = Author(
            id="author_test002",
            name="Book Test Author",
        )
        session.add(author)
        session.flush()

        # Create book
        book = Book(
            isbn="9781234567890",
            title="Test Book",
            author_id="author_test002",
            genre="Fiction",
            publication_year=2024,
            available_copies=3,
            total_copies=3,
        )

        session.add(book)
        session.commit()

        # Verify book and relationship
        saved_book = session.query(Book).filter_by(isbn="9781234567890").first()
        assert saved_book is not None
        assert saved_book.title == "Test Book"
        assert saved_book.author.name == "Book Test Author"

    def test_patron_creation(self, session):
        """Test creating a patron."""
        patron = Patron(
            id="patron_test001",
            name="Test Patron",
            email="test.patron@example.com",
            membership_date=date.today(),
            status=PatronStatusEnum.ACTIVE,
        )

        session.add(patron)
        session.commit()

        # Verify patron
        saved_patron = session.query(Patron).filter_by(id="patron_test001").first()
        assert saved_patron is not None
        assert saved_patron.is_active is True
        assert saved_patron.can_checkout is True

    def test_checkout_record_creation(self, session):
        """Test creating a checkout record with relationships."""
        # Create prerequisite data
        author = Author(id="author_checkout", name="Checkout Author")
        book = Book(
            isbn="9780000000001",
            title="Checkout Book",
            author_id="author_checkout",
            genre="Fiction",
            publication_year=2024,
            available_copies=1,
            total_copies=1,
        )
        patron = Patron(
            id="patron_checkout",
            name="Checkout Patron",
            email="checkout@example.com",
            membership_date=date.today(),
        )

        session.add_all([author, book, patron])
        session.flush()

        # Create checkout
        checkout = CheckoutRecord(
            id="checkout_test001",
            patron_id="patron_checkout",
            book_isbn="9780000000001",
            due_date=date.today() + timedelta(days=14),
        )

        session.add(checkout)
        session.commit()

        # Verify checkout and relationships
        saved_checkout = session.query(CheckoutRecord).filter_by(id="checkout_test001").first()
        assert saved_checkout is not None
        assert saved_checkout.patron.name == "Checkout Patron"
        assert saved_checkout.book.title == "Checkout Book"
        assert saved_checkout.status == CirculationStatusEnum.ACTIVE

    def test_constraint_enforcement(self, db_manager):
        """Test that database constraints are properly enforced."""
        # Test unique constraint on patron email
        with db_manager.session_scope() as session:
            patron1 = Patron(
                id="patron_unique1",
                name="Patron 1",
                email="duplicate@example.com",
                membership_date=date.today(),
            )
            session.add(patron1)

        # Try to add duplicate email in new session
        # PT012: This test needs to setup data within the session before triggering the constraint.
        # The setup is integral to the test logic and extracting it would reduce clarity.
        with pytest.raises(IntegrityError), db_manager.session_scope() as session:  # noqa: PT012
            patron2 = Patron(
                id="patron_unique2",
                name="Patron 2",
                email="duplicate@example.com",  # Duplicate email
                membership_date=date.today(),
            )
            session.add(patron2)

        # Test check constraint on book copies in new session
        # PT012: This test requires creating an author first, then a book with invalid data.
        # The multi-step setup within the session context is necessary to test the constraint.
        with pytest.raises(IntegrityError), db_manager.session_scope() as session:  # noqa: PT012
            # First create the author
            author = Author(id="author_constraint", name="Constraint Test Author")
            session.add(author)
            session.flush()

            book = Book(
                isbn="9789999999999",
                title="Invalid Book",
                author_id="author_constraint",
                genre="Fiction",
                publication_year=2024,
                available_copies=5,  # More than total!
                total_copies=3,
            )
            session.add(book)


class TestSessionManagement:
    """Test database session management utilities."""

    def test_session_scope_commit(self, db_manager):
        """Test that session_scope commits on success."""
        with session_scope() as session:
            author = Author(
                id="author_session001",
                name="Session Test Author",
            )
            session.add(author)

        # Verify in new session that commit happened
        with session_scope() as session:
            author = session.query(Author).filter_by(id="author_session001").first()
            assert author is not None

    def test_session_scope_rollback(self, db_manager):
        """Test that session_scope rolls back on error."""
        try:
            with session_scope() as session:
                author = Author(
                    id="author_rollback",
                    name="Rollback Author",
                )
                session.add(author)
                # Force an error
                # TRY301: This raise is intentional - we're testing rollback behavior
                # when an exception occurs within a transaction context.
                raise ValueError("Test error")
        except ValueError:
            pass

        # Verify rollback happened
        with session_scope() as session:
            author = session.query(Author).filter_by(id="author_rollback").first()
            assert author is None

    def test_multiple_sessions(self, db_manager):
        """Test that multiple sessions work correctly."""
        # Create in one session
        with session_scope() as session1:
            author = Author(id="author_multi", name="Multi Session")
            session1.add(author)

        # Read in another session
        with session_scope() as session2:
            author = session2.query(Author).filter_by(id="author_multi").first()
            assert author is not None
            assert author.name == "Multi Session"


class TestEnumHandling:
    """Test that enums are properly handled in the database."""

    def test_patron_status_enum(self, session):
        """Test PatronStatus enum values."""
        patron = Patron(
            id="patron_enum",
            name="Enum Test",
            email="enum@example.com",
            membership_date=date.today(),
            status=PatronStatusEnum.SUSPENDED,
        )

        session.add(patron)
        session.commit()

        # Verify enum is stored and retrieved correctly
        saved = session.query(Patron).filter_by(id="patron_enum").first()
        assert saved.status == PatronStatusEnum.SUSPENDED
        assert saved.status.value == "suspended"

    def test_circulation_status_enum(self, session):
        """Test CirculationStatus enum values."""
        # Create prerequisites
        author = Author(id="author_enum", name="Enum Author")
        book = Book(
            isbn="9788888888888",
            title="Enum Book",
            author_id="author_enum",
            genre="Fiction",
            publication_year=2024,
            total_copies=1,
        )
        patron = Patron(
            id="patron_circ_enum",
            name="Circ Enum",
            email="circ@example.com",
            membership_date=date.today(),
        )

        session.add_all([author, book, patron])
        session.flush()

        # Create checkout with specific status
        checkout = CheckoutRecord(
            id="checkout_enum",
            patron_id="patron_circ_enum",
            book_isbn="9788888888888",
            due_date=date.today() + timedelta(days=7),
            status=CirculationStatusEnum.OVERDUE,
        )

        session.add(checkout)
        session.commit()

        # Verify
        saved = session.query(CheckoutRecord).filter_by(id="checkout_enum").first()
        assert saved.status == CirculationStatusEnum.OVERDUE
        assert saved.status.value == "overdue"
