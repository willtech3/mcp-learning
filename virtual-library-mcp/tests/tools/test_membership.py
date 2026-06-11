"""Tests for renew_membership — the enum-elicitation showcase.

The renewal term is never a tool argument: the server elicits it from the
user mid-execution (MCP 2025-11-25 elicitation with constrained options).
"""

from datetime import date, timedelta

import pytest
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult
from fastmcp.exceptions import ToolError

import server
from database.schema import Patron as PatronDB


def _term_handler(term: str):
    async def handler(message, response_type, params, context):
        # Constrained elicitation: FastMCP wraps the Literal options in a
        # dataclass-like response type with a single 'value' field.
        if response_type is None:
            return None
        return term

    return handler


class TestRenewMembership:
    async def test_renewal_applies_chosen_term(self, library):
        async with Client(server.mcp, elicitation_handler=_term_handler("12 months")) as client:
            result = await client.call_tool("renew_membership", {"patron_id": "patron_clean001"})
        data = result.structured_content
        assert data["renewed"] is True
        assert data["term"] == "12 months"

        patron = library.get(PatronDB, "patron_clean001")
        library.refresh(patron)
        expected = date.today() + timedelta(days=200) + timedelta(days=365)
        assert patron.expiration_date == expected

    async def test_renewal_reactivates_expired_membership(self, library):
        async with Client(server.mcp, elicitation_handler=_term_handler("6 months")) as client:
            result = await client.call_tool("renew_membership", {"patron_id": "patron_lapsed01"})
        assert result.structured_content["renewed"] is True
        assert result.structured_content["status"] == "active"

    async def test_declined_renewal_is_a_normal_outcome(self, library):
        async def decline(message, response_type, params, context):
            return ElicitResult(action="decline")

        async with Client(server.mcp, elicitation_handler=decline) as client:
            result = await client.call_tool("renew_membership", {"patron_id": "patron_clean001"})
        data = result.structured_content
        assert data["renewed"] is False
        assert "decline" in data["message"]

    async def test_unknown_patron_is_tool_error(self, library):
        async with Client(server.mcp, elicitation_handler=_term_handler("6 months")) as client:
            with pytest.raises(ToolError, match="not found"):
                await client.call_tool("renew_membership", {"patron_id": "patron_missing99"})
