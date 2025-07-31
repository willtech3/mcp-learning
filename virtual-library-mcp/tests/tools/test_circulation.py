"""
Tests for circulation tools (checkout, return, reserve).

These tests demonstrate comprehensive testing of MCP tools:
1. Input validation
2. Success scenarios
3. Error handling
4. Business rule enforcement
5. State modifications
"""

from contextlib import contextmanager
from datetime import date, datetime, timedelta

import pytest

from database.schema import (
    Author as AuthorDB,
)
from database.schema import (
    Book as BookDB,
)
from database.schema import (
    CheckoutRecord as CheckoutDB,
)
from database.schema import (
    CirculationStatusEnum,
    ReservationStatusEnum,
)
from database.schema import (
    Patron as PatronDB,
)
from database.schema import (
    ReservationRecord as ReservationDB,
)
from database.schema import (
    ReturnRecord as ReturnDB,
)
from tools.circulation import (
    checkout_book_handler,
    reserve_book_handler,
    return_book_handler,
)


class TestCheckoutBookTool:
    """Test the checkout_book MCP tool."""

    @pytest.fixture
    def setup_test_data(self, test_db_session):
        """Create test patron and book for checkout tests."""
        # Create test author
        author = AuthorDB(
            id="author_test001",
            name="Test Author",
            birth_date=date(1970, 1, 1),
        )
        test_db_session.add(author)

        # Create a test patron
        patron = PatronDB(
            id="patron_test001",
            name="Test Patron",
            email="test@example.com",
            membership_date=date.today(),
            status="active",
            borrowing_limit=5,
            current_checkouts=0,
            outstanding_fines=0.0,
        )
        test_db_session.add(patron)

        # Create a test book
        book = BookDB(
            isbn="9780134685991",
            title="Test Book",
            author_id="author_test001",
            genre="Fiction",
            publication_year=2023,
            available_copies=3,
            total_copies=5,
        )
        test_db_session.add(book)

        test_db_session.commit()
        return patron, book

    async def test_checkout_success(self, setup_test_data, mock_get_session):
        """Test successful book checkout."""
        patron, book = setup_test_data

        # Execute checkout
        result = await checkout_book_handler(
            {
                "patron_id": patron.id,
                "book_isbn": book.isbn,
            }
        )

        # Verify success response
        assert "isError" not in result or not result["isError"]
        assert "content" in result
        assert result["content"][0]["type"] == "text"
        assert "Successfully checked out book" in result["content"][0]["text"]
        assert "Due date:" in result["content"][0]["text"]

        # Verify structured data
        assert "data" in result
        assert result["data"]["checkout"]["patron_id"] == patron.id
        assert result["data"]["checkout"]["book_isbn"] == book.isbn
        assert result["data"]["checkout"]["status"] == "active"
        assert result["data"]["checkout"]["loan_period_days"] == 14

        # Verify database state changes
        # Use the mock_get_session directly since it's the test session
        # Check book availability decreased
        updated_book = mock_get_session.get(BookDB, book.isbn)
        assert updated_book.available_copies == 2

        # Check patron checkout count increased
        updated_patron = mock_get_session.get(PatronDB, patron.id)
        assert updated_patron.current_checkouts == 1
        assert updated_patron.total_checkouts == 1

        # Check checkout record created
        checkout = (
            mock_get_session.query(CheckoutDB)
            .filter_by(patron_id=patron.id, book_isbn=book.isbn)
            .first()
        )
        assert checkout is not None
        assert checkout.status == CirculationStatusEnum.ACTIVE

    async def test_checkout_with_custom_due_date(self, setup_test_data, mock_get_session):
        """Test checkout with custom due date."""
        patron, book = setup_test_data
        custom_due_date = date.today() + timedelta(days=21)

        result = await checkout_book_handler(
            {
                "patron_id": patron.id,
                "book_isbn": book.isbn,
                "due_date": custom_due_date.isoformat(),
                "notes": "Extended loan for research",
            }
        )

        assert "isError" not in result or not result["isError"]
        assert result["data"]["checkout"]["due_date"] == custom_due_date.isoformat()
        assert result["data"]["checkout"]["loan_period_days"] == 21

        # Verify notes saved
        checkout = (
            mock_get_session.query(CheckoutDB)
            .filter_by(patron_id=patron.id, book_isbn=book.isbn)
            .first()
        )
        assert checkout.notes == "Extended loan for research"

    async def test_checkout_invalid_patron_id(self, mock_get_session):
        """Test checkout with invalid patron ID format."""
        result = await checkout_book_handler(
            {
                "patron_id": "invalid-format",
                "book_isbn": "9780134685991",
            }
        )

        assert result["isError"] is True
        assert "Invalid parameters" in result["content"][0]["text"]
        assert "patron_id" in result["content"][0]["text"].lower()

    async def test_checkout_patron_not_found(self, setup_test_data, mock_get_session):
        """Test checkout with non-existent patron."""
        _, book = setup_test_data

        result = await checkout_book_handler(
            {
                "patron_id": "patron_nonexistent",
                "book_isbn": book.isbn,
            }
        )

        assert result["isError"] is True
        assert "Patron patron_nonexistent not found" in result["content"][0]["text"]

    async def test_checkout_book_not_found(self, setup_test_data, mock_get_session):
        """Test checkout with non-existent book."""
        patron, _ = setup_test_data

        result = await checkout_book_handler(
            {
                "patron_id": patron.id,
                "book_isbn": "9999999999999",
            }
        )

        assert result["isError"] is True
        assert "Book 9999999999999 not found" in result["content"][0]["text"]

    async def test_checkout_book_unavailable(self, setup_test_data, mock_get_session):
        """Test checkout when no copies available."""
        patron, book = setup_test_data

        # Set available copies to 0
        # Using mocked session directly
        book_db = mock_get_session.get(BookDB, book.isbn)
        book_db.available_copies = 0
        mock_get_session.commit()

        result = await checkout_book_handler(
            {
                "patron_id": patron.id,
                "book_isbn": book.isbn,
            }
        )

        assert result["isError"] is True
        assert "Book unavailable for checkout" in result["content"][0]["text"]
        assert "no copies" in result["content"][0]["text"]

    async def test_checkout_patron_limit_exceeded(self, setup_test_data, mock_get_session):
        """Test checkout when patron has reached borrowing limit."""
        patron, book = setup_test_data

        # Set patron at borrowing limit
        # Using mocked session directly
        patron_db = mock_get_session.get(PatronDB, patron.id)
        patron_db.current_checkouts = patron_db.borrowing_limit
        mock_get_session.commit()

        result = await checkout_book_handler(
            {
                "patron_id": patron.id,
                "book_isbn": book.isbn,
            }
        )

        assert result["isError"] is True
        assert "borrowing limit" in result["content"][0]["text"]

    async def test_checkout_patron_inactive(self, setup_test_data, mock_get_session):
        """Test checkout with inactive patron membership."""
        patron, book = setup_test_data

        # Make patron inactive
        # Using mocked session directly
        patron_db = mock_get_session.get(PatronDB, patron.id)
        patron_db.status = "suspended"
        mock_get_session.commit()

        result = await checkout_book_handler(
            {
                "patron_id": patron.id,
                "book_isbn": book.isbn,
            }
        )

        assert result["isError"] is True
        assert "membership is not active" in result["content"][0]["text"]

    async def test_checkout_due_date_in_past(self, setup_test_data, mock_get_session):
        """Test checkout with past due date."""
        patron, book = setup_test_data
        past_date = date.today() - timedelta(days=1)

        result = await checkout_book_handler(
            {
                "patron_id": patron.id,
                "book_isbn": book.isbn,
                "due_date": past_date.isoformat(),
            }
        )

        assert result["isError"] is True
        assert "Due date cannot be in the past" in result["content"][0]["text"]


class TestReturnBookTool:
    """Test the return_book MCP tool."""

    @pytest.fixture
    def setup_checkout(self, test_db_session):
        """Create a checkout to test returns."""
        # Create test author
        author = AuthorDB(
            id="author_test001",
            name="Test Author",
            birth_date=date(1970, 1, 1),
        )
        test_db_session.add(author)

        # Create patron and book
        patron = PatronDB(
            id="patron_return001",
            name="Return Test Patron",
            email="return@example.com",
            membership_date=date.today(),
            status="active",
            current_checkouts=1,
            outstanding_fines=0.0,
        )
        test_db_session.add(patron)

        book = BookDB(
            isbn="9780134685992",
            title="Return Test Book",
            author_id="author_test001",
            genre="Fiction",
            publication_year=2023,
            available_copies=2,
            total_copies=3,
        )
        test_db_session.add(book)

        # Create active checkout
        checkout = CheckoutDB(
            id="checkout_20240101000001",
            patron_id=patron.id,
            book_isbn=book.isbn,
            checkout_date=datetime.now() - timedelta(days=7),
            due_date=date.today() + timedelta(days=7),
            status=CirculationStatusEnum.ACTIVE,
        )
        test_db_session.add(checkout)

        test_db_session.commit()
        return checkout, patron, book

    async def test_return_success(self, setup_checkout, mock_get_session):
        """Test successful book return."""
        checkout, patron, book = setup_checkout

        result = await return_book_handler(
            {
                "checkout_id": checkout.id,
            }
        )

        # Verify success response
        assert "isError" not in result or not result["isError"]
        assert "Successfully returned book" in result["content"][0]["text"]
        assert "Returned on time - no fines" in result["content"][0]["text"]

        # Verify structured data
        assert result["data"]["return"]["checkout_id"] == checkout.id
        assert result["data"]["return"]["late_days"] == 0
        assert result["data"]["return"]["fine_assessed"] == 0.0

        # Verify database state changes
        # Using mocked session directly
        # Check checkout marked complete
        updated_checkout = mock_get_session.get(CheckoutDB, checkout.id)
        assert updated_checkout.status == CirculationStatusEnum.COMPLETED
        assert updated_checkout.return_date is not None

        # Check book availability increased
        updated_book = mock_get_session.get(BookDB, book.isbn)
        assert updated_book.available_copies == 3

        # Check patron checkout count decreased
        updated_patron = mock_get_session.get(PatronDB, patron.id)
        assert updated_patron.current_checkouts == 0

    async def test_return_late_with_fine(self, setup_checkout, mock_get_session):
        """Test return of overdue book with fine calculation."""
        checkout, _, _ = setup_checkout

        # Make checkout overdue
        # Using mocked session directly
        checkout_db = mock_get_session.get(CheckoutDB, checkout.id)
        checkout_db.due_date = date.today() - timedelta(days=5)
        mock_get_session.commit()

        result = await return_book_handler(
            {
                "checkout_id": checkout.id,
            }
        )

        assert "isError" not in result or not result["isError"]
        assert "5 days late" in result["content"][0]["text"]
        assert "Fine assessed: $1.25" in result["content"][0]["text"]

        assert result["data"]["return"]["late_days"] == 5
        assert result["data"]["return"]["fine_assessed"] == 1.25
        assert result["data"]["return"]["fine_outstanding"] == 1.25

    async def test_return_with_condition_notes(self, setup_checkout, mock_get_session):
        """Test return with book condition and notes."""
        checkout, _, _ = setup_checkout

        result = await return_book_handler(
            {
                "checkout_id": checkout.id,
                "condition": "damaged",
                "notes": "Water damage on back cover",
                "rating": 4,
                "review": "Great story but the ending was predictable",
            }
        )

        assert "isError" not in result or not result["isError"]
        assert "Book condition noted as: damaged" in result["content"][0]["text"]

        # Verify condition saved
        # Using mocked session directly
        return_record = mock_get_session.query(ReturnDB).filter_by(checkout_id=checkout.id).first()
        assert return_record.condition == "damaged"
        assert return_record.notes == "Water damage on back cover"

    async def test_return_checkout_not_found(self, mock_get_session):
        """Test return with non-existent checkout."""
        result = await return_book_handler(
            {
                "checkout_id": "checkout_99999999999999",
            }
        )

        assert result["isError"] is True
        assert "Checkout checkout_99999999999999 not found" in result["content"][0]["text"]

    async def test_return_already_returned(self, setup_checkout, mock_get_session):
        """Test return of already returned checkout."""
        checkout, _, _ = setup_checkout

        # Mark checkout as already returned
        # Using mocked session directly
        checkout_db = mock_get_session.get(CheckoutDB, checkout.id)
        checkout_db.status = CirculationStatusEnum.COMPLETED
        mock_get_session.commit()

        result = await return_book_handler(
            {
                "checkout_id": checkout.id,
            }
        )

        assert result["isError"] is True
        assert "checkout is not active" in result["content"][0]["text"]

    async def test_return_invalid_condition(self, setup_checkout, mock_get_session):
        """Test return with invalid condition value."""
        checkout, _, _ = setup_checkout

        result = await return_book_handler(
            {
                "checkout_id": checkout.id,
                "condition": "destroyed",  # Invalid value
            }
        )

        assert result["isError"] is True
        assert "Invalid parameters" in result["content"][0]["text"]


class TestReserveBookTool:
    """Test the reserve_book MCP tool."""

    @pytest.fixture
    def setup_unavailable_book(self, test_db_session):
        """Create a book with no available copies."""
        # Create test author
        author = AuthorDB(
            id="author_test001",
            name="Test Author",
            birth_date=date(1970, 1, 1),
        )
        test_db_session.add(author)

        patron = PatronDB(
            id="patron_reserve001",
            name="Reserve Test Patron",
            email="reserve@example.com",
            membership_date=date.today(),
            status="active",
            outstanding_fines=0.0,
        )
        test_db_session.add(patron)

        book = BookDB(
            isbn="9780134685993",
            title="Popular Book",
            author_id="author_test001",
            genre="Fiction",
            publication_year=2023,
            available_copies=0,
            total_copies=2,
        )
        test_db_session.add(book)

        test_db_session.commit()
        return patron, book

    async def test_reserve_success(self, setup_unavailable_book, mock_get_session):
        """Test successful book reservation."""
        patron, book = setup_unavailable_book

        result = await reserve_book_handler(
            {
                "patron_id": patron.id,
                "book_isbn": book.isbn,
            }
        )

        # Verify success response
        assert "isError" not in result or not result["isError"]
        assert "Successfully reserved book" in result["content"][0]["text"]
        assert "Queue position: 1" in result["content"][0]["text"]

        # Verify structured data
        assert result["data"]["reservation"]["patron_id"] == patron.id
        assert result["data"]["reservation"]["book_isbn"] == book.isbn
        assert result["data"]["reservation"]["queue_position"] == 1
        assert result["data"]["reservation"]["status"] == "pending"

        # Verify database state
        # Using mocked session directly
        reservation = (
            mock_get_session.query(ReservationDB)
            .filter_by(patron_id=patron.id, book_isbn=book.isbn)
            .first()
        )
        assert reservation is not None
        assert reservation.status == ReservationStatusEnum.PENDING
        assert reservation.queue_position == 1

    async def test_reserve_with_queue(self, setup_unavailable_book, mock_get_session):
        """Test reservation when others are already in queue."""
        patron, book = setup_unavailable_book

        # Create existing reservation
        # Using mocked session directly
        existing_reservation = ReservationDB(
            id="reservation_existing001",
            patron_id="patron_other001",
            book_isbn=book.isbn,
            reservation_date=datetime.now() - timedelta(days=1),
            expiration_date=date.today() + timedelta(days=30),
            status=ReservationStatusEnum.PENDING,
            queue_position=1,
        )
        mock_get_session.add(existing_reservation)
        mock_get_session.commit()

        result = await reserve_book_handler(
            {
                "patron_id": patron.id,
                "book_isbn": book.isbn,
            }
        )

        assert "isError" not in result or not result["isError"]
        assert "Queue position: 2" in result["content"][0]["text"]
        assert "estimated wait: 14 days" in result["content"][0]["text"]

        assert result["data"]["reservation"]["queue_position"] == 2
        assert result["data"]["reservation"]["estimated_wait_days"] == 14
        assert result["data"]["reservation"]["total_in_queue"] == 2

    async def test_reserve_with_custom_expiration(self, setup_unavailable_book, mock_get_session):
        """Test reservation with custom expiration date."""
        patron, book = setup_unavailable_book
        expiration_date = date.today() + timedelta(days=60)

        result = await reserve_book_handler(
            {
                "patron_id": patron.id,
                "book_isbn": book.isbn,
                "expiration_date": expiration_date.isoformat(),
                "notes": "Need for summer reading list",
            }
        )

        assert "isError" not in result or not result["isError"]
        assert result["data"]["reservation"]["expiration_date"] == expiration_date.isoformat()

        # Verify notes saved
        # Using mocked session directly
        reservation = (
            mock_get_session.query(ReservationDB)
            .filter_by(patron_id=patron.id, book_isbn=book.isbn)
            .first()
        )
        assert reservation.notes == "Need for summer reading list"

    async def test_reserve_patron_not_found(self, setup_unavailable_book, mock_get_session):
        """Test reservation with non-existent patron."""
        _, book = setup_unavailable_book

        result = await reserve_book_handler(
            {
                "patron_id": "patron_nonexistent",
                "book_isbn": book.isbn,
            }
        )

        assert result["isError"] is True
        assert "Patron patron_nonexistent not found" in result["content"][0]["text"]

    async def test_reserve_book_not_found(self, setup_unavailable_book, mock_get_session):
        """Test reservation with non-existent book."""
        patron, _ = setup_unavailable_book

        result = await reserve_book_handler(
            {
                "patron_id": patron.id,
                "book_isbn": "9999999999999",
            }
        )

        assert result["isError"] is True
        assert "Book 9999999999999 not found" in result["content"][0]["text"]

    async def test_reserve_book_available(self, setup_unavailable_book, mock_get_session):
        """Test reservation attempt when book is available."""
        patron, book = setup_unavailable_book

        # Make book available
        # Using mocked session directly
        book_db = mock_get_session.get(BookDB, book.isbn)
        book_db.available_copies = 1
        mock_get_session.commit()

        result = await reserve_book_handler(
            {
                "patron_id": patron.id,
                "book_isbn": book.isbn,
            }
        )

        assert result["isError"] is True
        assert "Book has available copies" in result["content"][0]["text"]

    async def test_reserve_duplicate_reservation(self, setup_unavailable_book, mock_get_session):
        """Test duplicate reservation by same patron."""
        patron, book = setup_unavailable_book

        # Create first reservation
        await reserve_book_handler(
            {
                "patron_id": patron.id,
                "book_isbn": book.isbn,
            }
        )

        # Try to reserve again
        result = await reserve_book_handler(
            {
                "patron_id": patron.id,
                "book_isbn": book.isbn,
            }
        )

        assert result["isError"] is True
        assert "already has an active reservation" in result["content"][0]["text"]

    async def test_reserve_expiration_date_past(self, setup_unavailable_book, mock_get_session):
        """Test reservation with past expiration date."""
        patron, book = setup_unavailable_book
        past_date = date.today() - timedelta(days=1)

        result = await reserve_book_handler(
            {
                "patron_id": patron.id,
                "book_isbn": book.isbn,
                "expiration_date": past_date.isoformat(),
            }
        )

        assert result["isError"] is True
        assert "Expiration date must be in the future" in result["content"][0]["text"]

    async def test_reserve_expiration_date_too_far(self, setup_unavailable_book, mock_get_session):
        """Test reservation with expiration date too far in future."""
        patron, book = setup_unavailable_book
        far_date = date.today() + timedelta(days=100)

        result = await reserve_book_handler(
            {
                "patron_id": patron.id,
                "book_isbn": book.isbn,
                "expiration_date": far_date.isoformat(),
            }
        )

        assert result["isError"] is True
        assert "cannot be more than 90 days" in result["content"][0]["text"]


@pytest.fixture
def mock_get_session(test_db_session, monkeypatch):
    """Mock get_session to return the test session.

    This ensures that the circulation handlers use the same database session
    as the test, allowing them to see the test data we create.
    """

    @contextmanager
    def _mock_get_session():
        """Return the test session instead of creating a new one."""
        yield test_db_session

    # Patch the get_session function in the circulation module
    monkeypatch.setattr("tools.circulation.get_session", _mock_get_session)

    return test_db_session
