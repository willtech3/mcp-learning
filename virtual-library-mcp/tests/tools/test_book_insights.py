"""Tests for book insights — sampling, tool-enabled sampling, and fallback.

The in-memory client either provides a sampling_handler (simulating a
client whose LLM answers the server's request) or omits it (simulating a
client without the sampling capability, which must trigger fallback).
"""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import server
from tools.book_insights import search_library_catalog


@pytest.fixture
def sampling_calls():
    return []


@pytest.fixture
async def sampling_client(library, sampling_calls):
    """Client that 'runs' sampling requests with a canned response."""

    async def handler(messages, params, context):
        sampling_calls.append(params)
        return "A thoughtful AI-generated analysis of the book."

    async with Client(server.mcp, sampling_handler=handler) as c:
        yield c


@pytest.fixture
async def plain_client(library):
    """Client WITHOUT sampling support."""
    async with Client(server.mcp) as c:
        yield c


class TestSamplingPath:
    async def test_summary_uses_client_llm(self, sampling_client, sampling_calls):
        result = await sampling_client.call_tool(
            "generate_book_insights",
            {"isbn": "9780134685991", "insight_type": "summary"},
        )
        text = result.content[0].text
        assert "AI-Generated Summary" in text
        assert "thoughtful AI-generated analysis" in text
        assert len(sampling_calls) == 1

    async def test_model_preferences_are_hints(self, sampling_client, sampling_calls):
        await sampling_client.call_tool(
            "generate_book_insights",
            {"isbn": "9780134685991", "insight_type": "themes"},
        )
        prefs = sampling_calls[0].modelPreferences
        assert prefs is not None
        assert prefs.hints[0].name == "claude-opus-4-8"

    async def test_unknown_isbn_is_tool_error(self, sampling_client):
        with pytest.raises(ToolError, match="not found"):
            await sampling_client.call_tool("generate_book_insights", {"isbn": "9990000000000"})


class TestFallbackPath:
    async def test_summary_falls_back_without_sampling(self, plain_client):
        result = await plain_client.call_tool(
            "generate_book_insights",
            {"isbn": "9780134685991", "insight_type": "summary"},
        )
        text = result.content[0].text
        assert "Book Information" in text
        assert "The Available Book" in text

    async def test_each_insight_type_has_meaningful_fallback(self, plain_client):
        for insight_type in ("themes", "discussion_questions", "similar_books"):
            result = await plain_client.call_tool(
                "generate_book_insights",
                {"isbn": "9780134685991", "insight_type": insight_type},
            )
            assert "sampling support" in result.content[0].text


class TestToolEnabledSampling:
    """SEP-1577: the similar_books insight hands the client's LLM a tool."""

    async def test_similar_books_offers_catalog_tool(self, library):
        from mcp.types import SamplingCapability, SamplingToolsCapability

        seen_tools: list = []

        async def handler(messages, params, context):
            seen_tools.extend(getattr(params, "tools", None) or [])
            return "Grounded recommendations citing real holdings."

        async with Client(
            server.mcp,
            sampling_handler=handler,
            # SEP-1577: the client must advertise sampling.tools support,
            # otherwise the server refuses to send tools with the request.
            sampling_capabilities=SamplingCapability(tools=SamplingToolsCapability()),
        ) as client:
            result = await client.call_tool(
                "generate_book_insights",
                {"isbn": "9780134685991", "insight_type": "similar_books"},
            )

        assert "Grounded recommendations" in result.content[0].text
        assert any(t.name == "search_library_catalog" for t in seen_tools)

    def test_catalog_search_tool_returns_real_holdings(self, library):
        rows = search_library_catalog("Science Fiction")
        assert rows == [
            {
                "title": "The Popular Book",
                "isbn": "9780134685007",
                "genre": "Science Fiction",
                "year": 2021,
                "available": False,
            }
        ]
