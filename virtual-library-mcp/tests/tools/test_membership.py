"""Tests for renew_membership — interactive and stateless-safe renewal paths.

Sessionful clients can elicit the term mid-execution. Stateless clients ask
the user first and retry with the same explicit term argument.
"""

from datetime import date, timedelta
from types import SimpleNamespace

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

    async def test_stateless_client_fails_closed_then_accepts_explicit_term(
        self, library, monkeypatch
    ):
        patron = library.get(PatronDB, "patron_clean001")
        original_expiration = patron.expiration_date
        monkeypatch.setattr(
            "tools.interaction.get_config",
            lambda: SimpleNamespace(
                transport="http",
                http_stateless=True,
                elicitation_timeout_seconds=20,
            ),
        )

        async with Client(server.mcp) as client:
            with pytest.raises(ToolError, match="retry with the term argument"):
                await client.call_tool("renew_membership", {"patron_id": "patron_clean001"})
            library.refresh(patron)
            assert patron.expiration_date == original_expiration

            result = await client.call_tool(
                "renew_membership",
                {"patron_id": "patron_clean001", "term": "6 months"},
            )

        assert result.structured_content["renewed"] is True
        assert result.structured_content["term"] == "6 months"
