"""
Tests for modern/broker.py and the subscriptions/listen HTTP stream.

MCP 2026-07-28 (SEP-2575) replaced resources/subscribe, resources/unsubscribe
and the Streamable HTTP GET stream with a single long-lived request:
``subscriptions/listen``.  These tests pin the wire rules the spec is
strictest about:

- the acknowledgment is the FIRST stream message and echoes only the honored
  subset of the requested filter;
- every stream notification carries
  ``_meta["io.modelcontextprotocol/subscriptionId"]`` = the listen request id;
- delivery is strictly opt-in — unrequested notification types NEVER appear;
- graceful closure answers the listen request with an (otherwise empty)
  result whose ``_meta`` repeats the subscriptionId (schema-required);
- on HTTP, client disconnect IS cancellation: the broker cleans up and the
  server sends nothing further;
- ``:keepalive`` SSE comment lines flow during quiet periods and are
  invisible to a conforming SSE parser.
"""

import asyncio
import json
from typing import Any

import httpx
import pytest

from modern.broker import ListenOutcome, SubscriptionBroker
from modern.errors import MethodNotFoundError
from modern.http import create_modern_asgi
from modern.meta import parse_request_meta
from modern.types import (
    META_CLIENT_CAPS,
    META_CLIENT_INFO,
    META_PROTOCOL_VERSION,
    META_SUBSCRIPTION_ID,
    PROTOCOL_VERSION,
    SubscriptionFilter,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def make_meta() -> dict[str, Any]:
    return {
        META_PROTOCOL_VERSION: PROTOCOL_VERSION,
        META_CLIENT_INFO: {"name": "TestClient", "version": "1.0.0"},
        META_CLIENT_CAPS: {},
    }


def listen_body(request_id: int = 1, notifications: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "subscriptions/listen",
        "params": {
            "_meta": make_meta(),
            "notifications": notifications if notifications is not None else {},
        },
    }


def modern_headers(method: str) -> dict[str, str]:
    return {
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "Mcp-Method": method,
        "Accept": "application/json, text/event-stream",
    }


def parse_sse(body: str) -> list[dict[str, Any]]:
    """Parse SSE frames into JSON payloads, ignoring comment lines.

    Comment lines (starting with ``:``) are dropped exactly as a conforming
    SSE parser drops them — keepalives must be invisible at this layer.
    """
    events: list[dict[str, Any]] = []
    for chunk in body.split("\n\n"):
        data_lines = [
            line.removeprefix("data:").lstrip()
            for line in chunk.split("\n")
            if line.startswith("data:")
        ]
        if data_lines:
            events.append(json.loads("\n".join(data_lines)))
    return events


async def eventually(predicate, within: float = 2.0) -> None:
    """Poll until ``predicate()`` is truthy (test-side synchronization)."""
    deadline = asyncio.get_running_loop().time() + within
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            pytest.fail("condition not reached within timeout")
        await asyncio.sleep(0.005)


class ListenStubDispatcher:
    """Minimal dispatcher: validates _meta then hands listen to the broker.

    Mirrors the real dispatcher contract: parse_request_meta runs FIRST, and
    subscriptions/listen returns the broker's ListenOutcome untouched.
    """

    def __init__(self, broker: SubscriptionBroker) -> None:
        self.broker = broker

    async def handle(self, message: dict[str, Any], env: Any) -> Any:
        parse_request_meta(message.get("params"))
        if message["method"] == "subscriptions/listen":
            requested = message["params"].get("notifications") or {}
            return await self.broker.listen(message["id"], requested)
        raise MethodNotFoundError(f"Method '{message['method']}' not found")


# ---------------------------------------------------------------------------
# Broker unit tests
# ---------------------------------------------------------------------------


class TestBrokerAck:
    async def test_ack_is_tagged_and_echoes_honored_filter(self):
        broker = SubscriptionBroker()
        outcome = await broker.listen(
            7,
            SubscriptionFilter(
                tools_list_changed=True,
                resource_subscriptions=["library://books/1"],
            ),
        )

        assert isinstance(outcome, ListenOutcome)
        assert outcome.ack["jsonrpc"] == "2.0"
        assert outcome.ack["method"] == "notifications/subscriptions/acknowledged"
        params = outcome.ack["params"]
        # The subscriptionId tag is REQUIRED on every stream message,
        # including the ack, and equals the listen request's JSON-RPC id.
        assert params["_meta"][META_SUBSCRIPTION_ID] == 7
        # Honored subset: exactly what was requested, nothing more.
        assert params["notifications"] == {
            "toolsListChanged": True,
            "resourceSubscriptions": ["library://books/1"],
        }

    async def test_ack_omits_declined_and_falsy_filter_entries(self):
        broker = SubscriptionBroker()
        outcome = await broker.listen(
            "listen-1",
            SubscriptionFilter(
                tools_list_changed=False,  # explicit false == not subscribed
                resource_subscriptions=[],  # empty list == not subscribed
            ),
        )
        # Omission is the refusal/non-subscription signal — falsy entries
        # must not reappear in the acknowledgment.
        assert outcome.ack["params"]["notifications"] == {}

    async def test_accepts_raw_filter_dict(self):
        broker = SubscriptionBroker()
        outcome = await broker.listen(1, {"promptsListChanged": True})
        assert outcome.ack["params"]["notifications"] == {"promptsListChanged": True}


class TestBrokerOptIn:
    async def test_list_changed_delivered_only_to_opted_in_kind(self):
        broker = SubscriptionBroker()
        outcome = await broker.listen(3, SubscriptionFilter(tools_list_changed=True))

        broker.publish_list_changed("tools")
        broker.publish_list_changed("prompts")
        broker.publish_list_changed("resources")

        # Only the opted-in type arrives (spec MUST NOT send unrequested).
        assert outcome.queue.qsize() == 1
        notification = outcome.queue.get_nowait()
        assert notification["method"] == "notifications/tools/list_changed"
        assert notification["params"]["_meta"][META_SUBSCRIPTION_ID] == 3

    async def test_resource_updated_matches_exact_uri_only(self):
        broker = SubscriptionBroker()
        outcome = await broker.listen(
            4, SubscriptionFilter(resource_subscriptions=["library://books/123"])
        )

        broker.publish_resource_updated("library://books/123")
        broker.publish_resource_updated("library://books/999")
        # Exact matching: this broker does not exercise the spec's
        # sub-resource latitude.
        broker.publish_resource_updated("library://books/123/reviews")

        assert outcome.queue.qsize() == 1
        notification = outcome.queue.get_nowait()
        assert notification["method"] == "notifications/resources/updated"
        assert notification["params"]["uri"] == "library://books/123"
        assert notification["params"]["_meta"][META_SUBSCRIPTION_ID] == 4

    async def test_each_subscriber_gets_its_own_tag(self):
        broker = SubscriptionBroker()
        first = await broker.listen("a", SubscriptionFilter(resources_list_changed=True))
        second = await broker.listen("b", SubscriptionFilter(resources_list_changed=True))

        broker.publish_list_changed("resources")

        tag_a = first.queue.get_nowait()["params"]["_meta"][META_SUBSCRIPTION_ID]
        tag_b = second.queue.get_nowait()["params"]["_meta"][META_SUBSCRIPTION_ID]
        assert (tag_a, tag_b) == ("a", "b")


class TestBrokerClose:
    async def test_close_unregisters_and_returns_graceful_result(self):
        broker = SubscriptionBroker()
        outcome = await broker.listen(11, SubscriptionFilter(tools_list_changed=True))
        assert broker.active_subscription_count == 1

        response = await outcome.close()

        # The graceful-close response: empty result, required resultType,
        # and the schema-required _meta subscriptionId (even though it
        # duplicates the response id).
        assert response == {
            "jsonrpc": "2.0",
            "id": 11,
            "result": {
                "resultType": "complete",
                "_meta": {META_SUBSCRIPTION_ID: 11},
            },
        }
        assert broker.active_subscription_count == 0

        # Publishes after close reach nobody.
        broker.publish_list_changed("tools")
        assert outcome.queue.qsize() == 0

    async def test_close_is_idempotent(self):
        broker = SubscriptionBroker()
        outcome = await broker.listen(12, SubscriptionFilter())
        first = await outcome.close()
        second = await outcome.close()
        assert first == second
        assert broker.active_subscription_count == 0

    async def test_close_all_enqueues_graceful_response_for_each_stream(self):
        broker = SubscriptionBroker()
        first = await broker.listen(1, SubscriptionFilter(tools_list_changed=True))
        second = await broker.listen(2, SubscriptionFilter(prompts_list_changed=True))

        await broker.close_all()

        assert broker.active_subscription_count == 0
        for outcome, request_id in ((first, 1), (second, 2)):
            final = outcome.queue.get_nowait()
            # End-of-stream signal: a RESPONSE (no "method" key) in the queue.
            assert "method" not in final
            assert final["id"] == request_id
            assert final["result"]["_meta"][META_SUBSCRIPTION_ID] == request_id


# ---------------------------------------------------------------------------
# The full HTTP listen stream
# ---------------------------------------------------------------------------


def make_listen_app(
    broker: SubscriptionBroker, keepalive_interval: float = 15.0
) -> tuple[Any, ListenStubDispatcher]:
    dispatcher = ListenStubDispatcher(broker)
    app = create_modern_asgi(dispatcher, keepalive_interval=keepalive_interval)
    return app, dispatcher


class TestListenOverHttp:
    async def test_stream_ack_publish_and_graceful_close(self):
        broker = SubscriptionBroker()
        app, _ = make_listen_app(broker)

        async def drive() -> None:
            await eventually(lambda: broker.active_subscription_count == 1)
            broker.publish_list_changed("tools")
            broker.publish_list_changed("prompts")  # not requested -> dropped
            broker.publish_resource_updated("library://books/1")  # not subscribed
            await broker.close_all()

        driver = asyncio.create_task(drive())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/mcp",
                json=listen_body(request_id=9, notifications={"toolsListChanged": True}),
                headers=modern_headers("subscriptions/listen"),
            )
        await driver

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        # SHOULD-header that keeps reverse proxies from buffering the stream.
        assert response.headers["x-accel-buffering"] == "no"

        events = parse_sse(response.text)
        assert len(events) == 3
        # 1. Acknowledgment FIRST, echoing the honored subset.
        assert events[0]["method"] == "notifications/subscriptions/acknowledged"
        assert events[0]["params"]["notifications"] == {"toolsListChanged": True}
        assert events[0]["params"]["_meta"][META_SUBSCRIPTION_ID] == 9
        # 2. Only the opted-in notification type was delivered.
        assert events[1]["method"] == "notifications/tools/list_changed"
        assert events[1]["params"]["_meta"][META_SUBSCRIPTION_ID] == 9
        # 3. Graceful closure: the deferred JSON-RPC response to the listen
        #    request itself, with the schema-required _meta subscriptionId.
        assert events[2]["id"] == 9
        assert events[2]["result"]["resultType"] == "complete"
        assert events[2]["result"]["_meta"][META_SUBSCRIPTION_ID] == 9

    async def test_quiet_stream_emits_keepalive_comments(self):
        broker = SubscriptionBroker()
        app, _ = make_listen_app(broker, keepalive_interval=0.02)

        async def drive() -> None:
            await eventually(lambda: broker.active_subscription_count == 1)
            await asyncio.sleep(0.08)  # several keepalive intervals of silence
            await broker.close_all()

        driver = asyncio.create_task(drive())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/mcp",
                json=listen_body(request_id=5, notifications={"toolsListChanged": True}),
                headers=modern_headers("subscriptions/listen"),
            )
        await driver

        # Raw comment lines are on the wire...
        assert ":keepalive" in response.text
        # ...but a conforming SSE parser never surfaces them as events.
        events = parse_sse(response.text)
        assert [e.get("method", "response") for e in events] == [
            "notifications/subscriptions/acknowledged",
            "response",
        ]

    async def test_client_disconnect_is_cancellation(self):
        """Closing the SSE response stream MUST cancel the subscription.

        Driven through a raw ASGI harness because a real disconnect needs an
        ``http.disconnect`` message mid-stream, which buffered test clients
        cannot produce.
        """
        broker = SubscriptionBroker()
        app, _ = make_listen_app(broker, keepalive_interval=60.0)

        body = json.dumps(
            listen_body(request_id=13, notifications={"toolsListChanged": True})
        ).encode("utf-8")
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
                (b"mcp-method", b"subscriptions/listen"),
            ],
        }

        sent: list[dict[str, Any]] = []
        disconnect = asyncio.Event()
        request_delivered = False

        async def receive() -> dict[str, Any]:
            nonlocal request_delivered
            if not request_delivered:
                request_delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        app_task = asyncio.create_task(app(scope, receive, send))

        def ack_seen() -> bool:
            return any(
                b"acknowledged" in message.get("body", b"")
                for message in sent
                if message["type"] == "http.response.body"
            )

        await eventually(ack_seen)
        assert broker.active_subscription_count == 1

        sent_before_disconnect = len(sent)
        disconnect.set()
        await asyncio.wait_for(app_task, timeout=2.0)

        # Disconnect IS cancellation: subscription torn down...
        assert broker.active_subscription_count == 0
        # ...and NOTHING further was sent for the cancelled request.
        assert len(sent) == sent_before_disconnect

        # A publish after teardown reaches nobody (no error, no delivery).
        broker.publish_list_changed("tools")
