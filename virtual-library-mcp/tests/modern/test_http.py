"""
Tests for modern/http.py — the Streamable HTTP binding + dual-era endpoint.

MCP 2026-07-28 rebuilt Streamable HTTP (SEP-2243, SEP-2567, SEP-2575):
sessions and the GET stream are gone, every POST self-describes via headers
mirrored from the body, and error codes ride meaningful HTTP statuses.
These tests pin:

- the dual-era classification matrix (Versioning: Backward Compatibility):
  which POSTs reach the legacy FastMCP app vs the modern pipeline, GET and
  DELETE always going legacy, batch bodies rejected outright;
- SEP-2243 header validation: every -32020 HeaderMismatch trigger (missing
  or mismatched MCP-Protocol-Version / Mcp-Method / Mcp-Name, Base64
  sentinel decoding, Mcp-Param-{Name} vs x-mcp-header annotations);
- HTTP status mapping: -32601 rides 404, -32603 rides 500, everything else
  400; notification POSTs get 202 with no body;
- response modes: buffered application/json by default, request-scoped SSE
  when the request carries progressToken or the deprecated logLevel key;
- Origin validation (403) and pluggable Bearer auth (401/403 challenges).

The dispatcher is a stub coded against the modern/dispatcher.py contract:
it validates ``_meta`` first (parse_request_meta) exactly like the real one,
then returns canned complete JSON-RPC responses or raises McpErrors.
"""

import asyncio
import json
from typing import Any

import httpx
import pytest
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from modern.errors import MethodNotFoundError
from modern.http import create_dual_era_app, create_modern_asgi
from modern.meta import encode_header_value, parse_request_meta
from modern.types import (
    HEADER_MISMATCH,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    META_CLIENT_CAPS,
    META_CLIENT_INFO,
    META_LOG_LEVEL,
    META_PROGRESS_TOKEN,
    META_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    PROTOCOL_VERSION,
    SUPPORTED_VERSIONS,
    UNSUPPORTED_PROTOCOL_VERSION,
)

# ---------------------------------------------------------------------------
# Helpers and stubs
# ---------------------------------------------------------------------------


def make_meta(version: str = PROTOCOL_VERSION, **overrides: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {
        META_PROTOCOL_VERSION: version,
        META_CLIENT_INFO: {"name": "TestClient", "version": "1.0.0"},
        META_CLIENT_CAPS: {},
    }
    meta.update(overrides)
    return meta


def make_request(
    method: str,
    params: dict[str, Any] | None = None,
    request_id: int = 1,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body_params = dict(params or {})
    body_params["_meta"] = meta if meta is not None else make_meta()
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": body_params}


def modern_headers(
    method: str,
    name: str | None = None,
    version: str = PROTOCOL_VERSION,
    **extra: str,
) -> dict[str, str]:
    headers = {
        "MCP-Protocol-Version": version,
        "Mcp-Method": method,
        "Accept": "application/json, text/event-stream",
    }
    if name is not None:
        headers["Mcp-Name"] = name
    headers.update(extra)
    return headers


def parse_sse(body: str) -> list[dict[str, Any]]:
    events = []
    for chunk in body.split("\n\n"):
        data_lines = [
            line.removeprefix("data:").lstrip()
            for line in chunk.split("\n")
            if line.startswith("data:")
        ]
        if data_lines:
            events.append(json.loads("\n".join(data_lines)))
    return events


#: A tool schema exercising x-mcp-header (SEP-2243), including a nested
#: property reachable through a pure `properties` chain.
EXECUTE_SQL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "region": {"type": "string", "x-mcp-header": "Region"},
        "shard": {"type": "integer", "x-mcp-header": "Shard"},
        "dry_run": {"type": "boolean", "x-mcp-header": "Dry-Run"},
        "options": {
            "type": "object",
            "properties": {
                "tenant": {"type": "string", "x-mcp-header": "Tenant"},
            },
        },
        "query": {"type": "string"},
    },
    "required": ["query"],
}


class StubDispatcher:
    """Canned dispatcher honoring the modern/dispatcher.py contract.

    Like the real dispatcher, ``_meta`` validation runs before method
    routing, so -32602 / -32022 failures surface exactly as they would in
    production.  Returned dicts are complete JSON-RPC responses.
    """

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.envs: list[Any] = []

    async def handle(self, message: dict[str, Any], env: Any) -> Any:
        self.messages.append(message)
        self.envs.append(env)
        parse_request_meta(message.get("params"))
        method = message["method"]
        request_id = message["id"]
        if method == "tools/list":
            return self._result(
                request_id,
                {"resultType": "complete", "tools": [], "ttlMs": 300000, "cacheScope": "public"},
            )
        if method == "tools/call":
            return await self._call_tool(message, env)
        if method == "resources/read":
            uri = message["params"]["uri"]
            return self._result(
                request_id,
                {
                    "resultType": "complete",
                    "contents": [{"uri": uri, "text": "ok"}],
                    "ttlMs": 0,
                    "cacheScope": "private",
                },
            )
        if method == "prompts/get":
            return self._result(
                request_id,
                {"resultType": "complete", "messages": []},
            )
        raise MethodNotFoundError(f"Method '{method}' is not part of MCP 2026-07-28")

    async def _call_tool(self, message: dict[str, Any], env: Any) -> dict[str, Any]:
        request_id = message["id"]
        name = message["params"]["name"]
        if name == "explode":
            raise RuntimeError("handler blew up (details must not leak to the wire)")
        if name == "long_task":
            token = message["params"]["_meta"].get(META_PROGRESS_TOKEN, "tok")
            for step in (1, 2):
                await env.notify(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/progress",
                        "params": {"progressToken": token, "progress": step, "total": 2},
                    }
                )
        return self._result(
            request_id,
            {
                "resultType": "complete",
                "content": [{"type": "text", "text": f"called {name}"}],
            },
        )

    @staticmethod
    def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


class LegacyStubApp:
    """Recorder standing in for the FastMCP legacy ASGI app."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        body = b""
        if scope["type"] == "http" and scope.get("method") == "POST":
            while True:
                message = await receive()
                if message["type"] != "http.request":
                    break
                body += message.get("body", b"")
                if not message.get("more_body", False):
                    break
        self.calls.append({"method": scope.get("method"), "path": scope.get("path"), "body": body})
        payload = b'{"era": "legacy"}'
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload, "more_body": False})


def make_client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def make_modern(**kwargs: Any) -> tuple[Any, StubDispatcher]:
    dispatcher = StubDispatcher()
    return create_modern_asgi(dispatcher, **kwargs), dispatcher


# ---------------------------------------------------------------------------
# Era classification (dual-era front door)
# ---------------------------------------------------------------------------


class TestEraClassification:
    def dual_app(self, **modern_kwargs: Any) -> tuple[Any, StubDispatcher, LegacyStubApp]:
        modern, dispatcher = make_modern(**modern_kwargs)
        legacy = LegacyStubApp()
        return create_dual_era_app(modern, legacy), dispatcher, legacy

    async def test_legacy_version_header_routes_to_legacy(self):
        app, dispatcher, legacy = self.dual_app()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                headers={"MCP-Protocol-Version": "2025-11-25"},
            )
        assert response.json() == {"era": "legacy"}
        assert len(legacy.calls) == 1
        # The buffered body was replayed intact to the legacy app.
        assert json.loads(legacy.calls[0]["body"])["method"] == "tools/list"
        assert dispatcher.messages == []

    async def test_initialize_routes_to_legacy_even_without_header(self):
        app, dispatcher, legacy = self.dual_app()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
        assert response.json() == {"era": "legacy"}
        assert len(legacy.calls) == 1
        assert dispatcher.messages == []

    async def test_modern_header_routes_to_modern(self):
        app, dispatcher, legacy = self.dual_app()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("tools/list"),
                headers=modern_headers("tools/list"),
            )
        assert response.status_code == 200
        assert response.json()["result"]["resultType"] == "complete"
        assert legacy.calls == []
        assert dispatcher.messages[0]["method"] == "tools/list"

    async def test_unknown_header_version_reaches_modern_and_gets_32022(self):
        """An unrecognized version is a MODERN client — the modern pipeline
        owns rejecting it with -32022 and the supported list."""
        app, _, legacy = self.dual_app()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("tools/list", meta=make_meta(version="1900-01-01")),
                headers=modern_headers("tools/list", version="1900-01-01"),
            )
        assert legacy.calls == []
        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == UNSUPPORTED_PROTOCOL_VERSION
        assert error["data"]["requested"] == "1900-01-01"
        assert error["data"]["supported"] == list(SUPPORTED_VERSIONS)

    async def test_modern_meta_without_header_routes_modern_then_32020(self):
        """Modern _meta in the body marks a modern client even without the
        header — which the modern pipeline then rejects as missing (a modern
        client MUST send MCP-Protocol-Version)."""
        app, _, legacy = self.dual_app()
        async with make_client(app) as client:
            response = await client.post("/mcp", json=make_request("tools/list"))
        assert legacy.calls == []
        assert response.status_code == 400
        assert response.json()["error"]["code"] == HEADER_MISMATCH

    async def test_ambiguous_request_defaults_to_legacy(self):
        """No header, no modern _meta: pre-2025-06-18 clients look exactly
        like this, so ambiguity MUST fall to legacy."""
        app, dispatcher, legacy = self.dual_app()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
        assert response.json() == {"era": "legacy"}
        assert len(legacy.calls) == 1
        assert dispatcher.messages == []

    @pytest.mark.parametrize("http_method", ["GET", "DELETE"])
    async def test_get_and_delete_route_to_legacy(self, http_method: str):
        """GET (SSE stream) and DELETE (session teardown) exist only in the
        legacy binding; a modern-only deployment would answer 405 instead."""
        app, _, legacy = self.dual_app()
        async with make_client(app) as client:
            response = await client.request(http_method, "/mcp")
        assert response.json() == {"era": "legacy"}
        assert legacy.calls[0]["method"] == http_method

    async def test_batch_array_body_rejected_before_classification(self):
        app, dispatcher, legacy = self.dual_app()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=[{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}],
                headers=modern_headers("tools/list"),
            )
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == INVALID_REQUEST
        assert "id" not in body  # id is unreadable from an array body
        assert legacy.calls == []
        assert dispatcher.messages == []

    async def test_session_and_resume_headers_ignored_on_modern_path(self):
        """SEP-2567/SEP-2575: Mcp-Session-Id and Last-Event-ID are ignored —
        the request succeeds and no session id is minted or echoed."""
        app, _, legacy = self.dual_app()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("tools/list"),
                headers=modern_headers(
                    "tools/list",
                    **{"Mcp-Session-Id": "stale-session", "Last-Event-ID": "42"},
                ),
            )
        assert response.status_code == 200
        assert "mcp-session-id" not in response.headers
        assert legacy.calls == []

    async def test_non_mcp_paths_route_by_modern_route_table(self):
        async def prm(_request: Any) -> PlainTextResponse:
            return PlainTextResponse("prm")

        modern, _ = make_modern(
            extra_routes=[Route("/.well-known/oauth-protected-resource", prm, methods=["GET"])]
        )
        legacy = LegacyStubApp()
        app = create_dual_era_app(modern, legacy)
        async with make_client(app) as client:
            prm_response = await client.get("/.well-known/oauth-protected-resource")
            other_response = await client.get("/some/legacy/page")
        # A path the modern app registered is served by it...
        assert prm_response.text == "prm"
        # ...anything else falls through to the legacy app.
        assert other_response.json() == {"era": "legacy"}
        assert [call["path"] for call in legacy.calls] == ["/some/legacy/page"]


# ---------------------------------------------------------------------------
# Header validation (SEP-2243) — every -32020 trigger
# ---------------------------------------------------------------------------


class TestHeaderValidation:
    async def assert_mismatch(
        self, body: dict[str, Any], headers: dict[str, str], expect_id: Any = 1
    ) -> dict[str, Any]:
        app, dispatcher = make_modern()
        async with make_client(app) as client:
            response = await client.post("/mcp", json=body, headers=headers)
        assert response.status_code == 400
        payload = response.json()
        assert payload["error"]["code"] == HEADER_MISMATCH
        assert payload["id"] == expect_id
        # Validation failed BEFORE dispatch — the mirror must be verified
        # before the body is acted on.
        assert dispatcher.messages == []
        return payload

    async def test_missing_protocol_version_header(self):
        headers = modern_headers("tools/list")
        del headers["MCP-Protocol-Version"]
        await self.assert_mismatch(make_request("tools/list"), headers)

    async def test_protocol_version_header_body_mismatch(self):
        await self.assert_mismatch(
            make_request("tools/list"),  # body says 2026-07-28
            modern_headers("tools/list", version="2030-01-01"),
        )

    async def test_missing_mcp_method_header(self):
        headers = modern_headers("tools/list")
        del headers["Mcp-Method"]
        await self.assert_mismatch(make_request("tools/list"), headers)

    async def test_mcp_method_header_body_mismatch(self):
        await self.assert_mismatch(
            make_request("tools/list"),
            modern_headers("tools/call"),  # header names a different method
        )

    @pytest.mark.parametrize(
        ("method", "params"),
        [
            ("tools/call", {"name": "search_catalog", "arguments": {}}),
            ("resources/read", {"uri": "library://books/1"}),
            ("prompts/get", {"name": "recommend_book"}),
        ],
    )
    async def test_missing_mcp_name_header_on_name_addressed_methods(
        self, method: str, params: dict[str, Any]
    ):
        await self.assert_mismatch(make_request(method, params), modern_headers(method))

    async def test_mcp_name_header_body_mismatch(self):
        await self.assert_mismatch(
            make_request("tools/call", {"name": "search_catalog", "arguments": {}}),
            modern_headers("tools/call", name="different_tool"),
        )

    async def test_malformed_base64_sentinel_is_header_mismatch(self):
        await self.assert_mismatch(
            make_request("tools/call", {"name": "search_catalog", "arguments": {}}),
            modern_headers("tools/call", name="=?base64?!!!not-base64!!!?="),
        )

    async def test_sentinel_encoded_mcp_name_decodes_and_matches(self):
        """Resource URIs may not be header-safe; the =?base64?...?= sentinel
        carries them (SEP-2243 value encoding)."""
        uri = "library://books/世界"  # non-ASCII -> MUST be sentinel-encoded
        app, dispatcher = make_modern()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("resources/read", {"uri": uri}),
                headers=modern_headers("resources/read", name=encode_header_value(uri)),
            )
        assert response.status_code == 200
        assert response.json()["result"]["contents"][0]["uri"] == uri
        assert dispatcher.messages[0]["params"]["uri"] == uri

    async def test_mcp_name_not_required_for_other_methods(self):
        app, _ = make_modern()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("tools/list"),
                headers=modern_headers("tools/list"),  # no Mcp-Name
            )
        assert response.status_code == 200

    async def test_header_names_are_case_insensitive(self):
        app, _ = make_modern()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                content=json.dumps(
                    make_request("tools/call", {"name": "search_catalog", "arguments": {}})
                ),
                headers={
                    "content-type": "application/json",
                    "mcp-protocol-version": PROTOCOL_VERSION,
                    "MCP-METHOD": "tools/call",
                    "mcp-name": "search_catalog",
                },
            )
        assert response.status_code == 200


class TestMcpParamHeaders:
    """SEP-2243 custom headers: x-mcp-header annotations -> Mcp-Param-{Name}."""

    def app_with_schema(self) -> tuple[Any, StubDispatcher]:
        return make_modern(
            tool_schema_lookup=lambda name: EXECUTE_SQL_SCHEMA if name == "execute_sql" else None
        )

    def call_body(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return make_request("tools/call", {"name": "execute_sql", "arguments": arguments})

    async def post(
        self, arguments: dict[str, Any], extra_headers: dict[str, str]
    ) -> httpx.Response:
        app, _ = self.app_with_schema()
        headers = modern_headers("tools/call", name="execute_sql", **extra_headers)
        async with make_client(app) as client:
            return await client.post("/mcp", json=self.call_body(arguments), headers=headers)

    async def test_matching_param_header_accepted(self):
        response = await self.post(
            {"region": "us-west1", "query": "SELECT 1"},
            {"Mcp-Param-Region": "us-west1"},
        )
        assert response.status_code == 200

    async def test_mismatched_param_header_rejected(self):
        response = await self.post(
            {"region": "us-west1", "query": "SELECT 1"},
            {"Mcp-Param-Region": "eu-central1"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == HEADER_MISMATCH

    async def test_value_in_body_but_header_omitted_rejected(self):
        """Behavior table: client omits the header while the annotated value
        is present in the body -> non-conforming client, MUST reject."""
        response = await self.post({"region": "us-west1", "query": "SELECT 1"}, {})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == HEADER_MISMATCH

    async def test_header_present_but_argument_absent_rejected(self):
        response = await self.post(
            {"query": "SELECT 1"},
            {"Mcp-Param-Region": "us-west1"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == HEADER_MISMATCH

    async def test_integer_params_compare_numerically(self):
        """Spec SHOULD: compare integers numerically, so '42.0' == 42."""
        response = await self.post(
            {"shard": 42, "query": "SELECT 1"},
            {"Mcp-Param-Shard": "42.0"},
        )
        assert response.status_code == 200

    async def test_boolean_params_mirror_as_lowercase_words(self):
        ok = await self.post({"dry_run": True, "query": "SELECT 1"}, {"Mcp-Param-Dry-Run": "true"})
        assert ok.status_code == 200
        bad = await self.post(
            {"dry_run": False, "query": "SELECT 1"}, {"Mcp-Param-Dry-Run": "true"}
        )
        assert bad.status_code == 400

    async def test_nested_property_via_properties_chain(self):
        response = await self.post(
            {"options": {"tenant": "acme"}, "query": "SELECT 1"},
            {"Mcp-Param-Tenant": "acme"},
        )
        assert response.status_code == 200

    async def test_sentinel_encoded_param_value(self):
        value = "Hello, 世界"
        response = await self.post(
            {"region": value, "query": "SELECT 1"},
            {"Mcp-Param-Region": encode_header_value(value)},
        )
        assert response.status_code == 200

    async def test_unrecognized_mcp_param_headers_are_ignored(self):
        """RFC 9110: headers matching no annotation are forwarded/ignored."""
        response = await self.post(
            {"query": "SELECT 1"},
            {"Mcp-Param-Totally-Unknown": "whatever"},
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Request/response mechanics, error-status mapping
# ---------------------------------------------------------------------------


class TestRequestResponses:
    async def test_plain_request_gets_buffered_json_response(self):
        app, _ = make_modern()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("tools/call", {"name": "search_catalog", "arguments": {}}),
                headers=modern_headers("tools/call", name="search_catalog"),
            )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        payload = response.json()
        assert payload["id"] == 1
        assert payload["result"]["resultType"] == "complete"

    async def test_unknown_method_is_http_404_with_32601_body(self):
        """The JSON-RPC body distinguishes this 404 from a legacy HTTP+SSE
        server's bare 404 — that difference IS the era-detection signal."""
        app, _ = make_modern()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("resources/subscribe", {"uri": "library://books/1"}),
                headers=modern_headers("resources/subscribe"),
            )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == METHOD_NOT_FOUND

    async def test_handler_crash_is_500_with_32603_and_no_leak(self):
        app, _ = make_modern()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("tools/call", {"name": "explode", "arguments": {}}),
                headers=modern_headers("tools/call", name="explode"),
            )
        assert response.status_code == 500
        error = response.json()["error"]
        assert error["code"] == INTERNAL_ERROR
        assert "blew up" not in error["message"]  # internals stay server-side

    async def test_notification_post_gets_202_without_mcp_method(self):
        """Notification POSTs: 202 Accepted, no body — and the spec defines
        no header requirements for them, so no Mcp-Method is demanded."""
        app, dispatcher = make_modern()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "notifications/cancelled",
                    "params": {"requestId": 42},
                },
                headers={"MCP-Protocol-Version": PROTOCOL_VERSION},
            )
        assert response.status_code == 202
        assert response.content == b""
        assert dispatcher.messages == []  # not dispatched: http layer 202s

    async def test_array_body_rejected_on_modern_app_too(self):
        app, _ = make_modern()
        async with make_client(app) as client:
            response = await client.post("/mcp", json=[], headers=modern_headers("tools/list"))
        assert response.status_code == 400
        assert response.json()["error"]["code"] == INVALID_REQUEST

    async def test_invalid_json_is_parse_error(self):
        app, _ = make_modern()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                content=b"{not json",
                headers={**modern_headers("tools/list"), "content-type": "application/json"},
            )
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == PARSE_ERROR
        assert "id" not in body

    @pytest.mark.parametrize(
        "message",
        [
            "just a string",
            {"id": 1, "method": "tools/list"},  # missing jsonrpc
            {"jsonrpc": "1.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 1},  # missing method
        ],
    )
    async def test_non_request_shapes_are_invalid_request(self, message: Any):
        app, _ = make_modern()
        async with make_client(app) as client:
            response = await client.post("/mcp", json=message, headers=modern_headers("tools/list"))
        assert response.status_code == 400
        assert response.json()["error"]["code"] == INVALID_REQUEST

    async def test_null_id_is_invalid_request(self):
        """MCP is stricter than JSON-RPC: ids MUST be string or integer."""
        app, _ = make_modern()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": None, "method": "tools/list", "params": {}},
                headers=modern_headers("tools/list"),
            )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == INVALID_REQUEST

    async def test_missing_meta_trio_is_invalid_params_400(self):
        app, _ = make_modern()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                headers=modern_headers("tools/list"),
            )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == INVALID_PARAMS

    async def test_get_on_modern_only_app_is_405(self):
        """Without the dual-era front door there is no legacy fallback:
        the single MCP endpoint supports POST only."""
        app, _ = make_modern()
        async with make_client(app) as client:
            response = await client.get("/mcp")
        assert response.status_code == 405


# ---------------------------------------------------------------------------
# Response streaming (request-scoped SSE)
# ---------------------------------------------------------------------------


class TestSseResponses:
    async def test_progress_token_switches_response_to_sse(self):
        app, _ = make_modern()
        meta = make_meta(**{META_PROGRESS_TOKEN: "tok-1"})
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("tools/call", {"name": "long_task", "arguments": {}}, meta=meta),
                headers=modern_headers("tools/call", name="long_task"),
            )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        # No SSE ids anywhere: resumability was removed (SEP-2575).
        assert "\nid:" not in response.text
        assert not response.text.startswith("id:")

        events = parse_sse(response.text)
        assert [e.get("method") for e in events[:2]] == [
            "notifications/progress",
            "notifications/progress",
        ]
        assert events[0]["params"]["progressToken"] == "tok-1"
        assert events[0]["params"]["progress"] == 1
        # The final JSON-RPC response terminates the stream.
        final = events[-1]
        assert final["id"] == 1
        assert final["result"]["resultType"] == "complete"

    async def test_progress_token_does_not_bury_error_status(self):
        """Regression: a request carrying progressToken must NOT get an HTTP
        200 SSE stream when it actually errors. -32601 rides 404 (transport
        MUST); an early error emits no notifications, so the response is a
        buffered JSON error with the correct status — never a committed 200
        stream that hides it (and defeats the era-detection beacon)."""
        app, _ = make_modern()
        meta = make_meta(**{META_PROGRESS_TOKEN: "tok-err"})
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("resources/subscribe", {}, meta=meta),
                headers=modern_headers("resources/subscribe"),
            )
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["error"]["code"] == -32601

    async def test_log_level_meta_also_switches_to_sse(self):
        """io.modelcontextprotocol/logLevel (deprecated, SEP-2577) is the
        other opt-in marker for request-scoped streaming."""
        app, _ = make_modern()
        meta = make_meta(**{META_LOG_LEVEL: "info"})
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request(
                    "tools/call", {"name": "search_catalog", "arguments": {}}, meta=meta
                ),
                headers=modern_headers("tools/call", name="search_catalog"),
            )
        assert response.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(response.text)
        assert events[-1]["result"]["resultType"] == "complete"

    async def test_without_markers_response_stays_plain_json(self):
        app, _ = make_modern()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("tools/call", {"name": "search_catalog", "arguments": {}}),
                headers=modern_headers("tools/call", name="search_catalog"),
            )
        assert response.headers["content-type"].startswith("application/json")


# ---------------------------------------------------------------------------
# Origin validation
# ---------------------------------------------------------------------------


class TestOriginValidation:
    async def test_disallowed_origin_is_403(self):
        app, dispatcher = make_modern()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("tools/list"),
                headers=modern_headers("tools/list", Origin="https://evil.example"),
            )
        assert response.status_code == 403
        # Body MAY be a JSON-RPC error with no id (spec) — ours is.
        assert "id" not in response.json()
        assert dispatcher.messages == []

    async def test_loopback_origin_allowed_by_default(self):
        app, _ = make_modern()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("tools/list"),
                headers=modern_headers("tools/list", Origin="http://localhost:6274"),
            )
        assert response.status_code == 200

    async def test_configured_origin_allowed(self):
        app, _ = make_modern(allowed_origins=["https://inspector.example"])
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("tools/list"),
                headers=modern_headers("tools/list", Origin="https://inspector.example"),
            )
        assert response.status_code == 200

    async def test_absent_origin_is_accepted(self):
        """Non-browser clients send no Origin; only a PRESENT invalid origin
        is rejected."""
        app, _ = make_modern()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("tools/list"),
                headers=modern_headers("tools/list"),
            )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Bearer auth integration (verifier + challenge builders are stubs;
# modern/auth/* provides the real ones)
# ---------------------------------------------------------------------------


class _Forbidden(Exception):
    http_status = 403


class StubVerifier:
    def verify(self, token: str) -> dict[str, Any]:
        if token == "good-token":
            return {"subject": "demo-user", "scopes": {"library:read"}}
        if token == "narrow-token":
            raise _Forbidden("insufficient scope")
        raise ValueError("invalid token")


def make_auth_app() -> tuple[Any, StubDispatcher]:
    return make_modern(
        require_auth=True,
        verifier=StubVerifier(),
        challenge_401=lambda: (
            'Bearer resource_metadata="http://testserver/.well-known/oauth-protected-resource"'
        ),
        challenge_403=lambda: 'Bearer error="insufficient_scope", scope="library:write"',
    )


class TestAuth:
    async def test_missing_token_gets_401_challenge(self):
        app, dispatcher = make_auth_app()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp", json=make_request("tools/list"), headers=modern_headers("tools/list")
            )
        assert response.status_code == 401
        assert "resource_metadata=" in response.headers["www-authenticate"]
        assert dispatcher.messages == []

    async def test_invalid_token_gets_401(self):
        app, _ = make_auth_app()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("tools/list"),
                headers=modern_headers("tools/list", Authorization="Bearer forged"),
            )
        assert response.status_code == 401

    async def test_insufficient_scope_gets_403_challenge(self):
        app, _ = make_auth_app()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("tools/list"),
                headers=modern_headers("tools/list", Authorization="Bearer narrow-token"),
            )
        assert response.status_code == 403
        assert "insufficient_scope" in response.headers["www-authenticate"]

    async def test_valid_token_dispatches_with_principal(self):
        app, dispatcher = make_auth_app()
        async with make_client(app) as client:
            response = await client.post(
                "/mcp",
                json=make_request("tools/list"),
                headers=modern_headers("tools/list", Authorization="Bearer good-token"),
            )
        assert response.status_code == 200
        env = dispatcher.envs[0]
        assert env.transport == "http"
        assert env.principal == {"subject": "demo-user", "scopes": {"library:read"}}

    async def test_auth_disabled_passes_none_principal(self):
        app, dispatcher = make_modern()
        async with make_client(app) as client:
            await client.post(
                "/mcp", json=make_request("tools/list"), headers=modern_headers("tools/list")
            )
        assert dispatcher.envs[0].principal is None

    def test_require_auth_without_verifier_is_a_config_error(self):
        with pytest.raises(ValueError, match="verifier"):
            create_modern_asgi(StubDispatcher(), require_auth=True)


# ---------------------------------------------------------------------------
# Cancellation on the buffered path (disconnect mid-dispatch)
# ---------------------------------------------------------------------------


class TestBufferedCancellation:
    async def test_disconnect_mid_dispatch_cancels_the_handler(self):
        """Closing the response stream cancels even a buffered request:
        the dispatch task is cancelled and no response is written."""
        started = asyncio.Event()
        cancelled = asyncio.Event()

        class SlowDispatcher:
            async def handle(self, message: dict[str, Any], env: Any) -> Any:
                started.set()
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
                return {"jsonrpc": "2.0", "id": message["id"], "result": {}}

        app = create_modern_asgi(SlowDispatcher())
        body = json.dumps(make_request("tools/list")).encode("utf-8")
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "path": "/mcp",
            "raw_path": b"/mcp",
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 1234),
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"mcp-protocol-version", PROTOCOL_VERSION.encode("ascii")),
                (b"mcp-method", b"tools/list"),
            ],
        }
        disconnect = asyncio.Event()
        request_delivered = False

        async def receive() -> dict[str, Any]:
            nonlocal request_delivered
            if not request_delivered:
                request_delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            await disconnect.wait()
            return {"type": "http.disconnect"}

        sent: list[dict[str, Any]] = []

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        app_task = asyncio.create_task(app(scope, receive, send))
        await asyncio.wait_for(started.wait(), timeout=2.0)
        disconnect.set()
        await asyncio.wait_for(app_task, timeout=2.0)

        assert cancelled.is_set()
        # Nothing meaningful goes to the vanished client: no JSON-RPC bytes.
        bodies = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
        assert bodies == b""


# ---------------------------------------------------------------------------
# Discovery-era routing (dual-era front door + filtered discovery routes)
# ---------------------------------------------------------------------------


class TestLegacyDiscoveryEraRouting:
    """End-to-end routing behavior behind ``discovery_era='legacy'``.

    server.py filters the modern route set with
    ``filter_shared_discovery_routes`` before building the modern app; the
    dual-era front door then routes anything the modern app did NOT register
    to the legacy app. Together that hands the shared well-known documents
    to the legacy OAuth stack while every /auth/* endpoint and the
    path-inserted AS metadata stay modern — chat clients (legacy era) and a
    modern client that knows the issuer can BOTH authenticate.
    """

    BASE = "https://library.example.run.app"

    def dual_app_with_legacy_discovery(self) -> tuple[Any, LegacyStubApp]:
        from modern.auth import build_demo_auth, filter_shared_discovery_routes

        routes, _verifier, _issuer = build_demo_auth(
            base_url=self.BASE,
            canonical_resource_url=f"{self.BASE}/mcp",
        )
        routes = filter_shared_discovery_routes(routes, f"{self.BASE}/mcp")
        modern, _dispatcher = make_modern(extra_routes=routes)
        legacy = LegacyStubApp()
        return create_dual_era_app(modern, legacy), legacy

    async def test_shared_well_knowns_fall_through_to_legacy(self):
        app, legacy = self.dual_app_with_legacy_discovery()
        async with make_client(app) as client:
            for path in (
                "/.well-known/oauth-protected-resource/mcp",
                "/.well-known/oauth-protected-resource",
                "/.well-known/oauth-authorization-server",
            ):
                response = await client.get(path)
                assert response.json() == {"era": "legacy"}, path
        assert [call["path"] for call in legacy.calls] == [
            "/.well-known/oauth-protected-resource/mcp",
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-authorization-server",
        ]

    async def test_modern_as_stays_reachable_at_path_inserted_form(self):
        app, legacy = self.dual_app_with_legacy_discovery()
        async with make_client(app) as client:
            metadata = await client.get("/.well-known/oauth-authorization-server/auth")
        # RFC 8414 path-inserted metadata is served by the modern app…
        assert metadata.status_code == 200
        assert metadata.json()["issuer"] == f"{self.BASE}/auth"
        # …without ever touching the legacy app.
        assert legacy.calls == []

    async def test_auth_endpoints_stay_modern(self):
        app, legacy = self.dual_app_with_legacy_discovery()
        async with make_client(app) as client:
            jwks = await client.get("/auth/jwks.json")
        assert jwks.status_code == 200
        assert "keys" in jwks.json()
        assert legacy.calls == []
