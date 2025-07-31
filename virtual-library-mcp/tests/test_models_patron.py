"""
Tests for the Patron model.

These tests verify that the Patron model correctly:
1. Validates patron data and membership status
2. Enforces borrowing limits and policies
3. Handles fines and payments
4. Manages notification preferences
"""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError
from virtual_library_mcp.models.patron import Patron, PatronStatus


class TestPatronModel:
    """Test suite for the Patron model."""

    def test_create_valid_patron(self):
        """Test creating a patron with valid data."""
        patron = Patron(
            id="patron_smith001",
            name="John Smith",
            email="john.smith@example.com",
            phone="+1234567890",
            address="123 Main St, Anytown, ST 12345",
            membership_date=date.today() - timedelta(days=365),
            expiration_date=date.today() + timedelta(days=365),
            status=PatronStatus.ACTIVE,
            borrowing_limit=5,
            current_checkouts=2,
            total_checkouts=45,
            outstanding_fines=0.0,
            preferred_genres=["Fiction", "Mystery"],
        )

        assert patron.id == "patron_smith001"
        assert patron.name == "John Smith"
        assert patron.email == "john.smith@example.com"
        assert patron.phone == "1234567890"  # Normalized
        assert patron.is_active is True
        assert patron.can_checkout is True
        assert patron.available_checkouts == 3

    def test_patron_id_validation(self):
        """Test patron ID pattern validation."""
        # Valid IDs
        valid_ids = ["patron_smith001", "patron_doe_jane", "patron_12345678"]

        for patron_id in valid_ids:
            patron = Patron(
                id=patron_id,
                name="Test Patron",
                email="test@example.com",
                membership_date=date.today(),
            )
            assert patron.id == patron_id

        # Invalid IDs
        invalid_ids = [
            "smith001",  # Missing prefix
            "patron_123",  # Too short
            "PATRON_smith001",  # Wrong case
            "patron-smith001",  # Wrong separator
        ]

        for patron_id in invalid_ids:
            with pytest.raises(ValidationError):
                Patron(
                    id=patron_id,
                    name="Test Patron",
                    email="test@example.com",
                    membership_date=date.today(),
                )

    def test_email_validation(self):
        """Test email validation."""
        # Valid emails
        valid_emails = [
            "john@example.com",
            "jane.doe@library.org",
            "patron+tag@example.co.uk",
        ]

        for email in valid_emails:
            patron = Patron(
                id="patron_test01",
                name="Test Patron",
                email=email,
                membership_date=date.today(),
            )
            assert patron.email == email

        # Invalid emails
        invalid_emails = [
            "not-an-email",
            "missing@domain",
            "@example.com",
            "user@",
        ]

        for email in invalid_emails:
            with pytest.raises(ValidationError):
                Patron(
                    id="patron_test01",
                    name="Test Patron",
                    email=email,
                    membership_date=date.today(),
                )

    def test_phone_normalization(self):
        """Test phone number normalization."""
        phone_numbers = [
            ("+1234567890", "1234567890"),
            ("555-123-4567", "5551234567"),
            ("(555) 123-4567", "5551234567"),
            ("555 123 4567", "5551234567"),
            ("+1 (555) 123-4567", "15551234567"),
        ]

        for input_phone, expected in phone_numbers:
            patron = Patron(
                id="patron_test01",
                name="Test Patron",
                email="test@example.com",
                membership_date=date.today(),
                phone=input_phone,
            )
            assert patron.phone == expected

    def test_membership_dates_validation(self):
        """Test membership and expiration date validation."""
        # Valid dates
        patron = Patron(
            id="patron_test01",
            name="Test Patron",
            email="test@example.com",
            membership_date=date(2023, 1, 1),
            expiration_date=date(2024, 1, 1),
        )
        assert patron.membership_date < patron.expiration_date

        # Membership date in future
        with pytest.raises(ValidationError) as exc_info:
            Patron(
                id="patron_test01",
                name="Test Patron",
                email="test@example.com",
                membership_date=date.today() + timedelta(days=1),
            )
        assert "future" in str(exc_info.value)

        # Expiration before membership
        with pytest.raises(ValidationError) as exc_info:
            Patron(
                id="patron_test01",
                name="Test Patron",
                email="test@example.com",
                membership_date=date(2023, 1, 1),
                expiration_date=date(2022, 12, 31),
            )
        assert "after membership date" in str(exc_info.value)

    def test_patron_status(self):
        """Test different patron statuses."""
        statuses = [
            PatronStatus.ACTIVE,
            PatronStatus.SUSPENDED,
            PatronStatus.EXPIRED,
            PatronStatus.PENDING,
        ]

        for status in statuses:
            patron = Patron(
                id="patron_test01",
                name="Test Patron",
                email="test@example.com",
                membership_date=date.today(),
                status=status,
            )
            assert patron.status == status

            # Only ACTIVE status allows checkout
            if status == PatronStatus.ACTIVE:
                assert patron.is_active is True
            else:
                assert patron.is_active is False

    def test_expired_membership(self):
        """Test behavior with expired membership."""
        # Not expired
        patron = Patron(
            id="patron_test01",
            name="Test Patron",
            email="test@example.com",
            membership_date=date.today() - timedelta(days=365),
            expiration_date=date.today() + timedelta(days=1),
            status=PatronStatus.ACTIVE,
        )
        assert patron.is_active is True

        # Expired
        patron = Patron(
            id="patron_test02",
            name="Test Patron",
            email="test@example.com",
            membership_date=date.today() - timedelta(days=365),
            expiration_date=date.today() - timedelta(days=1),
            status=PatronStatus.ACTIVE,
        )
        assert patron.is_active is False
        assert patron.can_checkout is False

    def test_borrowing_limits(self):
        """Test borrowing limit enforcement."""
        patron = Patron(
            id="patron_test01",
            name="Test Patron",
            email="test@example.com",
            membership_date=date.today(),
            borrowing_limit=5,
            current_checkouts=3,
        )

        assert patron.available_checkouts == 2
        assert patron.can_checkout is True

        # At limit
        patron.current_checkouts = 5
        assert patron.available_checkouts == 0
        assert patron.can_checkout is False

        # Invalid: current exceeds limit
        with pytest.raises(ValidationError) as exc_info:
            Patron(
                id="patron_test01",
                name="Test Patron",
                email="test@example.com",
                membership_date=date.today(),
                borrowing_limit=5,
                current_checkouts=6,
            )
        assert "exceed borrowing limit" in str(exc_info.value)

    def test_checkout_book_method(self):
        """Test the checkout_book method."""
        patron = Patron(
            id="patron_test01",
            name="Test Patron",
            email="test@example.com",
            membership_date=date.today(),
            borrowing_limit=3,
            current_checkouts=1,
            total_checkouts=10,
        )

        # Successful checkout
        patron.checkout_book()
        assert patron.current_checkouts == 2
        assert patron.total_checkouts == 11
        assert patron.last_activity is not None

        # Checkout at limit
        patron.checkout_book()
        assert patron.current_checkouts == 3

        # Try to exceed limit
        with pytest.raises(ValueError, match="Borrowing limit"):
            patron.checkout_book()

    def test_return_book_method(self):
        """Test the return_book method."""
        patron = Patron(
            id="patron_test01",
            name="Test Patron",
            email="test@example.com",
            membership_date=date.today(),
            current_checkouts=3,
        )

        # Successful return
        patron.return_book()
        assert patron.current_checkouts == 2
        assert patron.last_activity is not None

        # Return all books
        patron.return_book()
        patron.return_book()
        assert patron.current_checkouts == 0

        # Try to return when none checked out
        with pytest.raises(ValueError, match="No books to return"):
            patron.return_book()

    def test_fine_management(self):
        """Test fine addition and payment."""
        patron = Patron(
            id="patron_test01",
            name="Test Patron",
            email="test@example.com",
            membership_date=date.today(),
            outstanding_fines=5.50,
        )

        # Add fine
        patron.add_fine(2.25)
        assert patron.outstanding_fines == 7.75

        # Invalid fine amount
        with pytest.raises(ValueError, match="must be positive"):
            patron.add_fine(-1.00)

        # Pay fine
        patron.pay_fine(5.00)
        assert patron.outstanding_fines == 2.75

        # Overpayment
        with pytest.raises(ValueError, match="exceeds outstanding"):
            patron.pay_fine(5.00)

        # Negative payment
        with pytest.raises(ValueError, match="must be positive"):
            patron.pay_fine(-1.00)

    def test_fine_blocks_checkout(self):
        """Test that high fines block checkouts."""
        patron = Patron(
            id="patron_test01",
            name="Test Patron",
            email="test@example.com",
            membership_date=date.today(),
            outstanding_fines=10.00,  # At limit
        )

        assert patron.can_checkout is False

        with pytest.raises(ValueError, match="Outstanding fines"):
            patron.checkout_book()

        # Pay down fines
        patron.pay_fine(0.01)
        assert patron.outstanding_fines == 9.99
        assert patron.can_checkout is True

    def test_genre_preferences(self):
        """Test genre preference normalization."""
        patron = Patron(
            id="patron_test01",
            name="Test Patron",
            email="test@example.com",
            membership_date=date.today(),
            preferred_genres=["fiction", "MYSTERY", "science fiction", "Fiction"],
        )

        # Should be normalized and deduplicated
        assert patron.preferred_genres == ["Fiction", "Mystery", "Science Fiction"]

    def test_notification_preferences(self):
        """Test notification preferences."""
        patron = Patron(
            id="patron_test01",
            name="Test Patron",
            email="test@example.com",
            membership_date=date.today(),
        )

        # Check defaults
        assert patron.notification_preferences["email"] is True
        assert patron.notification_preferences["sms"] is False
        assert patron.notification_preferences["due_date_reminder"] is True
        assert patron.notification_preferences["new_arrivals"] is False

        # Custom preferences
        patron = Patron(
            id="patron_test02",
            name="Test Patron",
            email="test@example.com",
            membership_date=date.today(),
            notification_preferences={
                "email": False,
                "sms": True,
                "due_date_reminder": False,
                "new_arrivals": True,
            },
        )

        assert patron.notification_preferences["email"] is False
        assert patron.notification_preferences["sms"] is True

    def test_membership_renewal(self):
        """Test membership renewal."""
        # Expired membership
        patron = Patron(
            id="patron_test01",
            name="Test Patron",
            email="test@example.com",
            membership_date=date(2022, 1, 1),
            expiration_date=date(2023, 1, 1),
            status=PatronStatus.EXPIRED,
        )

        patron.renew_membership(years=1)
        assert patron.expiration_date.year == date.today().year + 1
        assert patron.status == PatronStatus.ACTIVE

        # Active membership - extend from current expiration
        patron = Patron(
            id="patron_test02",
            name="Test Patron",
            email="test@example.com",
            membership_date=date.today() - timedelta(days=30),
            expiration_date=date.today() + timedelta(days=335),
            status=PatronStatus.ACTIVE,
        )

        original_expiration = patron.expiration_date
        patron.renew_membership(years=2)
        assert patron.expiration_date.year == original_expiration.year + 2

        # Invalid renewal period
        with pytest.raises(ValueError, match="at least 1 year"):
            patron.renew_membership(years=0)

    def test_membership_duration(self):
        """Test membership duration calculation."""
        patron = Patron(
            id="patron_test01",
            name="Test Patron",
            email="test@example.com",
            membership_date=date.today() - timedelta(days=365),
        )

        assert patron.membership_duration_days == 365

    def test_json_serialization(self):
        """Test JSON serialization and deserialization."""
        patron = Patron(
            id="patron_smith001",
            name="John Smith",
            email="john.smith@example.com",
            membership_date=date(2023, 1, 15),
            preferred_genres=["Fiction", "Mystery"],
        )

        # Serialize to dict
        data = patron.model_dump()
        assert data["id"] == "patron_smith001"
        assert data["preferred_genres"] == ["Fiction", "Mystery"]

        # Serialize to JSON
        json_str = patron.model_dump_json()
        assert "patron_smith001" in json_str

        # Deserialize
        patron2 = Patron.model_validate(data)
        assert patron2.id == patron.id
        assert patron2.email == patron.email
