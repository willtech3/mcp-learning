"""
Tests for modern/stdio.py — the newline-delimited JSON-RPC driver.

These feed literal lines into the server loop and assert on the literal
lines it writes back, exercising the transport MUSTs of MCP 2026-07-28
basic/transports/stdio:

- one JSON-RPC message per line; parse failures -> -32700 with NO id;
  batch arrays -> -32600 (batching does not exist in MCP);
- notifications are never answered;
- ``notifications/cancelled`` (the stdio cancellation signal) stops an
  in-flight request and suppresses its response entirely;
- request-scoped notifications (progress / log messages) interleave on the
  shared channel BEFORE the final response of their request;
- ``subscriptions/listen``: acknowledgment first, subscriptionId-tagged
  notifications after, and the two-signal server-side teardown
  (notifications/cancelled THEN the graceful SubscriptionsListenResult);
- EOF -> clean exit with graceful teardown of live listen streams.
"""

import asyncio
import json

import pytest
from fastmcp import Context
from mcp.types import ToolAnnotations

from modern.dispatcher import Dispatcher, ListenOutcome
from modern.mrtr import RequestStateCodec
from modern.registry import ListCachePolicy, ModernRegistry
from modern.stdio import ModernStdioServer
from modern.types import META_SUBSCRIPTION_ID, PROTOCOL_VERSION, Implementation
from tools import ToolSpec

# ---------------------------------------------------------------------------
# Synthetic tools (no database, fully deterministic)
# ---------------------------------------------------------------------------


async def _echo_tool(text: str) -> str:
    return f"echo: {text}"


async def _slow_tool() -> str:
    await asyncio.sleep(30)  # cancelled long before this completes
    return "never"


async def _noisy_tool(ctx: Context) -> str:
    # Request-scoped notifications: MUST ride this request's own response
    # stream (on stdio: the shared channel, before the final response).
    await ctx.info("stage 1")
    await ctx.report_progress(1, total=2, message="halfway")
    return "done"


def _spec(fn, name: str) -> ToolSpec:
    return ToolSpec(fn=fn, name=name, annotations=ToolAnnotations(title=name))


class StubBroker:
    """Implements the DESIGN SubscriptionBroker surface the driver needs."""

    def __init__(self):
        self.queues: dict = {}
        #: request_ids whose close() the driver invoked — a real broker frees
        #: the subscription there, so this is how we detect the driver
        #: leaking a subscription (never calling close()).
        self.closed: set = set()

    async def listen(self, request_id, subscription_filter) -> ListenOutcome:
        queue: asyncio.Queue = asyncio.Queue()
        self.queues[request_id] = queue
        ack = {
            "jsonrpc": "2.0",
            "method": "notifications/subscriptions/acknowledged",
            "params": {
                "_meta": {META_SUBSCRIPTION_ID: request_id},
                "notifications": subscription_filter.to_wire(),
            },
        }

        async def close():
            self.closed.add(request_id)
            self.queues.pop(request_id, None)
            return {"resultType": "complete", "_meta": {META_SUBSCRIPTION_ID: request_id}}

        return ListenOutcome(ack=ack, queue=queue, close=close)

    def publish(self, request_id, notification: dict) -> None:
        # A closed subscription has no queue — a real broker simply doesn't
        # route to it (that's the whole point of close() freeing it).
        queue = self.queues.get(request_id)
        if queue is not None:
            queue.put_nowait(notification)

    def close_stream(self, request_id) -> None:
        # Server-side close signal: the broker enqueues the graceful result.
        self.queues[request_id].put_nowait(
            {"resultType": "complete", "_meta": {META_SUBSCRIPTION_ID: request_id}}
        )


# ---------------------------------------------------------------------------
# Harness: in-memory line streams around ModernStdioServer.run()
# ---------------------------------------------------------------------------


class StdioHarness:
    def __init__(self, dispatcher: Dispatcher):
        self.server = ModernStdioServer(dispatcher)
        self._incoming: asyncio.Queue = asyncio.Queue()
        self.outgoing: list[dict] = []
        self._new_output = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def _read_line(self) -> str | None:
        return await self._incoming.get()

    async def _write_line(self, line: str) -> None:
        assert "\n" not in line  # framing MUST: no embedded newlines
        self.outgoing.append(json.loads(line))
        self._new_output.set()

    def start(self) -> None:
        self._task = asyncio.create_task(self.server.run(self._read_line, self._write_line))

    def send(self, message) -> None:
        self._incoming.put_nowait(json.dumps(message))

    def send_raw(self, line: str) -> None:
        self._incoming.put_nowait(line)

    def eof(self) -> None:
        self._incoming.put_nowait(None)

    async def wait_for_outputs(self, count: int, deadline: float = 5.0) -> list[dict]:
        async with asyncio.timeout(deadline):
            while len(self.outgoing) < count:
                self._new_output.clear()
                await self._new_output.wait()
        return self.outgoing

    async def finish(self, deadline: float = 5.0) -> list[dict]:
        self.eof()
        assert self._task is not None
        async with asyncio.timeout(deadline):
            await self._task
        return self.outgoing


@pytest.fixture
def broker():
    return StubBroker()


@pytest.fixture
async def harness(broker):  # async: start() needs the running event loop
    registry = ModernRegistry(
        tool_specs=[
            _spec(_echo_tool, "echo_tool"),
            _spec(_slow_tool, "slow_tool"),
            _spec(_noisy_tool, "noisy_tool"),
        ],
        resource_groups=[],
        prompt_specs=[],
    )
    dispatcher = Dispatcher(
        registry,
        RequestStateCodec(b"stdio-test-secret"),
        Implementation(name="stdio-lib", version="1.0"),
        None,
        broker,
        ListCachePolicy(),
    )
    h = StdioHarness(dispatcher)
    h.start()
    return h


def wire_meta(**extra) -> dict:
    return {
        "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "stdio-client", "version": "1.0"},
        "io.modelcontextprotocol/clientCapabilities": {},
        **extra,
    }


def request(method: str, request_id, meta_extra: dict | None = None, **params) -> dict:
    params["_meta"] = wire_meta(**(meta_extra or {}))
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


# ---------------------------------------------------------------------------
# Framing
# ---------------------------------------------------------------------------


class TestFraming:
    async def test_request_response(self, harness):
        harness.send(request("tools/call", "r1", name="echo_tool", arguments={"text": "hello"}))
        outputs = await harness.finish()
        assert len(outputs) == 1
        response = outputs[0]
        assert response["id"] == "r1"
        assert response["result"]["content"][0]["text"] == "echo: hello"

    async def test_parse_error_has_no_id(self, harness):
        harness.send_raw("this is not json {{{")
        outputs = await harness.finish()
        assert len(outputs) == 1
        assert outputs[0]["error"]["code"] == -32700
        assert "id" not in outputs[0]  # id unreadable -> key OMITTED, not null

    async def test_batch_rejected(self, harness):
        harness.send([request("tools/list", 1), request("tools/list", 2)])
        outputs = await harness.finish()
        assert len(outputs) == 1
        assert outputs[0]["error"]["code"] == -32600

    async def test_blank_lines_ignored(self, harness):
        harness.send_raw("")
        harness.send_raw("   ")
        harness.send(request("tools/list", "r1"))
        outputs = await harness.finish()
        assert len(outputs) == 1
        assert outputs[0]["id"] == "r1"

    async def test_notifications_are_never_answered(self, harness):
        # An unknown notification produces nothing — not even an error
        # (receivers MUST NOT respond to notifications).
        harness.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        harness.send(request("tools/list", "after"))
        outputs = await harness.finish()
        assert [m.get("id") for m in outputs] == ["after"]

    async def test_interleaved_requests_both_answered(self, harness):
        harness.send(request("tools/call", "a", name="echo_tool", arguments={"text": "1"}))
        harness.send(request("tools/call", "b", name="echo_tool", arguments={"text": "2"}))
        outputs = await harness.finish()
        assert {m["id"] for m in outputs} == {"a", "b"}


# ---------------------------------------------------------------------------
# Cancellation (stdio signal: notifications/cancelled)
# ---------------------------------------------------------------------------


class TestCancellation:
    async def test_cancelled_request_sends_nothing(self, harness):
        harness.send(request("tools/call", "slow-1", name="slow_tool", arguments={}))
        # Let the request task start before cancelling it.
        await asyncio.sleep(0.05)
        harness.send(
            {
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": "slow-1", "reason": "user gave up"},
            }
        )
        harness.send(request("tools/call", "after", name="echo_tool", arguments={"text": "x"}))
        outputs = await harness.finish()
        # The cancelled request produced NO response (spec MUST NOT); the
        # later request still worked — cancellation is per-request, the
        # channel survives.
        assert [m.get("id") for m in outputs] == ["after"]

    async def test_unknown_request_id_ignored(self, harness):
        harness.send(
            {
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": "never-issued"},
            }
        )
        harness.send(request("tools/list", "r1"))
        outputs = await harness.finish()
        assert [m.get("id") for m in outputs] == ["r1"]


# ---------------------------------------------------------------------------
# Request-scoped notifications share the channel, before the response
# ---------------------------------------------------------------------------


class TestRequestScopedNotifications:
    async def test_progress_and_log_precede_response(self, harness):
        harness.send(
            request(
                "tools/call",
                "noisy-1",
                meta_extra={
                    # Opt in to BOTH per-request notification kinds.
                    "io.modelcontextprotocol/logLevel": "debug",
                    "progressToken": "tok-1",
                },
                name="noisy_tool",
                arguments={},
            )
        )
        outputs = await harness.finish()
        methods = [m.get("method") for m in outputs]
        assert methods == ["notifications/message", "notifications/progress", None]
        log, progress, response = outputs
        assert log["params"]["level"] == "info"
        assert log["params"]["data"] == "stage 1"
        assert progress["params"]["progressToken"] == "tok-1"
        assert progress["params"]["progress"] == 1
        assert response["id"] == "noisy-1"
        assert response["result"]["content"][0]["text"] == "done"

    async def test_without_opt_in_no_notifications(self, harness):
        """No logLevel -> MUST NOT send notifications/message; no
        progressToken -> no progress. Only the response appears."""
        harness.send(request("tools/call", "quiet-1", name="noisy_tool", arguments={}))
        outputs = await harness.finish()
        assert len(outputs) == 1
        assert outputs[0]["id"] == "quiet-1"


# ---------------------------------------------------------------------------
# subscriptions/listen: ack, tagged notifications, teardown
# ---------------------------------------------------------------------------


LISTEN_FILTER = {"toolsListChanged": True, "resourceSubscriptions": ["library://books/1"]}


class TestListenStreams:
    async def test_ack_is_first_and_tagged(self, harness, broker):
        harness.send(request("subscriptions/listen", 7, notifications=LISTEN_FILTER))
        outputs = await harness.wait_for_outputs(1)
        ack = outputs[0]
        assert ack["method"] == "notifications/subscriptions/acknowledged"
        assert ack["params"]["_meta"][META_SUBSCRIPTION_ID] == 7
        assert ack["params"]["notifications"]["toolsListChanged"] is True
        await harness.finish()

    async def test_notifications_flow_with_subscription_id(self, harness, broker):
        harness.send(request("subscriptions/listen", 7, notifications=LISTEN_FILTER))
        await harness.wait_for_outputs(1)
        broker.publish(
            7,
            {
                "jsonrpc": "2.0",
                "method": "notifications/tools/list_changed",
                "params": {"_meta": {META_SUBSCRIPTION_ID: 7}},
            },
        )
        outputs = await harness.wait_for_outputs(2)
        note = outputs[1]
        assert note["method"] == "notifications/tools/list_changed"
        # Clients demultiplex the shared stdio channel by this key.
        assert note["params"]["_meta"][META_SUBSCRIPTION_ID] == 7
        await harness.finish()

    async def test_server_side_teardown_order(self, harness, broker):
        """Server closes the stream: notifications/cancelled FIRST (the only
        server-sent cancellation allowed in 2026-07-28, and ONLY for listen
        streams), THEN the graceful SubscriptionsListenResult answering the
        original request id."""
        harness.send(request("subscriptions/listen", "sub-1", notifications=LISTEN_FILTER))
        await harness.wait_for_outputs(1)
        broker.close_stream("sub-1")
        outputs = await harness.wait_for_outputs(3)
        cancelled, result = outputs[1], outputs[2]
        assert cancelled["method"] == "notifications/cancelled"
        assert cancelled["params"]["requestId"] == "sub-1"
        assert result["id"] == "sub-1"
        assert result["result"]["resultType"] == "complete"
        assert result["result"]["_meta"][META_SUBSCRIPTION_ID] == "sub-1"
        await harness.finish()

    async def test_client_cancellation_silences_stream(self, harness, broker):
        harness.send(request("subscriptions/listen", "sub-2", notifications=LISTEN_FILTER))
        await harness.wait_for_outputs(1)
        harness.send(
            {
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": "sub-2"},
            }
        )
        await asyncio.sleep(0.05)
        # Notifications published after client cancellation never appear.
        broker.publish(
            "sub-2",
            {
                "jsonrpc": "2.0",
                "method": "notifications/tools/list_changed",
                "params": {"_meta": {META_SUBSCRIPTION_ID: "sub-2"}},
            },
        )
        outputs = await harness.finish()
        assert len(outputs) == 1  # just the ack

    async def test_client_cancellation_unregisters_subscription(self, harness, broker):
        """Regression: client-cancelling a listen MUST call outcome.close() so
        the broker frees the subscription (research-subs.md §1.5). Without it,
        the broker keeps fanning every future notification into a dead queue —
        an unbounded memory leak the HTTP transport avoids but stdio once did
        not."""
        harness.send(request("subscriptions/listen", "sub-9", notifications=LISTEN_FILTER))
        await harness.wait_for_outputs(1)
        harness.send(
            {
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": "sub-9"},
            }
        )
        await asyncio.sleep(0.05)
        await harness.finish()
        assert "sub-9" in broker.closed  # subscription was freed, not leaked

    async def test_eof_tears_down_listen_gracefully(self, harness, broker):
        """EOF with a live listen: the shutdown path emits the same
        two-signal teardown so the client knows the stream ended cleanly."""
        harness.send(request("subscriptions/listen", "sub-3", notifications=LISTEN_FILTER))
        await harness.wait_for_outputs(1)
        outputs = await harness.finish()
        methods = [m.get("method") for m in outputs]
        assert methods == [
            "notifications/subscriptions/acknowledged",
            "notifications/cancelled",
            None,  # the graceful SubscriptionsListenResult response
        ]
        assert outputs[2]["id"] == "sub-3"
        assert outputs[2]["result"]["resultType"] == "complete"
