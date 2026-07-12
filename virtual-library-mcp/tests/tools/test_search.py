"""Tests for the search_catalog tool through the MCP protocol path.

These run against the real server via the FastMCP in-memory client, so
they verify what an actual MCP client experiences: the generated input
schema, structured output, annotations, and ToolError conversion.
"""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import server


@pytest.fixture
async def client(library):
    async with Client(server.mcp) as c:
        yield c


class TestSearchSchema:
    """The generated input schema is the contract the LLM sees."""

    async def test_input_schema_has_real_parameters(self, client):
        tools = {t.name: t for t in await client.list_tools()}
        schema = tools["search_catalog"].inputSchema
        assert set(schema["properties"]) >= {
            "query",
            "genre",
            "author",
            "available_only",
            "page",
            "page_size",
            "sort_by",
            "sort_desc",
        }

    async def test_output_schema_published(self, client):
        tools = {t.name: t for t in await client.list_tools()}
        out = tools["search_catalog"].outputSchema
        assert out is not None
        assert "books" in out["properties"]

    async def test_annotations_mark_read_only(self, client):
        tools = {t.name: t for t in await client.list_tools()}
        annotations = tools["search_catalog"].annotations
        assert annotations is not None
        assert annotations.readOnlyHint is True

    async def test_components_have_icons(self, client):
        """SEP-973: tools expose icon metadata for client UIs."""
        tools = {t.name: t for t in await client.list_tools()}
        icons = tools["search_catalog"].icons
        assert icons
        assert icons[0].src.startswith("data:image/svg+xml")


class TestSearchBehavior:
    async def test_search_by_query(self, client):
        result = await client.call_tool("search_catalog", {"query": "Available"})
        data = result.structured_content
        assert data["pagination"]["total"] == 1
        assert data["books"][0]["title"] == "The Available Book"
        assert data["books"][0]["is_available"] is True

    async def test_search_by_genre_is_case_insensitive(self, client):
        result = await client.call_tool("search_catalog", {"genre": "science fiction"})
        data = result.structured_content
        assert data["pagination"]["total"] == 1
        assert data["books"][0]["isbn"] == "9780134685007"

    async def test_search_by_author_partial_match(self, client):
        result = await client.call_tool("search_catalog", {"author": "test"})
        assert result.structured_content["pagination"]["total"] == 2

    async def test_available_only_filters_out_zero_copy_books(self, client):
        result = await client.call_tool(
            "search_catalog", {"genre": "Science Fiction", "available_only": True}
        )
        assert result.structured_content["pagination"]["total"] == 0

    async def test_no_criteria_is_a_tool_error(self, client):
        with pytest.raises(ToolError, match="at least one search criterion"):
            await client.call_tool("search_catalog", {})

    async def test_schema_rejects_out_of_range_page(self, client):
        with pytest.raises(ToolError):
            await client.call_tool("search_catalog", {"query": "x", "page": 0})

    async def test_no_results_message(self, client):
        result = await client.call_tool("search_catalog", {"query": "zzz-no-such-book"})
        assert "No books found" in result.structured_content["summary"]

    async def test_pagination_metadata(self, client):
        result = await client.call_tool("search_catalog", {"author": "test", "page_size": 1})
        page = result.structured_content["pagination"]
        assert page["total"] == 2
        assert page["total_pages"] == 2
        assert page["has_next"] is True
