"""Regression tests for patron URI-template resources."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from models.book import Book
from resources.patrons import get_patron_history_handler


@pytest.mark.asyncio
async def test_patron_history_handles_serialized_status_and_resolves_title():
    patron = SimpleNamespace(id="patron_test001", name="Test Reader", current_checkouts=1)
    checkout = SimpleNamespace(
        id="checkout_202608080001",
        book_isbn="9780134685991",
        checkout_date=datetime.now() - timedelta(days=2),
        due_date=date.today() + timedelta(days=12),
        status="active",
        renewal_count=0,
        is_overdue=False,
        days_overdue=0,
        fine_amount=0.0,
        fine_paid=False,
    )
    book = Book(
        isbn="9780134685991",
        title="The Available Book",
        author_id="author_test001",
        genre="Fiction",
        publication_year=2020,
        available_copies=2,
        total_copies=3,
    )

    with (
        patch("resources.patrons.session_scope") as session_scope,
        patch("resources.patrons.PatronRepository") as patron_repository,
        patch("resources.patrons.CirculationRepository") as circulation_repository,
        patch("resources.patrons.BookRepository") as book_repository,
    ):
        session_scope.return_value.__enter__.return_value = Mock()
        patron_repository.return_value.get_with_activity.return_value = patron
        circulation_repository.return_value.get_patron_checkouts.return_value = [checkout]
        book_repository.return_value.get_by_isbn.return_value = book

        result = await get_patron_history_handler("patron_test001")

    assert result["history"][0]["status"] == "active"
    assert result["history"][0]["book_title"] == "The Available Book"
    assert result["history"][0]["details"]["is_overdue"] is False
