"""Tests for circulation tools (checkout, return, reserve) over the protocol.

Highlights:
- checkout_book's elicitation flow: a patron with outstanding fines
  triggers a server-initiated confirmation that the client must answer
- ToolError for business-rule violations (model-recoverable errors)
- structured output for every circulation operation
"""

import asyncio
import time
from types import SimpleNamespace

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import server
from database.schema import Book as BookDB
from database.schema import CheckoutRecord as CheckoutDB
from database.schema import Patron as PatronDB
from database.schema import ReservationRecord as ReservationDB
from database.schema import ReturnRecord as ReturnDB
from tools.interaction import ElicitationUnavailableError, elicit_with_timeout


@pytest.fixture
async def client(library):
    """Client whose elicitation handler approves everything."""

    async def approve_all(message, response_type, params, context):
        return True

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
                {
                    "patron_id": "patron_fines001",
                    "book_isbn": "9780134685007",
                    "fines_acknowledged": True,
                },
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
            return True

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
            with pytest.raises(ToolError, match=r"cancelled|did not approve"):
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

    async def test_stateless_http_fails_fast_then_explicit_retry_succeeds(
        self, library, monkeypatch
    ):
        monkeypatch.setattr(
            "tools.interaction.get_config",
            lambda: SimpleNamespace(
                transport="http",
                http_stateless=True,
                elicitation_timeout_seconds=20,
            ),
        )
        started = time.monotonic()
        async with Client(server.mcp) as client:
            with pytest.raises(ToolError, match="fines_acknowledged=true"):
                await client.call_tool(
                    "checkout_book",
                    {"patron_id": "patron_fines001", "book_isbn": "9780134685991"},
                )
            assert time.monotonic() - started < 1
            assert (
                library.query(CheckoutDB).filter(CheckoutDB.patron_id == "patron_fines001").count()
                == 0
            )

            result = await client.call_tool(
                "checkout_book",
                {
                    "patron_id": "patron_fines001",
                    "book_isbn": "9780134685991",
                    "fines_acknowledged": True,
                },
            )
        assert result.structured_content["replayed"] is False

    async def test_elicitation_helper_enforces_timeout(self, monkeypatch):
        monkeypatch.setattr(
            "tools.interaction.get_config",
            lambda: SimpleNamespace(
                transport="stdio",
                http_stateless=False,
                elicitation_timeout_seconds=0.01,
            ),
        )

        class SlowContext:
            async def elicit(self, *args, **kwargs):
                await asyncio.sleep(1)
                return True

        started = time.monotonic()
        with pytest.raises(ElicitationUnavailableError, match="did not answer"):
            await elicit_with_timeout(SlowContext(), "Confirm", bool)
        assert time.monotonic() - started < 0.5

    async def test_elicitation_timeout_fails_closed_without_mutation(self, library, monkeypatch):
        async def timed_out(*args, **kwargs):
            del args, kwargs
            raise ElicitationUnavailableError("timed out")

        monkeypatch.setattr("tools.circulation.elicit_with_timeout", timed_out)

        async with Client(server.mcp) as client:
            with pytest.raises(ToolError, match="No checkout was created"):
                await client.call_tool(
                    "checkout_book",
                    {"patron_id": "patron_fines001", "book_isbn": "9780134685991"},
                )
        assert (
            library.query(CheckoutDB).filter(CheckoutDB.patron_id == "patron_fines001").count() == 0
        )

    async def test_checkout_retry_reconciles_without_second_loan(self, client, library):
        arguments = {"patron_id": "patron_clean001", "book_isbn": "9780134685991"}
        first = await client.call_tool("checkout_book", arguments)
        second = await client.call_tool("checkout_book", arguments)

        assert second.structured_content["checkout_id"] == first.structured_content["checkout_id"]
        assert second.structured_content["replayed"] is True
        assert library.get(BookDB, "9780134685991").available_copies == 2
        assert library.get(PatronDB, "patron_clean001").current_checkouts == 2


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

    async def test_return_retry_reuses_result_and_assesses_fine_once(self, client, library):
        first = await client.call_tool("return_book", {"checkout_id": "checkout_active01"})
        second = await client.call_tool("return_book", {"checkout_id": "checkout_active01"})

        assert second.structured_content["return_id"] == first.structured_content["return_id"]
        assert second.structured_content["replayed"] is True
        assert library.query(ReturnDB).count() == 1
        assert library.get(PatronDB, "patron_clean001").outstanding_fines == pytest.approx(1.0)


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

    async def test_reservation_retry_reuses_active_hold(self, client, library):
        arguments = {"patron_id": "patron_fines001", "book_isbn": "9780134685007"}
        first = await client.call_tool("reserve_book", arguments)
        second = await client.call_tool("reserve_book", arguments)

        assert (
            second.structured_content["reservation_id"]
            == first.structured_content["reservation_id"]
        )
        assert second.structured_content["replayed"] is True
        assert library.query(ReservationDB).count() == 1


class TestCirculationDescriptors:
    async def test_retry_safe_mutations_are_marked_idempotent(self, client):
        descriptors = {tool.name: tool for tool in await client.list_tools()}
        for name in ("checkout_book", "return_book", "reserve_book"):
            assert descriptors[name].annotations.idempotentHint is True
