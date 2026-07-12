"""Protocol-level tests for the read-only MCP App tools."""

import json

import pytest
from fastmcp import Client

import apps_server
import server


@pytest.fixture
async def client(library):
    async with Client(server.mcp) as test_client:
        yield test_client


class TestAppDescriptors:
    async def test_app_only_server_exposes_no_mutating_tools(self, library):
        async with Client(apps_server.mcp) as app_client:
            tools = {tool.name for tool in await app_client.list_tools()}

        assert tools == {"browse_catalog_app", "library_dashboard_app"}

    async def test_app_tools_publish_ui_metadata_and_safety_hints(self, client):
        tools = {tool.name: tool for tool in await client.list_tools()}

        for name in ("browse_catalog_app", "library_dashboard_app"):
            descriptor = tools[name].model_dump(by_alias=True, exclude_none=True)
            assert descriptor["annotations"] == {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            }
            assert descriptor["_meta"]["ui"]["resourceUri"].startswith("ui://")

    async def test_prefab_renderer_resource_is_registered(self, client):
        resources = await client.list_resources()
        renderers = [resource for resource in resources if str(resource.uri).startswith("ui://")]

        assert renderers
        renderer = (await client.read_resource(renderers[0].uri))[0]
        assert renderer.mimeType == "text/html;profile=mcp-app"


class TestAppBehavior:
    async def test_catalog_app_contains_filtered_book_data(self, client):
        result = await client.call_tool(
            "browse_catalog_app",
            {"genre": "fiction", "availability": "available"},
        )
        payload = json.dumps(result.structured_content)

        assert "The Available Book" in payload
        assert "The Popular Book" not in payload
        assert "Test Author" in payload

    async def test_dashboard_contains_metrics_and_popular_books(self, client):
        result = await client.call_tool(
            "library_dashboard_app",
            {"days": 30, "popular_limit": 5},
        )
        payload = json.dumps(result.structured_content)

        assert "Virtual Library Dashboard" in payload
        assert "The Popular Book" in payload
        assert "Circulation rate" in payload

    async def test_app_inputs_are_bounded(self, client):
        with pytest.raises(Exception, match="validation"):
            await client.call_tool("browse_catalog_app", {"limit": 0})
