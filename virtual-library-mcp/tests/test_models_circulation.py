"""
Tests for the Circulation models.

These tests verify that the circulation models correctly:
1. Track checkouts, returns, and reservations
2. Calculate fines and due dates
3. Handle status transitions
4. Maintain data integrity
"""

from datetime import date, datetime, timedelta

import pytest
from pydantic import ValidationError
from virtual_library_mcp.models.circulation import (
    CheckoutRecord,
    CirculationStatus,
    ReservationRecord,
    ReservationStatus,
    ReturnRecord,
)


class TestCheckoutRecord:
    """Test suite for CheckoutRecord model."""

    def test_create_valid_checkout(self):
        """Test creating a checkout with valid data."""
        checkout_date = datetime.now()
        due_date = date.today() + timedelta(days=14)

        checkout = CheckoutRecord(
            id="checkout_202312150001",
            patron_id="patron_smith001",
            book_isbn="9780134685479",
            checkout_date=checkout_date,
            due_date=due_date,
        )

        assert checkout.id == "checkout_202312150001"
        assert checkout.patron_id == "patron_smith001"
        assert checkout.book_isbn == "9780134685479"
        assert checkout.status == CirculationStatus.ACTIVE
        assert checkout.renewal_count == 0
        assert checkout.fine_amount == 0.0
        assert checkout.loan_period_days == 14

    def test_checkout_id_validation(self):
        """Test checkout ID pattern validation."""
        valid_ids = [
            "checkout_202312150001",
            "checkout_202403201234",
            "checkout_123456789012",
        ]

        for checkout_id in valid_ids:
            checkout = CheckoutRecord(
                id=checkout_id,
                patron_id="patron_test01",
                book_isbn="9780134685479",
                due_date=date.today() + timedelta(days=14),
            )
            assert checkout.id == checkout_id

        # Invalid IDs
        invalid_ids = [
            "202312150001",  # Missing prefix
            "checkout_12345",  # Too short
            "CHECKOUT_202312150001",  # Wrong case
        ]

        for checkout_id in invalid_ids:
            with pytest.raises(ValidationError):
                CheckoutRecord(
                    id=checkout_id,
                    patron_id="patron_test01",
                    book_isbn="9780134685479",
                    due_date=date.today() + timedelta(days=14),
                )

    def test_due_date_validation(self):
        """Test that due date must be after checkout date."""
        checkout_date = datetime.now()

        # Valid: due date after checkout
        checkout = CheckoutRecord(
            id="checkout_test01",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            checkout_date=checkout_date,
            due_date=date.today() + timedelta(days=1),
        )
        assert checkout.due_date > checkout.checkout_date.date()

        # Invalid: due date before checkout
        with pytest.raises(ValidationError) as exc_info:
            CheckoutRecord(
                id="checkout_test01",
                patron_id="patron_test01",
                book_isbn="9780134685479",
                checkout_date=checkout_date,
                due_date=date.today() - timedelta(days=1),
            )
        assert "after checkout date" in str(exc_info.value)

    def test_overdue_calculation(self):
        """Test overdue status and days calculation."""
        # Not overdue
        checkout = CheckoutRecord(
            id="checkout_test01",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            due_date=date.today() + timedelta(days=1),
        )
        assert checkout.is_overdue is False
        assert checkout.days_overdue == 0

        # Overdue
        checkout = CheckoutRecord(
            id="checkout_test02",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            checkout_date=datetime.now() - timedelta(days=20),
            due_date=date.today() - timedelta(days=5),
        )
        assert checkout.is_overdue is True
        assert checkout.days_overdue == 5

        # Completed checkout not overdue
        checkout.status = CirculationStatus.COMPLETED
        assert checkout.is_overdue is False

    def test_fine_calculation(self):
        """Test fine calculation based on overdue days."""
        # Not overdue - no fine
        checkout = CheckoutRecord(
            id="checkout_test01",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            due_date=date.today() + timedelta(days=1),
        )
        assert checkout.calculate_fine() == 0.0

        # Overdue - calculate fine
        checkout = CheckoutRecord(
            id="checkout_test02",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            checkout_date=datetime.now() - timedelta(days=20),
            due_date=date.today() - timedelta(days=10),
        )
        assert checkout.calculate_fine() == 2.50  # 10 days * $0.25
        assert checkout.calculate_fine(daily_rate=0.50) == 5.00  # Custom rate

        # Returned late - use return date
        checkout.return_date = datetime.now() - timedelta(days=3)
        assert checkout.calculate_fine() == 1.75  # 7 days * $0.25

    def test_renewal(self):
        """Test checkout renewal."""
        checkout = CheckoutRecord(
            id="checkout_test01",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            due_date=date.today() + timedelta(days=7),
            renewal_count=0,
        )

        # First renewal
        original_due = checkout.due_date
        checkout.renew()
        assert checkout.due_date == original_due + timedelta(days=14)
        assert checkout.renewal_count == 1

        # Renew with custom extension
        checkout.renew(extension_days=7)
        assert checkout.renewal_count == 2

        # Third renewal
        checkout.renew()
        assert checkout.renewal_count == 3

        # Maximum renewals reached
        with pytest.raises(ValueError, match="Maximum renewal limit"):
            checkout.renew()

    def test_renewal_restrictions(self):
        """Test renewal restriction conditions."""
        # Cannot renew overdue items
        checkout = CheckoutRecord(
            id="checkout_test01",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            checkout_date=datetime.now() - timedelta(days=10),
            due_date=date.today() - timedelta(days=1),
        )

        with pytest.raises(ValueError, match="Cannot renew overdue"):
            checkout.renew()

        # Cannot renew non-active checkouts
        checkout = CheckoutRecord(
            id="checkout_test02",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            due_date=date.today() + timedelta(days=7),
            status=CirculationStatus.COMPLETED,
        )

        with pytest.raises(ValueError, match="only renew active"):
            checkout.renew()

    def test_complete_return(self):
        """Test completing a return."""
        checkout = CheckoutRecord(
            id="checkout_test01",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            checkout_date=datetime.now() - timedelta(days=10),
            due_date=date.today() - timedelta(days=5),  # Overdue
        )

        assert checkout.return_date is None
        assert checkout.status == CirculationStatus.ACTIVE

        # Complete return
        checkout.complete_return()

        assert checkout.return_date is not None
        assert checkout.status == CirculationStatus.COMPLETED
        assert checkout.fine_amount == 1.25  # 5 days * $0.25

        # Cannot return again
        with pytest.raises(ValueError, match="already completed"):
            checkout.complete_return()


class TestReturnRecord:
    """Test suite for ReturnRecord model."""

    def test_create_valid_return(self):
        """Test creating a return record with valid data."""
        return_record = ReturnRecord(
            id="return_202312290001",
            checkout_id="checkout_202312150001",
            patron_id="patron_smith001",
            book_isbn="9780134685479",
            condition="good",
            late_days=0,
            fine_assessed=0.0,
            fine_paid=0.0,
        )

        assert return_record.id == "return_202312290001"
        assert return_record.condition == "good"
        assert return_record.fine_outstanding == 0.0
        assert return_record.is_damaged is False

    def test_condition_validation(self):
        """Test book condition values."""
        valid_conditions = ["excellent", "good", "fair", "damaged", "lost"]

        for condition in valid_conditions:
            return_record = ReturnRecord(
                id="return_test01",
                checkout_id="checkout_test01",
                patron_id="patron_test01",
                book_isbn="9780134685479",
                condition=condition,
            )
            assert return_record.condition == condition

            if condition in ["damaged", "lost"]:
                assert return_record.is_damaged is True
            else:
                assert return_record.is_damaged is False

        # Invalid condition
        with pytest.raises(ValidationError):
            ReturnRecord(
                id="return_test01",
                checkout_id="checkout_test01",
                patron_id="patron_test01",
                book_isbn="9780134685479",
                condition="broken",
            )

    def test_fine_validation(self):
        """Test fine amount validation."""
        # Valid: paid equals assessed
        return_record = ReturnRecord(
            id="return_test01",
            checkout_id="checkout_test01",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            fine_assessed=5.00,
            fine_paid=5.00,
        )
        assert return_record.fine_outstanding == 0.0

        # Valid: partial payment
        return_record = ReturnRecord(
            id="return_test02",
            checkout_id="checkout_test01",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            fine_assessed=5.00,
            fine_paid=3.00,
        )
        assert return_record.fine_outstanding == 2.00

        # Test invalid overpayment scenario
        with pytest.raises(ValidationError) as exc_info:
            ReturnRecord(
                id="return_test03",
                checkout_id="checkout_test01",
                patron_id="patron_test01",
                book_isbn="9780134685479",
                fine_assessed=5.00,
                fine_paid=6.00,
            )
        assert "exceed fine assessed" in str(exc_info.value)


class TestReservationRecord:
    """Test suite for ReservationRecord model."""

    def test_create_valid_reservation(self):
        """Test creating a reservation with valid data."""
        reservation = ReservationRecord(
            id="reservation_202312150001",
            patron_id="patron_smith001",
            book_isbn="9780134685479",
            expiration_date=date.today() + timedelta(days=30),
            queue_position=1,
        )

        assert reservation.id == "reservation_202312150001"
        assert reservation.status == ReservationStatus.PENDING
        assert reservation.is_expired is False
        assert reservation.days_until_expiration == 30

    def test_expiration_date_validation(self):
        """Test that expiration date must be in the future."""
        # Valid
        reservation = ReservationRecord(
            id="reservation_test01",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            expiration_date=date.today() + timedelta(days=1),
            queue_position=1,
        )
        assert reservation.expiration_date > date.today()

        # Invalid: past date
        with pytest.raises(ValidationError) as exc_info:
            ReservationRecord(
                id="reservation_test01",
                patron_id="patron_test01",
                book_isbn="9780134685479",
                expiration_date=date.today() - timedelta(days=1),
                queue_position=1,
            )
        assert "after reservation date" in str(exc_info.value)

    def test_notify_available(self):
        """Test notifying patron of availability."""
        reservation = ReservationRecord(
            id="reservation_test01",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            expiration_date=date.today() + timedelta(days=30),
            queue_position=1,
        )

        assert reservation.status == ReservationStatus.PENDING
        assert reservation.notification_date is None
        assert reservation.pickup_deadline is None

        # Notify available
        reservation.notify_available(pickup_days=3)

        assert reservation.status == ReservationStatus.AVAILABLE
        assert reservation.notification_date is not None
        assert reservation.pickup_deadline == date.today() + timedelta(days=3)

        # Cannot notify again
        with pytest.raises(ValueError, match="only notify for pending"):
            reservation.notify_available()

    def test_reservation_expiration(self):
        """Test reservation expiration logic."""
        # Not expired - pending
        reservation = ReservationRecord(
            id="reservation_test01",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            expiration_date=date.today() + timedelta(days=10),
            queue_position=1,
        )
        assert reservation.is_expired is False
        assert reservation.days_until_expiration == 10

        # Expired - past expiration date
        reservation = ReservationRecord(
            id="reservation_test02",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            reservation_date=datetime.now() - timedelta(days=10),
            expiration_date=date.today() - timedelta(days=1),
            queue_position=1,
        )
        assert reservation.is_expired is True
        assert reservation.days_until_expiration == 0

        # Available with pickup deadline
        reservation = ReservationRecord(
            id="reservation_test02",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            expiration_date=date.today() + timedelta(days=30),
            queue_position=1,
            status=ReservationStatus.AVAILABLE,
            notification_date=datetime.now(),
            pickup_deadline=date.today() + timedelta(days=3),
        )
        assert reservation.is_expired is False
        assert reservation.days_until_expiration == 3

        # Expired pickup deadline
        reservation = ReservationRecord(
            id="reservation_test03",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            reservation_date=datetime.now() - timedelta(days=10),
            expiration_date=date.today() + timedelta(days=30),
            queue_position=1,
            status=ReservationStatus.AVAILABLE,
            notification_date=datetime.now() - timedelta(days=5),
            pickup_deadline=date.today() - timedelta(days=1),
        )
        assert reservation.is_expired is True

    def test_fulfill_reservation(self):
        """Test fulfilling a reservation."""
        reservation = ReservationRecord(
            id="reservation_test01",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            expiration_date=date.today() + timedelta(days=30),
            queue_position=1,
            status=ReservationStatus.AVAILABLE,
        )

        # Fulfill
        reservation.fulfill()
        assert reservation.status == ReservationStatus.FULFILLED

        # Cannot fulfill non-available
        reservation2 = ReservationRecord(
            id="reservation_test02",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            expiration_date=date.today() + timedelta(days=30),
            queue_position=1,
            status=ReservationStatus.PENDING,
        )

        with pytest.raises(ValueError, match="only fulfill available"):
            reservation2.fulfill()

    def test_cancel_reservation(self):
        """Test canceling a reservation."""
        reservation = ReservationRecord(
            id="reservation_test01",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            expiration_date=date.today() + timedelta(days=30),
            queue_position=1,
        )

        # Cancel pending
        reservation.cancel()
        assert reservation.status == ReservationStatus.CANCELLED

        # Cannot cancel completed
        reservation2 = ReservationRecord(
            id="reservation_test02",
            patron_id="patron_test01",
            book_isbn="9780134685479",
            expiration_date=date.today() + timedelta(days=30),
            queue_position=1,
            status=ReservationStatus.FULFILLED,
        )

        with pytest.raises(ValueError, match="Cannot cancel completed"):
            reservation2.cancel()
