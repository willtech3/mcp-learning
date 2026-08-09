"""Tests for human-friendly, privacy-minimized patron discovery."""

import pytest
from fastmcp import Client

import server


@pytest.fixture
async def client(library):
    async with Client(server.mcp) as test_client:
        yield test_client


class TestPatronSearchSchema:
    async def test_tool_is_read_only_and_uses_string_query(self, client):
        tools = {tool.name: tool for tool in await client.list_tools()}
        tool = tools["find_patron"]

        assert tool.inputSchema["required"] == ["query"]
        assert tool.inputSchema["properties"]["query"]["type"] == "string"
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.idempotentHint is True
        assert tool.annotations.openWorldHint is False


class TestPatronSearchBehavior:
    async def test_name_search_returns_masked_identity_hint(self, client):
        result = await client.call_tool("find_patron", {"query": "Clean Reader"})
        payload = result.structured_content

        assert payload["total_matches"] == 1
        assert payload["patrons"][0]["patron_id"] == "patron_clean001"
        assert payload["patrons"][0]["email_hint"] == "c••••@example.com"
        assert "clean@example.com" not in str(payload)

    async def test_email_search_finds_account_without_card_number(self, client):
        result = await client.call_tool("find_patron", {"query": "fined@example.com"})

        assert result.structured_content["patrons"][0]["patron_id"] == "patron_fines001"

    async def test_no_matches_is_a_normal_empty_result(self, client):
        result = await client.call_tool("find_patron", {"query": "Nobody Here"})

        assert result.structured_content["total_matches"] == 0
        assert result.structured_content["patrons"] == []

    async def test_blank_query_is_rejected(self, client):
        with pytest.raises(Exception, match="two non-space"):
            await client.call_tool("find_patron", {"query": "  "})
