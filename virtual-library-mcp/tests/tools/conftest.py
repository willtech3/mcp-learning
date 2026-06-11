"""Shared fixtures for tool tests.

Tool tests run through the FastMCP in-memory Client against the real
server instance (server.mcp), so they exercise the actual protocol path:
input schema validation, elicitation round-trips, structured content,
and ToolError -> isError conversion. The only thing faked is the
database session, which is pointed at a seeded per-test SQLite database.
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
)
from database.schema import (
    Patron as PatronDB,
)

# Every tools module imports its session factory into its own namespace,
# so each must be patched where it is *used*, not where it is defined.
_SESSION_FACTORY_PATCHES = [
    "tools.search.get_session",
    "tools.circulation.get_session",
    "tools.membership.get_session",
    "tools.bulk_import.session_scope",
    "tools.catalog_maintenance.session_scope",
    "tools.book_insights.session_scope",
]


@pytest.fixture
def library(test_db_session, monkeypatch):
    """A small seeded library wired into every tool module.

    Contents:
    - author_test001 with two books (one available, one with 0 copies)
    - patron_clean001: active, no fines
    - patron_fines001: active, $4.50 outstanding fines (elicitation trigger)
    - patron_lapsed01: expired membership
    - checkout_active01: open loan for patron_clean001 (overdue by 4 days)
    """

    @contextmanager
    def _test_session():
        yield test_db_session

    for target in _SESSION_FACTORY_PATCHES:
        monkeypatch.setattr(target, _test_session)

    author = AuthorDB(id="author_test001", name="Test Author", birth_date=date(1970, 1, 1))
    test_db_session.add(author)

    available_book = BookDB(
        isbn="9780134685991",
        title="The Available Book",
        author_id="author_test001",
        genre="Fiction",
        publication_year=2020,
        available_copies=3,
        total_copies=3,
        description="A book with copies on the shelf.",
    )
    unavailable_book = BookDB(
        isbn="9780134685007",
        title="The Popular Book",
        author_id="author_test001",
        genre="Science Fiction",
        publication_year=2021,
        available_copies=0,
        total_copies=2,
        description="A book that is always checked out.",
    )
    test_db_session.add_all([available_book, unavailable_book])

    today = date.today()
    patrons = [
        PatronDB(
            id="patron_clean001",
            name="Clean Reader",
            email="clean@example.com",
            membership_date=today - timedelta(days=400),
            expiration_date=today + timedelta(days=200),
            status="active",
            borrowing_limit=5,
            current_checkouts=1,
            total_checkouts=12,
            outstanding_fines=0.0,
        ),
        PatronDB(
            id="patron_fines001",
            name="Fined Reader",
            email="fined@example.com",
            membership_date=today - timedelta(days=300),
            expiration_date=today + timedelta(days=100),
            status="active",
            borrowing_limit=5,
            current_checkouts=0,
            total_checkouts=30,
            outstanding_fines=4.50,
        ),
        PatronDB(
            id="patron_lapsed01",
            name="Lapsed Reader",
            email="lapsed@example.com",
            membership_date=today - timedelta(days=900),
            expiration_date=today - timedelta(days=90),
            status="expired",
            borrowing_limit=5,
            current_checkouts=0,
            total_checkouts=4,
            outstanding_fines=0.0,
        ),
    ]
    test_db_session.add_all(patrons)

    checkout = CheckoutDB(
        id="checkout_active01",
        patron_id="patron_clean001",
        book_isbn="9780134685007",
        checkout_date=datetime.now() - timedelta(days=18),
        due_date=today - timedelta(days=4),
        status=CirculationStatusEnum.OVERDUE,
    )
    test_db_session.add(checkout)
    test_db_session.commit()

    return test_db_session
