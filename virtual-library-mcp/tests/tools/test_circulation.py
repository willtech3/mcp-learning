"""Tests for circulation tools (checkout, return, reserve) over the protocol.

Highlights:
- checkout_book's elicitation flow: a patron with outstanding fines
  triggers a server-initiated confirmation that the client must answer
- ToolError for business-rule violations (model-recoverable errors)
- structured output for every circulation operation
"""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import server
from database.schema import Book as BookDB
from database.schema import CheckoutRecord as CheckoutDB
from database.schema import Patron as PatronDB


@pytest.fixture
async def client(library):
    """Client whose elicitation handler approves everything."""

    async def approve_all(message, response_type, params, context):
        return None  # bare accept for approval-style elicitations

    async with Client(server.mcp, elicitation_handler=approve_all) as c:
        yield c


class TestCheckoutBook:
    async def test_checkout_success_updates_state(self, client, library):
        result = await client.call_tool(
            "checkout_book",
            {"patron_id": "patron_clean001", "book_isbn": "9780134685991"},
        )
        data = result.structured_content
        assert data["patron_id"] == "patron_clean001"
        assert data["loan_period_days"] == 14

        book = library.get(BookDB, "9780134685991")
        assert book.available_copies == 2
        patron = library.get(PatronDB, "patron_clean001")
        assert patron.current_checkouts == 2

    async def test_checkout_unavailable_book_is_tool_error(self, client):
        with pytest.raises(ToolError, match=r"unavailable|no copies"):
            await client.call_tool(
                "checkout_book",
                {"patron_id": "patron_clean001", "book_isbn": "9780134685007"},
            )

    async def test_checkout_unknown_patron_is_tool_error(self, client):
        with pytest.raises(ToolError, match="not found"):
            await client.call_tool(
                "checkout_book",
                {"patron_id": "patron_missing99", "book_isbn": "9780134685991"},
            )

    async def test_checkout_invalid_isbn_rejected_by_schema(self, client):
        with pytest.raises(ToolError):
            await client.call_tool(
                "checkout_book", {"patron_id": "patron_clean001", "book_isbn": "not-an-isbn"}
            )


class TestCheckoutElicitation:
    """A patron with fines triggers a confirmation elicitation."""

    async def test_fined_patron_checkout_asks_and_proceeds_on_accept(self, library):
        asked: list[str] = []

        async def approve(message, response_type, params, context):
            asked.append(message)

        async with Client(server.mcp, elicitation_handler=approve) as client:
            result = await client.call_tool(
                "checkout_book",
                {"patron_id": "patron_fines001", "book_isbn": "9780134685991"},
            )
        assert result.structured_content["patron_id"] == "patron_fines001"
        assert len(asked) == 1
        assert "$4.50" in asked[0]

    async def test_fined_patron_checkout_aborts_on_decline(self, library):
        from fastmcp.client.elicitation import ElicitResult

        async def decline(message, response_type, params, context):
            return ElicitResult(action="decline")

        async with Client(server.mcp, elicitation_handler=decline) as client:
            with pytest.raises(ToolError, match="declined"):
                await client.call_tool(
                    "checkout_book",
                    {"patron_id": "patron_fines001", "book_isbn": "9780134685991"},
                )

        # No loan was created for the declined checkout.
        checkouts = (
            library.query(CheckoutDB).filter(CheckoutDB.patron_id == "patron_fines001").count()
        )
        assert checkouts == 0

    async def test_clean_patron_checkout_never_elicits(self, library):
        asked: list[str] = []

        async def record(message, response_type, params, context):
            asked.append(message)

        async with Client(server.mcp, elicitation_handler=record) as client:
            await client.call_tool(
                "checkout_book",
                {"patron_id": "patron_clean001", "book_isbn": "9780134685991"},
            )
        assert asked == []


class TestReturnBook:
    async def test_return_overdue_book_assesses_fine(self, client, library):
        result = await client.call_tool(
            "return_book", {"checkout_id": "checkout_active01", "condition": "good"}
        )
        data = result.structured_content
        assert data["late_days"] == 4
        assert data["fine_assessed"] == pytest.approx(1.0)  # 4 days * $0.25

        book = library.get(BookDB, "9780134685007")
        assert book.available_copies == 1  # restored

    async def test_return_records_condition(self, client):
        result = await client.call_tool(
            "return_book", {"checkout_id": "checkout_active01", "condition": "damaged"}
        )
        assert result.structured_content["condition"] == "damaged"
        assert "damaged" in result.structured_content["message"]

    async def test_return_unknown_checkout_is_tool_error(self, client):
        with pytest.raises(ToolError, match="not found"):
            await client.call_tool("return_book", {"checkout_id": "checkout_nope999"})

    async def test_schema_rejects_invalid_condition(self, client):
        with pytest.raises(ToolError):
            await client.call_tool(
                "return_book", {"checkout_id": "checkout_active01", "condition": "obliterated"}
            )


class TestReserveBook:
    async def test_reserve_unavailable_book_returns_queue_position(self, client):
        result = await client.call_tool(
            "reserve_book",
            {"patron_id": "patron_fines001", "book_isbn": "9780134685007"},
        )
        data = result.structured_content
        assert data["queue_position"] == 1
        assert data["total_in_queue"] == 1

    async def test_reserve_unknown_book_is_tool_error(self, client):
        with pytest.raises(ToolError, match="not found"):
            await client.call_tool(
                "reserve_book",
                {"patron_id": "patron_clean001", "book_isbn": "9999999999999"},
            )
