"""
Tests for modern/dispatcher.py (and modern/registry.py through it) —
the MCP 2026-07-28 method router driven with REAL library handlers
against a seeded per-test database.

Covered protocol behavior:

- server/discover shape (SEP-2575): supportedVersions, capabilities,
  serverInfo, required ttlMs/cacheScope/resultType (SEP-2549);
- deterministic name-sorted lists with caching hints, opaque-cursor
  pagination (invalid cursor -> -32602);
- the full MRTR round trip (SEP-2322) through tools/call with the real
  checkout_book tool on the fined-patron path, including requestState
  tampering/expiry/binding rejection;
- capability gating: -32021 with data.requiredCapabilities;
- teaching -32601 errors for methods removed from the modern era;
- resources/read of library:// URIs (static + template), prompts/get,
  completion/complete with live data;
- subscriptions/listen delegation to the broker (ListenOutcome);
- the post-call resource-update hook table;
- registry visibility (maintenance mode) firing on_list_changed.
"""

import asyncio
import time
from contextlib import contextmanager
from datetime import date, timedelta

import pytest
from fastmcp import Context
from mcp.types import ToolAnnotations

from database.schema import Author as AuthorDB
from database.schema import Book as BookDB
from database.schema import Patron as PatronDB
from modern.context import ModernContext
from modern.dispatcher import Dispatcher, ListenOutcome, RequestEnv
from modern.meta import RequestMeta
from modern.mrtr import RequestStateCodec, canonical_arguments_hash
from modern.registry import ListCachePolicy, ModernRegistry
from modern.types import (
    META_SUBSCRIPTION_ID,
    PROTOCOL_VERSION,
    SUPPORTED_VERSIONS,
    ClientCapabilities,
    Implementation,
)
from tools import ToolSpec

# ---------------------------------------------------------------------------
# Fixtures: seeded library + patched session factories (same approach as
# tests/tools/conftest.py — every module gets the factory patched where it
# is USED, not where it is defined)
# ---------------------------------------------------------------------------

# Modules that use `with <factory>() as session:` (context-manager style).
_CM_SESSION_PATCHES = [
    "tools.search.get_session",
    "tools.circulation.get_session",
    "tools.membership.get_session",
    "tools.book_insights.session_scope",
    "resources.books.session_scope",
    "resources.advanced_books.session_scope",
    "resources.patrons.session_scope",
    "resources.stats.session_scope",
    "resources.recommendations.session_scope",
    "modern.registry.session_scope",  # completions query live data
]

# Modules that call `session = get_session()` (plain-return style).
_PLAIN_SESSION_PATCHES = [
    "prompts.book_recommendations.get_session",
    "prompts.reading_plan.get_session",
    "prompts.review_generator.get_session",
]


@pytest.fixture
def library(test_db_session, monkeypatch):
    """A small seeded library wired into every handler module.

    - author_test001 with one available book (Fiction) and one unavailable
      (Science Fiction)
    - patron_clean001: active, no fines (checkout proceeds directly)
    - patron_fines001: active, $4.50 fines (the elicitation trigger)
    """

    @contextmanager
    def _cm_session():
        yield test_db_session

    for target in _CM_SESSION_PATCHES:
        monkeypatch.setattr(target, _cm_session)
    for target in _PLAIN_SESSION_PATCHES:
        monkeypatch.setattr(target, lambda: test_db_session)

    test_db_session.add(
        AuthorDB(id="author_test001", name="Test Author", birth_date=date(1970, 1, 1))
    )
    test_db_session.add_all(
        [
            BookDB(
                isbn="9780134685991",
                title="The Available Book",
                author_id="author_test001",
                genre="Fiction",
                publication_year=2020,
                available_copies=3,
                total_copies=3,
                description="A book with copies on the shelf.",
            ),
            BookDB(
                isbn="9780134685007",
                title="The Popular Book",
                author_id="author_test001",
                genre="Science Fiction",
                publication_year=2021,
                available_copies=0,
                total_copies=2,
                description="A book that is always checked out.",
            ),
        ]
    )
    today = date.today()
    test_db_session.add_all(
        [
            PatronDB(
                id="patron_clean001",
                name="Clean Reader",
                email="clean@example.com",
                membership_date=today - timedelta(days=400),
                expiration_date=today + timedelta(days=200),
                status="active",
                borrowing_limit=5,
                current_checkouts=0,
                total_checkouts=12,
                outstanding_fines=0.0,
            ),
            PatronDB(
                id="patron_fines001",
                name="Fined Reader",
                email="fined@example.com",
                membership_date=today - timedelta(days=300),
                expiration_date=today + timedelta(days=100),
                status="active",
                borrowing_limit=5,
                current_checkouts=0,
                total_checkouts=30,
                outstanding_fines=4.50,
            ),
        ]
    )
    test_db_session.commit()
    return test_db_session


class StubBroker:
    """Minimal stand-in for modern/broker.py's SubscriptionBroker,
    implementing the DESIGN contract the dispatcher codes against."""

    def __init__(self):
        self.list_changed: list[str] = []
        self.resource_updated: list[str] = []
        self.queue: asyncio.Queue = asyncio.Queue()

    async def listen(self, request_id, subscription_filter) -> ListenOutcome:
        ack = {
            "jsonrpc": "2.0",
            "method": "notifications/subscriptions/acknowledged",
            "params": {
                "_meta": {META_SUBSCRIPTION_ID: request_id},
                "notifications": subscription_filter.to_wire(),
            },
        }

        async def close():
            return {"resultType": "complete", "_meta": {META_SUBSCRIPTION_ID: request_id}}

        return ListenOutcome(ack=ack, queue=self.queue, close=close)

    def publish_list_changed(self, kind: str) -> None:
        self.list_changed.append(kind)

    def publish_resource_updated(self, uri: str) -> None:
        self.resource_updated.append(uri)


SECRET = b"dispatcher-test-secret"


@pytest.fixture
def broker():
    return StubBroker()


@pytest.fixture
def dispatcher(broker):
    return Dispatcher(
        ModernRegistry(),
        RequestStateCodec(SECRET),
        Implementation(name="virtual-library", version="1.0.0"),
        "A library management server.",
        broker,
        ListCachePolicy(ttl_ms=300_000, cache_scope="public"),
        resource_update_hooks={
            "checkout_book": lambda args: f"library://books/{args['book_isbn']}",
            "return_book": lambda args: f"library://books/{args.get('book_isbn', '')}",
        },
    )


def wire_meta(caps: dict | None = None, **extra) -> dict:
    return {
        "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "test-client", "version": "1.0"},
        "io.modelcontextprotocol/clientCapabilities": caps if caps is not None else {},
        **extra,
    }


def request(method: str, request_id=1, caps: dict | None = None, meta_extra=None, **params) -> dict:
    params["_meta"] = wire_meta(caps, **(meta_extra or {}))
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


async def _noop_notify(_message: dict) -> None:
    return None


ENV = RequestEnv(transport="stdio", principal=None, notify=_noop_notify)

ELICIT_CAPS = {"elicitation": {"form": {}}}


# ---------------------------------------------------------------------------
# _meta validation runs before routing
# ---------------------------------------------------------------------------


class TestMetaValidation:
    async def test_missing_meta_is_32602(self, dispatcher):
        response = await dispatcher.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, ENV
        )
        assert response["error"]["code"] == -32602

    async def test_unsupported_version_is_32022_with_supported_list(self, dispatcher):
        msg = request("tools/list")
        msg["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] = "1900-01-01"
        response = await dispatcher.handle(msg, ENV)
        error = response["error"]
        assert error["code"] == -32022
        assert error["data"]["requested"] == "1900-01-01"
        assert error["data"]["supported"] == list(SUPPORTED_VERSIONS)

    async def test_null_id_rejected(self, dispatcher):
        response = await dispatcher.handle(
            {"jsonrpc": "2.0", "id": None, "method": "tools/list", "params": {}}, ENV
        )
        assert response["error"]["code"] == -32600
        assert "id" not in response  # never echo a null id

    async def test_notification_returns_none(self, dispatcher):
        result = await dispatcher.handle(
            {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 5}},
            ENV,
        )
        assert result is None


# ---------------------------------------------------------------------------
# server/discover
# ---------------------------------------------------------------------------


class TestDiscover:
    async def test_shape(self, dispatcher):
        response = await dispatcher.handle(request("server/discover"), ENV)
        result = response["result"]
        assert result["resultType"] == "complete"
        assert result["supportedVersions"] == list(SUPPORTED_VERSIONS)
        assert result["serverInfo"] == {"name": "virtual-library", "version": "1.0.0"}
        assert result["instructions"] == "A library management server."
        # DiscoverResult extends CacheableResult: both hints are REQUIRED.
        assert result["ttlMs"] == 3_600_000
        assert result["cacheScope"] == "public"
        caps = result["capabilities"]
        assert caps["tools"] == {"listChanged": True}
        assert caps["resources"] == {"subscribe": True, "listChanged": True}
        assert caps["prompts"] == {"listChanged": True}
        assert caps["completions"] == {}


# ---------------------------------------------------------------------------
# Lists: deterministic ordering + caching hints + pagination
# ---------------------------------------------------------------------------


class TestLists:
    async def test_tools_list_sorted_with_cache_hints(self, dispatcher):
        response = await dispatcher.handle(request("tools/list"), ENV)
        result = response["result"]
        names = [t["name"] for t in result["tools"]]
        assert names == sorted(names)
        assert "checkout_book" in names
        assert result["resultType"] == "complete"
        assert result["ttlMs"] == 300_000
        assert result["cacheScope"] == "public"
        # Schemas derived from the SAME functions the legacy era serves.
        checkout = next(t for t in result["tools"] if t["name"] == "checkout_book")
        assert checkout["inputSchema"]["required"] == ["patron_id", "book_isbn"]
        assert "ctx" not in checkout["inputSchema"]["properties"]

    async def test_resources_and_templates_and_prompts_sorted(self, dispatcher):
        for method, key in [
            ("resources/list", "resources"),
            ("resources/templates/list", "resourceTemplates"),
            ("prompts/list", "prompts"),
        ]:
            response = await dispatcher.handle(request(method), ENV)
            result = response["result"]
            names = [item["name"] for item in result[key]]
            assert names == sorted(names), method
            assert result["ttlMs"] == 300_000
            assert result["cacheScope"] == "public"

    async def test_pagination_walk(self, broker):
        paged = Dispatcher(
            ModernRegistry(),
            RequestStateCodec(SECRET),
            Implementation(name="lib", version="1"),
            None,
            broker,
            ListCachePolicy(),
            page_size=3,
        )
        expected = [t.name for t in paged.registry.list_tools()]
        # Collect every page by following nextCursor (opaque to clients).
        collected, cursor, hops = [], None, 0
        while True:
            params = {} if cursor is None else {"cursor": cursor}
            response = await paged.handle(
                request("tools/list", request_id=f"p{hops}", **params), ENV
            )
            page = response["result"]["tools"]
            assert len(page) <= 3
            collected.extend(t["name"] for t in page)
            cursor = response["result"].get("nextCursor")
            hops += 1
            if cursor is None:
                break
        assert hops > 1  # it actually paginated
        assert collected == expected

    async def test_invalid_cursor_is_32602(self, dispatcher):
        response = await dispatcher.handle(request("tools/list", cursor="!!!not-a-cursor!!!"), ENV)
        assert response["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# tools/call — plain calls and error taxonomy
# ---------------------------------------------------------------------------


class TestToolsCall:
    async def test_search_catalog_complete(self, dispatcher, library):
        response = await dispatcher.handle(
            request("tools/call", name="search_catalog", arguments={"query": "Available"}), ENV
        )
        result = response["result"]
        assert result["resultType"] == "complete"
        assert result["structuredContent"]["books"][0]["isbn"] == "9780134685991"
        assert result["content"][0]["type"] == "text"

    async def test_unknown_tool_is_32602(self, dispatcher):
        response = await dispatcher.handle(
            request("tools/call", name="not_a_tool", arguments={}), ENV
        )
        error = response["error"]
        assert error["code"] == -32602  # NOT the retired -32002
        assert "not_a_tool" in error["message"]

    async def test_invalid_arguments_is_32602(self, dispatcher, library):
        response = await dispatcher.handle(
            request("tools/call", name="checkout_book", arguments={"patron_id": "patron_clean001"}),
            ENV,
        )
        assert response["error"]["code"] == -32602

    async def test_business_error_is_iserror_result(self, dispatcher, library):
        """Tool EXECUTION failures ride in the result so the LLM can read
        and self-correct — not JSON-RPC errors."""
        response = await dispatcher.handle(
            request(
                "tools/call",
                name="checkout_book",
                arguments={"patron_id": "patron_00404", "book_isbn": "9780134685991"},
            ),
            ENV,
        )
        result = response["result"]
        assert result["resultType"] == "complete"
        assert result["isError"] is True
        assert "patron_00404" in result["content"][0]["text"]

    async def test_resource_update_hook_fires_on_success(self, dispatcher, broker, library):
        await dispatcher.handle(
            request(
                "tools/call",
                name="checkout_book",
                arguments={"patron_id": "patron_clean001", "book_isbn": "9780134685991"},
            ),
            ENV,
        )
        assert broker.resource_updated == ["library://books/9780134685991"]

    async def test_hook_does_not_fire_on_error(self, dispatcher, broker, library):
        await dispatcher.handle(
            request(
                "tools/call",
                name="checkout_book",
                arguments={"patron_id": "patron_00404", "book_isbn": "9780134685991"},
            ),
            ENV,
        )
        assert broker.resource_updated == []


# ---------------------------------------------------------------------------
# The full MRTR round trip with the REAL checkout_book tool
# ---------------------------------------------------------------------------

FINES_ARGS = {"patron_id": "patron_fines001", "book_isbn": "9780134685991"}


class TestMrtrRoundTrip:
    async def test_fined_patron_round_trip(self, dispatcher, library):
        """checkout_book pauses on the fined patron: input_required with a
        deterministic key, then the retry (NEW id, echoed state) completes
        and actually creates the loan."""
        first = await dispatcher.handle(
            request(
                "tools/call",
                request_id="call-1",
                caps=ELICIT_CAPS,
                name="checkout_book",
                arguments=FINES_ARGS,
            ),
            ENV,
        )
        result = first["result"]
        assert result["resultType"] == "input_required"
        assert list(result["inputRequests"]) == ["elicit:0"]
        embedded = result["inputRequests"]["elicit:0"]
        assert embedded["method"] == "elicitation/create"
        assert "$4.50" in embedded["params"]["message"]
        # Approval-only elicitation: the same empty-object schema FastMCP sends.
        assert embedded["params"]["requestedSchema"] == {"type": "object", "properties": {}}
        state = result["requestState"]
        assert isinstance(state, str)

        retry = await dispatcher.handle(
            request(
                "tools/call",
                request_id="call-2",  # retries MUST use a new id
                caps=ELICIT_CAPS,
                name="checkout_book",
                arguments=FINES_ARGS,
                inputResponses={"elicit:0": {"action": "accept", "content": {}}},
                requestState=state,
            ),
            ENV,
        )
        final = retry["result"]
        assert final["resultType"] == "complete"
        assert not final.get("isError")
        assert final["structuredContent"]["patron_id"] == "patron_fines001"
        assert final["structuredContent"]["status"] == "active"

    async def test_declined_elicitation_is_tool_error(self, dispatcher, library):
        first = await dispatcher.handle(
            request(
                "tools/call",
                request_id=1,
                caps=ELICIT_CAPS,
                name="checkout_book",
                arguments=FINES_ARGS,
            ),
            ENV,
        )
        retry = await dispatcher.handle(
            request(
                "tools/call",
                request_id=2,
                caps=ELICIT_CAPS,
                name="checkout_book",
                arguments=FINES_ARGS,
                inputResponses={"elicit:0": {"action": "decline"}},
                requestState=first["result"]["requestState"],
            ),
            ENV,
        )
        result = retry["result"]
        assert result["isError"] is True
        assert "declined" in result["content"][0]["text"]

    async def test_tampered_request_state_is_32602(self, dispatcher, library):
        first = await dispatcher.handle(
            request(
                "tools/call",
                request_id=1,
                caps=ELICIT_CAPS,
                name="checkout_book",
                arguments=FINES_ARGS,
            ),
            ENV,
        )
        state = first["result"]["requestState"]
        tampered = state[:-4] + ("AAAA" if not state.endswith("AAAA") else "BBBB")
        retry = await dispatcher.handle(
            request(
                "tools/call",
                request_id=2,
                caps=ELICIT_CAPS,
                name="checkout_book",
                arguments=FINES_ARGS,
                inputResponses={"elicit:0": {"action": "accept", "content": {}}},
                requestState=tampered,
            ),
            ENV,
        )
        assert retry["error"]["code"] == -32602
        assert "requestState" in retry["error"]["message"]

    async def test_expired_request_state_is_32602(self, dispatcher, library):
        # Mint a state that is correctly signed and bound but already dead.
        codec = RequestStateCodec(SECRET)
        expired = codec.encode(
            {
                "v": 1,
                "m": "tools/call",
                "n": "checkout_book",
                "a": canonical_arguments_hash(FINES_ARGS),
                "p": "anon",
                "exp": int(time.time()) - 10,
                "r": {"elicit:0": {"action": "accept", "content": {}}},
            }
        )
        retry = await dispatcher.handle(
            request(
                "tools/call",
                request_id=2,
                caps=ELICIT_CAPS,
                name="checkout_book",
                arguments=FINES_ARGS,
                requestState=expired,
            ),
            ENV,
        )
        assert retry["error"]["code"] == -32602
        assert "expired" in retry["error"]["message"]

    async def test_state_bound_to_arguments(self, dispatcher, library):
        first = await dispatcher.handle(
            request(
                "tools/call",
                request_id=1,
                caps=ELICIT_CAPS,
                name="checkout_book",
                arguments=FINES_ARGS,
            ),
            ENV,
        )
        # Replaying consent onto DIFFERENT arguments must fail.
        other_args = {"patron_id": "patron_fines001", "book_isbn": "9780134685007"}
        retry = await dispatcher.handle(
            request(
                "tools/call",
                request_id=2,
                caps=ELICIT_CAPS,
                name="checkout_book",
                arguments=other_args,
                inputResponses={"elicit:0": {"action": "accept", "content": {}}},
                requestState=first["result"]["requestState"],
            ),
            ENV,
        )
        assert retry["error"]["code"] == -32602
        assert "arguments" in retry["error"]["message"]

    async def test_no_capability_means_handler_fallback(self, dispatcher, library):
        """checkout_book catches the missing-capability error and proceeds
        without confirmation (its documented graceful degradation) — the
        capability gate protects the WIRE, not the business rule."""
        response = await dispatcher.handle(
            request(
                "tools/call",
                caps={},  # no elicitation capability
                name="checkout_book",
                arguments=FINES_ARGS,
            ),
            ENV,
        )
        result = response["result"]
        assert result["resultType"] == "complete"
        assert not result.get("isError")


# ---------------------------------------------------------------------------
# Capability gating: -32021 surfaces when the handler does NOT catch it
# ---------------------------------------------------------------------------


async def _gated_tool(ctx: Context) -> str:
    """Synthetic tool that requires elicitation without a fallback."""
    answer = await ctx.elicit("Really?", response_type=None)
    return f"user said {answer.action}"


GATED_SPEC = ToolSpec(
    fn=_gated_tool,
    name="gated_tool",
    annotations=ToolAnnotations(title="Gated"),
)


class TestCapabilityGating:
    @pytest.fixture
    def gated_dispatcher(self, broker):
        registry = ModernRegistry(tool_specs=[GATED_SPEC], resource_groups=[], prompt_specs=[])
        return Dispatcher(
            registry,
            RequestStateCodec(SECRET),
            Implementation(name="lib", version="1"),
            None,
            broker,
            ListCachePolicy(),
        )

    async def test_missing_capability_is_32021(self, gated_dispatcher):
        response = await gated_dispatcher.handle(
            request("tools/call", caps={}, name="gated_tool", arguments={}), ENV
        )
        error = response["error"]
        assert error["code"] == -32021
        assert error["data"] == {"requiredCapabilities": {"elicitation": {}}}

    async def test_with_capability_goes_input_required(self, gated_dispatcher):
        response = await gated_dispatcher.handle(
            request("tools/call", caps=ELICIT_CAPS, name="gated_tool", arguments={}), ENV
        )
        assert response["result"]["resultType"] == "input_required"


# ---------------------------------------------------------------------------
# Sampling through the dispatcher (synthetic tool; deprecated feature)
# ---------------------------------------------------------------------------


async def _ask_llm(question: str, ctx: Context) -> str:
    result = await ctx.sample(messages=question, max_tokens=50)
    return result.text or "(no answer)"


ASK_SPEC = ToolSpec(fn=_ask_llm, name="ask_llm", annotations=ToolAnnotations(title="Ask"))


class TestSamplingRoundTrip:
    @pytest.fixture
    def sampling_dispatcher(self, broker):
        registry = ModernRegistry(tool_specs=[ASK_SPEC], resource_groups=[], prompt_specs=[])
        return Dispatcher(
            registry,
            RequestStateCodec(SECRET),
            Implementation(name="lib", version="1"),
            None,
            broker,
            ListCachePolicy(),
        )

    async def test_sampling_round_trip(self, sampling_dispatcher):
        caps = {"sampling": {}}
        args = {"question": "capital of France?"}
        first = await sampling_dispatcher.handle(
            request("tools/call", request_id=1, caps=caps, name="ask_llm", arguments=args), ENV
        )
        result = first["result"]
        assert result["resultType"] == "input_required"
        embedded = result["inputRequests"]["sample:0"]
        assert embedded["method"] == "sampling/createMessage"
        assert embedded["params"]["maxTokens"] == 50

        retry = await sampling_dispatcher.handle(
            request(
                "tools/call",
                request_id=2,
                caps=caps,
                name="ask_llm",
                arguments=args,
                inputResponses={
                    "sample:0": {
                        "role": "assistant",
                        "content": {"type": "text", "text": "Paris."},
                        "model": "claude-x",
                        "stopReason": "endTurn",
                    }
                },
                requestState=result["requestState"],
            ),
            ENV,
        )
        final = retry["result"]
        assert final["resultType"] == "complete"
        assert final["content"][0]["text"] == "Paris."
        assert final["structuredContent"] == {"result": "Paris."}

    async def test_book_insights_degrades_without_sampling(self, dispatcher, library):
        """The real generate_book_insights catches the -32021 internally and
        serves fallback content — useful on every client."""
        response = await dispatcher.handle(
            request(
                "tools/call",
                caps={},
                name="generate_book_insights",
                arguments={"isbn": "9780134685991", "insight_type": "summary"},
            ),
            ENV,
        )
        result = response["result"]
        assert result["resultType"] == "complete"
        assert "Book Information" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# resources/read
# ---------------------------------------------------------------------------


class TestResourcesRead:
    async def test_static_resource(self, dispatcher, library):
        response = await dispatcher.handle(
            request("resources/read", uri="library://books/list"), ENV
        )
        result = response["result"]
        assert result["resultType"] == "complete"
        assert result["ttlMs"] == 300_000  # SEP-2549: read results carry hints
        assert result["cacheScope"] == "public"
        contents = result["contents"][0]
        assert contents["uri"] == "library://books/list"
        assert contents["mimeType"] == "application/json"
        assert '"books"' in contents["text"]

    async def test_template_resource(self, dispatcher, library):
        response = await dispatcher.handle(
            request("resources/read", uri="library://books/9780134685991"), ENV
        )
        contents = response["result"]["contents"][0]
        assert "The Available Book" in contents["text"]

    async def test_multi_variable_template(self, dispatcher, library):
        response = await dispatcher.handle(
            request("resources/read", uri="library://stats/popular/30/5"), ENV
        )
        assert response["result"]["resultType"] == "complete"

    async def test_unknown_resource_is_32602(self, dispatcher, library):
        response = await dispatcher.handle(
            request("resources/read", uri="library://nope/nothing"), ENV
        )
        error = response["error"]
        assert error["code"] == -32602  # -32002 is retired
        assert error["data"]["uri"] == "library://nope/nothing"

    async def test_missing_book_is_32602(self, dispatcher, library):
        response = await dispatcher.handle(
            request("resources/read", uri="library://books/9999999999999"), ENV
        )
        assert response["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# prompts/get
# ---------------------------------------------------------------------------


class TestPromptsGet:
    async def test_render_shape(self, dispatcher, library):
        response = await dispatcher.handle(
            request("prompts/get", name="recommend_books", arguments={"genre": "Fiction"}), ENV
        )
        result = response["result"]
        assert result["resultType"] == "complete"
        message = result["messages"][0]
        assert message["role"] == "user"
        assert message["content"]["type"] == "text"
        assert "Fiction" in message["content"]["text"]
        # prompts/get is NOT cacheable (renders per-arguments).
        assert "ttlMs" not in result

    async def test_string_arguments_coerced(self, dispatcher, library):
        # Prompt args are strings on the wire; "3" must become int 3 for
        # the limit parameter.
        response = await dispatcher.handle(
            request("prompts/get", name="recommend_books", arguments={"limit": "3"}), ENV
        )
        assert "recommend 3 books" in response["result"]["messages"][0]["content"]["text"]

    async def test_missing_required_argument_is_32602(self, dispatcher, library):
        response = await dispatcher.handle(
            request("prompts/get", name="generate_reading_plan", arguments={}), ENV
        )
        error = response["error"]
        assert error["code"] == -32602
        assert "goal" in error["message"]

    async def test_unknown_prompt_is_32602(self, dispatcher):
        response = await dispatcher.handle(request("prompts/get", name="nope", arguments={}), ENV)
        assert response["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# completion/complete
# ---------------------------------------------------------------------------


class TestCompletion:
    async def test_prompt_literal_argument(self, dispatcher):
        response = await dispatcher.handle(
            request(
                "completion/complete",
                ref={"type": "ref/prompt", "name": "generate_reading_plan"},
                argument={"name": "experience_level", "value": "b"},
            ),
            ENV,
        )
        completion = response["result"]["completion"]
        assert completion["values"] == ["beginner"]
        assert completion["total"] == 1
        assert completion["hasMore"] is False
        # NOT cacheable: completion/complete is absent from SEP-2549's list.
        assert "ttlMs" not in response["result"]

    async def test_prompt_genre_from_live_data(self, dispatcher, library):
        response = await dispatcher.handle(
            request(
                "completion/complete",
                ref={"type": "ref/prompt", "name": "recommend_books"},
                argument={"name": "genre", "value": "F"},
            ),
            ENV,
        )
        assert response["result"]["completion"]["values"] == ["Fiction"]

    async def test_template_status_enum(self, dispatcher):
        response = await dispatcher.handle(
            request(
                "completion/complete",
                ref={"type": "ref/resource", "uri": "library://patrons/by-status/{status}"},
                argument={"name": "status", "value": ""},
            ),
            ENV,
        )
        values = response["result"]["completion"]["values"]
        assert set(values) == {"active", "suspended", "expired", "pending"}

    async def test_template_isbn_prefix(self, dispatcher, library):
        response = await dispatcher.handle(
            request(
                "completion/complete",
                ref={"type": "ref/resource", "uri": "library://books/{isbn}"},
                argument={"name": "isbn", "value": "978013468"},
            ),
            ENV,
        )
        values = response["result"]["completion"]["values"]
        assert values == ["9780134685007", "9780134685991"]

    async def test_unknown_prompt_ref_is_32602(self, dispatcher):
        response = await dispatcher.handle(
            request(
                "completion/complete",
                ref={"type": "ref/prompt", "name": "nope"},
                argument={"name": "genre", "value": "F"},
            ),
            ENV,
        )
        assert response["error"]["code"] == -32602

    async def test_unknown_argument_returns_empty(self, dispatcher):
        response = await dispatcher.handle(
            request(
                "completion/complete",
                ref={"type": "ref/prompt", "name": "recommend_books"},
                argument={"name": "no_such_arg", "value": "x"},
            ),
            ENV,
        )
        assert response["result"]["completion"]["values"] == []


# ---------------------------------------------------------------------------
# Removed legacy methods -> teaching -32601 errors
# ---------------------------------------------------------------------------


class TestRemovedMethods:
    async def test_initialize_names_supported_versions(self, dispatcher):
        """A legacy client's initialize (no modern _meta!) still gets a
        useful answer: -32601 with data.supported (spec SHOULD)."""
        response = await dispatcher.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
            },
            ENV,
        )
        error = response["error"]
        assert error["code"] == -32601
        assert "server/discover" in error["message"]
        assert error["data"]["supported"] == list(SUPPORTED_VERSIONS)

    async def test_resources_subscribe_names_replacement(self, dispatcher):
        response = await dispatcher.handle(request("resources/subscribe", uri="x"), ENV)
        error = response["error"]
        assert error["code"] == -32601
        assert "subscriptions/listen" in error["message"]

    @pytest.mark.parametrize("method", ["ping", "logging/setLevel", "tasks/list", "tasks/result"])
    async def test_other_removed_methods(self, dispatcher, method):
        response = await dispatcher.handle(request(method), ENV)
        assert response["error"]["code"] == -32601

    async def test_truly_unknown_method(self, dispatcher):
        response = await dispatcher.handle(request("bogus/method"), ENV)
        error = response["error"]
        assert error["code"] == -32601
        assert "bogus/method" in error["message"]


# ---------------------------------------------------------------------------
# Extension methods (registry.add_method) — the tasks-extension hook
# ---------------------------------------------------------------------------


class TestExtensionMethods:
    async def test_registered_method_is_routed(self, broker):
        registry = ModernRegistry(tool_specs=[], resource_groups=[], prompt_specs=[])
        seen = {}

        async def handler(params: dict, meta: RequestMeta) -> dict:
            seen["params"] = params
            seen["client"] = meta.client_info.name
            return {"taskId": "task-1", "status": "working"}

        registry.add_method("tasks/get", handler, {"io.modelcontextprotocol/tasks": {}})
        dispatcher = Dispatcher(
            registry,
            RequestStateCodec(SECRET),
            Implementation(name="lib", version="1"),
            None,
            broker,
            ListCachePolicy(),
        )
        response = await dispatcher.handle(request("tasks/get", taskId="task-1"), ENV)
        result = response["result"]
        assert result["taskId"] == "task-1"
        assert result["resultType"] == "complete"  # defaulted by the router
        assert seen["client"] == "test-client"
        # The capability fragment surfaces in discover.
        discover = await dispatcher.handle(request("server/discover", request_id=2), ENV)
        extensions = discover["result"]["capabilities"]["extensions"]
        assert extensions == {"io.modelcontextprotocol/tasks": {}}


# ---------------------------------------------------------------------------
# subscriptions/listen delegation
# ---------------------------------------------------------------------------


class TestListen:
    async def test_returns_listen_outcome_with_ack(self, dispatcher):
        outcome = await dispatcher.handle(
            request("subscriptions/listen", request_id=7, notifications={"toolsListChanged": True}),
            ENV,
        )
        assert isinstance(outcome, ListenOutcome)
        assert outcome.ack["method"] == "notifications/subscriptions/acknowledged"
        assert outcome.ack["params"]["_meta"][META_SUBSCRIPTION_ID] == 7

    async def test_missing_filter_is_32602(self, dispatcher):
        response = await dispatcher.handle(request("subscriptions/listen"), ENV)
        assert response["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# Visibility (maintenance mode) through ModernContext -> registry
# ---------------------------------------------------------------------------


class TestVisibility:
    async def test_disable_and_reset_fire_list_changed(self, dispatcher, broker):
        registry = dispatcher.registry
        registry.on_list_changed = broker.publish_list_changed

        meta = RequestMeta(
            protocol_version=PROTOCOL_VERSION,
            client_info=Implementation(name="t", version="1"),
            client_capabilities=ClientCapabilities(),
            log_level=None,
            progress_token=None,
            trace={},
        )
        ctx = ModernContext(meta=meta, registry=registry)

        target = "Personalized Book Recommendations"
        names_before = [t.name for t in registry.list_resource_templates()]
        assert target in names_before

        # Exactly what tools/catalog_maintenance.py calls during rebuild.
        await ctx.disable_components(names={target}, components={"template"})
        assert target not in [t.name for t in registry.list_resource_templates()]
        assert broker.list_changed == ["resources"]

        await ctx.reset_visibility()
        assert target in [t.name for t in registry.list_resource_templates()]
        assert broker.list_changed == ["resources", "resources"]
