"""Protocol-level tests for the read-only MCP App tools."""

import json
from types import SimpleNamespace

import pytest
from fastmcp import Client, FastMCP

import apps_server
import server
from modern.context import ModernContext
from modern.meta import RequestMeta
from modern.registry import ModernRegistry
from modern.types import ClientCapabilities, Implementation
from tools import apps


@pytest.fixture
async def client(library):
    async with Client(server.mcp) as test_client:
        yield test_client


class TestAppDescriptors:
    async def test_app_only_server_exposes_no_mutating_tools(self, library):
        async with Client(apps_server.mcp) as app_client:
            tools = {tool.name for tool in await app_client.list_tools()}

        assert tools == {
            "browse_catalog_app",
            "library_dashboard_app",
            "patron_account_app",
        }

    async def test_app_tools_publish_ui_metadata_and_safety_hints(self, client):
        tools = {tool.name: tool for tool in await client.list_tools()}

        for name in ("browse_catalog_app", "library_dashboard_app", "patron_account_app"):
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

    async def test_renderer_publishes_configured_stable_domain(self, monkeypatch):
        monkeypatch.setattr(
            apps,
            "get_config",
            lambda: SimpleNamespace(base_url="https://library.example"),
        )
        mcp = FastMCP("domain-test")
        apps.register(mcp)

        async with Client(mcp) as app_client:
            resources = await app_client.list_resources()
            renderer = (await app_client.read_resource(resources[0].uri))[0]

        descriptor = renderer.model_dump(by_alias=True, exclude_none=True)
        assert descriptor["_meta"]["ui"]["domain"] == "https://library.example"

    async def test_modern_registry_exposes_standard_app_extension(self, library):
        registry = ModernRegistry()
        capabilities = registry.capabilities().to_wire()
        tools = {tool.name: tool.to_wire() for tool in registry.list_tools()}
        resources = {resource.uri: resource.to_wire() for resource in registry.list_resources()}

        assert capabilities["extensions"][apps.MCP_APPS_EXTENSION_ID] == {
            "mimeTypes": ["text/html;profile=mcp-app"]
        }
        assert tools["browse_catalog_app"]["_meta"] == {
            "ui": {"resourceUri": apps.PREFAB_RENDERER_URI}
        }
        assert resources[apps.PREFAB_RENDERER_URI]["mimeType"] == ("text/html;profile=mcp-app")

    async def test_modern_registry_reads_renderer_with_security_metadata(self, library):
        registry = ModernRegistry()
        context = ModernContext(
            meta=RequestMeta(
                protocol_version="2026-07-28",
                client_info=Implementation(name="test", version="1.0.0"),
                client_capabilities=ClientCapabilities(
                    extensions={
                        apps.MCP_APPS_EXTENSION_ID: {"mimeTypes": ["text/html;profile=mcp-app"]}
                    }
                ),
                log_level=None,
                progress_token=None,
                trace={},
            ),
            request_id=1,
            principal=None,
            memo={},
            notify=None,
            registry=registry,
        )

        contents = await registry.read_resource(apps.PREFAB_RENDERER_URI, context)

        assert contents[0]["mimeType"] == "text/html;profile=mcp-app"
        assert contents[0]["_meta"]["ui"]["csp"] == {
            "resourceDomains": ["https://cdn.jsdelivr.net"]
        }
        assert "<html" in contents[0]["text"].lower()


class TestAppBehavior:
    async def test_catalog_app_contains_filtered_book_data(self, client):
        result = await client.call_tool(
            "browse_catalog_app",
            {"genre": "fiction", "availability": "available"},
        )
        payload = json.dumps(result.structured_content, ensure_ascii=False)

        assert "The Available Book" in payload
        assert "The Popular Book" not in payload
        assert "Test Author" in payload
        assert "On-shelf titles only" in payload

    async def test_dashboard_contains_metrics_and_popular_books(self, client):
        result = await client.call_tool(
            "library_dashboard_app",
            {"days": 30, "popular_limit": 5},
        )
        payload = json.dumps(result.structured_content, ensure_ascii=False)

        assert "Virtual Library Dashboard" in payload
        assert "The Popular Book" in payload
        assert "Circulation rate" in payload

    async def test_patron_app_finds_account_without_patron_number(self, client):
        result = await client.call_tool("patron_account_app", {"query": "Clean Reader"})
        payload = json.dumps(result.structured_content, ensure_ascii=False)

        assert "Clean Reader" in payload
        assert "patron_clean001" not in payload
        assert "c••••@example.com" in payload
        assert "clean@example.com" not in payload
        assert "The Popular Book" in payload

    async def test_patron_app_explains_truncated_matches(self, client):
        result = await client.call_tool(
            "patron_account_app",
            {"query": "example.com", "limit": 1},
        )
        payload = json.dumps(result.structured_content, ensure_ascii=False)

        assert "Showing the first 1 of" in payload
        assert "narrow the list" in payload

    async def test_app_inputs_are_bounded(self, client):
        with pytest.raises(Exception, match="validation"):
            await client.call_tool("browse_catalog_app", {"limit": 0})

        with pytest.raises(Exception, match="two non-space"):
            await client.call_tool("patron_account_app", {"query": "  "})
