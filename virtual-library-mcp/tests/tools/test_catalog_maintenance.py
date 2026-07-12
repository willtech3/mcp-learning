"""Tests for catalog maintenance: progress, ToolResult, and maintenance mode."""

import pytest
from fastmcp import Client

import server


@pytest.fixture
async def client(library):
    async with Client(server.mcp) as c:
        yield c


class TestRegenerateCatalog:
    async def test_returns_summary_and_structured_content(self, client):
        result = await client.call_tool("regenerate_catalog", {})

        # ToolResult carries BOTH a human summary and machine-readable data.
        assert "completed successfully" in result.content[0].text
        data = result.structured_content
        assert data["status"] == "completed"
        assert set(data) >= {
            "integrity_check",
            "search_indexes",
            "circulation_stats",
            "recommendations_cache",
        }

    async def test_counts_reflect_seeded_library(self, client):
        result = await client.call_tool("regenerate_catalog", {})
        data = result.structured_content
        assert data["integrity_check"]["books_checked"] == 2
        assert data["circulation_stats"]["active_loans"] >= 0
        assert data["recommendations_cache"]["patrons_processed"] == 3

    async def test_progress_spans_all_stages(self, client):
        updates: list[float] = []

        async def on_progress(progress, total, message):
            updates.append(progress)

        await client.call_tool("regenerate_catalog", {}, progress_handler=on_progress)
        assert updates[-1] == 100
        assert min(updates) < 25  # early-stage progress was reported too

    async def test_recommendations_resource_restored_after_maintenance(self, client):
        """Maintenance disables the recommendations resource, then re-enables
        it (firing list_changed both times). Afterwards it must be visible."""
        await client.call_tool("regenerate_catalog", {})
        templates = await client.list_resource_templates()
        names = {t.name for t in templates}
        assert "Personalized Book Recommendations" in names

    async def test_list_changed_notifications_fired(self, library):
        """Clients receive resources/list_changed for disable and enable."""
        import asyncio

        from fastmcp.client.messages import MessageHandler

        seen: list[str] = []

        class Recorder(MessageHandler):
            async def on_resource_list_changed(self, notification) -> None:
                seen.append("resources/list_changed")

        async with Client(server.mcp, message_handler=Recorder()) as client:
            await client.call_tool("regenerate_catalog", {})
            # Notifications ride the stream asynchronously; yield so the
            # client task can process them before we assert.
            await asyncio.sleep(0.1)

        assert len(seen) >= 2  # one for disable, one for enable
