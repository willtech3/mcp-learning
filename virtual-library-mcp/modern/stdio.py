"""
Modern stdio transport driver for MCP 2026-07-28.

The stdio binding is deliberately boring — newline-delimited JSON-RPC over
a subprocess's standard streams, unchanged in framing since the first MCP
revision — but the 2026-07-28 SEMANTICS running over it are new, and this
driver is where they become visible:

- **One shared channel, no per-request streams.**  On Streamable HTTP each
  request gets its own response (possibly an SSE stream); on stdio
  EVERYTHING interleaves on stdout — responses (correlated by JSON-RPC id),
  request-scoped notifications (progress/log messages for in-flight
  requests), and subscription notifications.  The latter carry
  ``_meta["io.modelcontextprotocol/subscriptionId"]`` precisely so clients
  can demultiplex this shared channel (SEP-2575).

- **The process is NOT a session.**  Clients may interleave unrelated
  requests on the same pipe; each is handled in its own task, and each
  carries its own ``_meta``.  The driver keeps only TRANSPORT state (which
  tasks are in flight, which listen streams are pumping) — never protocol
  state.

- **Cancellation is a notification here (basic/patterns/cancellation).**
  HTTP clients cancel by closing the response stream; stdio has no stream
  to close, so the client MUST send ``notifications/cancelled`` naming the
  request id.  We cancel the task and send NOTHING further for that
  request (spec MUST NOT).  Unknown/completed ids are ignored — fire and
  forget, races are expected.

- **Server-side listen teardown sends BOTH signals.**  The subscriptions
  page says the server SHOULD answer the listen request with an empty
  result before closing ("graceful closure"); the cancellation page says
  the server MUST send ``notifications/cancelled`` referencing the listen
  id when it tears the stream down (and MUST NOT use that notification for
  anything else — it is the ONLY server-sent cancellation in the modern
  protocol).  We do both, in that order: cancelled first (the "stop
  expecting notifications" signal), then the ``SubscriptionsListenResult``
  that finally answers the long-deferred request.

- **EOF on stdin is THE shutdown signal.**  Servers SHOULD exit promptly
  when reads return EOF; in-flight work is cancelled (statelessness means
  the client simply retries against a fresh process), active listens get
  the graceful teardown above, and the loop returns.

- **stdout purity is a MUST.**  Nothing that is not a valid MCP message may
  be written to stdout (logging belongs on stderr).  A single writer lock
  guarantees whole-line atomicity for interleaved tasks.

Spec: MCP 2026-07-28 basic/transports/stdio, basic/patterns/cancellation,
basic/patterns/subscriptions; SEP-2575.
"""

import asyncio
import contextlib
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from modern.dispatcher import Dispatcher, ListenOutcome, RequestEnv
from modern.errors import InvalidRequestError, ParseError
from modern.types import JSONRPC_VERSION

logger = logging.getLogger(__name__)

#: Async line sources/sinks the server loop runs against.  Tests inject
#: in-memory implementations; run_stdio_modern wires the real pipes.
ReadLine = Callable[[], Awaitable[str | None]]  # None = EOF
WriteLine = Callable[[str], Awaitable[None]]


class ModernStdioServer:
    """One modern-era server loop bound to a pair of line streams."""

    def __init__(self, dispatcher: Dispatcher, *, drain_timeout: float = 2.0) -> None:
        self.dispatcher = dispatcher
        #: How long EOF shutdown waits for in-flight requests to finish
        #: before cancelling them (see _shutdown).
        self.drain_timeout = drain_timeout
        #: In-flight request tasks by JSON-RPC id — the cancellation target
        #: table.  Includes listen pump tasks (a listen is cancelled by the
        #: same notification, naming the listen request's id).
        self._tasks: dict[str | int, asyncio.Task[None]] = {}
        #: Live ListenOutcomes by listen request id, for EOF teardown.
        self._listens: dict[str | int, ListenOutcome] = {}
        self._write_lock = asyncio.Lock()
        self._write_line: WriteLine | None = None

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    async def _write_message(self, message: dict[str, Any]) -> None:
        """Serialize one message as one line — atomically.

        Framing MUSTs: newline-delimited, no embedded newlines.
        ``json.dumps`` never emits raw newlines, and the lock keeps
        concurrent request tasks from interleaving partial lines.
        """
        if self._write_line is None:  # loop not running; drop silently
            return
        line = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        async with self._write_lock:
            await self._write_line(line)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self, read_line: ReadLine, write_line: WriteLine) -> None:
        """Read stdin until EOF, dispatching each line concurrently."""
        self._write_line = write_line
        try:
            while True:
                line = await read_line()
                if line is None:
                    break  # EOF: the one portable graceful-shutdown signal
                line = line.strip()
                if not line:
                    continue

                try:
                    message = json.loads(line)
                except ValueError:
                    # Unreadable body -> -32700 with NO id (we could not
                    # parse one out; the id key is omitted, never null).
                    await self._write_message(ParseError().to_error_response(None))
                    continue

                if isinstance(message, list):
                    # JSON-RPC batching does not exist in MCP.
                    await self._write_message(
                        InvalidRequestError(
                            "Batch requests are not supported in MCP"
                        ).to_error_response(None)
                    )
                    continue
                if not isinstance(message, dict):
                    await self._write_message(
                        InvalidRequestError("Message must be a JSON object").to_error_response(None)
                    )
                    continue

                if "id" not in message:
                    self._handle_notification(message)
                    continue

                self._spawn_request(message)
        finally:
            await self._shutdown()
            self._write_line = None

    # ------------------------------------------------------------------
    # Notifications (client -> server): only cancellation matters
    # ------------------------------------------------------------------

    def _handle_notification(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        if method != "notifications/cancelled":
            # No other client notification is defined in 2026-07-28.
            # Notifications MUST NOT be answered, so: silence.
            return
        params = message.get("params")
        request_id = params.get("requestId") if isinstance(params, dict) else None
        if request_id is None:
            return
        task = self._tasks.get(request_id)
        if task is None:
            # Unknown/completed/never-issued id: MAY be ignored (races
            # between completion and cancellation are expected and benign).
            return
        # Cancel the task; its own machinery guarantees nothing further is
        # written for this request (spec MUST NOT respond after cancel).
        self._listens.pop(request_id, None)
        task.cancel()

    # ------------------------------------------------------------------
    # Requests
    # ------------------------------------------------------------------

    def _spawn_request(self, message: dict[str, Any]) -> None:
        """Handle each request in its own task so slow calls don't block the
        read loop — clients legitimately interleave requests on one pipe."""
        raw_id = message.get("id")
        task = asyncio.create_task(self._process_request(message))
        if isinstance(raw_id, str | int) and not isinstance(raw_id, bool):
            self._tasks[raw_id] = task
            task.add_done_callback(lambda t, rid=raw_id: self._forget_task(rid, t))

    def _forget_task(self, request_id: str | int, task: asyncio.Task[None]) -> None:
        """Drop a finished task — but only if it still owns the table slot.

        A ``subscriptions/listen`` request REPLACES its dispatch task with
        the long-lived pump task under the same id; the dispatch task's
        done-callback must not evict the pump it was replaced by.
        """
        if self._tasks.get(request_id) is task:
            del self._tasks[request_id]

    async def _process_request(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        env = RequestEnv(
            transport="stdio",
            # stdio auth comes from the process environment, not the
            # protocol (the Authorization framework is HTTP-only).
            principal=None,
            # Request-scoped notifications ride the same shared channel,
            # BEFORE the final response (their only legal stream).
            notify=self._write_message,
        )
        # If this task is cancelled mid-dispatch (notifications/cancelled),
        # CancelledError unwinds right here — nothing below runs, so nothing
        # is ever written for a cancelled request (spec MUST NOT).
        outcome = await self.dispatcher.handle(message, env)
        if outcome is None:
            return
        if isinstance(outcome, ListenOutcome):
            if isinstance(request_id, str | int) and not isinstance(request_id, bool):
                await self._start_listen(request_id, outcome)
            return
        await self._write_message(outcome)

    # ------------------------------------------------------------------
    # subscriptions/listen pumping
    # ------------------------------------------------------------------

    async def _start_listen(self, request_id: str | int, outcome: ListenOutcome) -> None:
        """Ack immediately, then pump broker notifications until closed.

        The pump replaces this request's entry in the task table: a later
        ``notifications/cancelled`` naming the listen id cancels the PUMP
        (client-initiated teardown — we stop sending, answer nothing).
        """
        self._listens[request_id] = outcome
        await self._write_message(outcome.ack)
        pump = asyncio.create_task(self._pump_listen(request_id, outcome))
        self._tasks[request_id] = pump
        pump.add_done_callback(lambda t, rid=request_id: self._forget_task(rid, t))

    async def _pump_listen(self, request_id: str | int, outcome: ListenOutcome) -> None:
        try:
            while True:
                item = await outcome.queue.get()
                if not isinstance(item, dict):
                    continue
                if "method" in item:
                    # An ordinary notification, pre-tagged by the broker
                    # with the subscriptionId _meta key.
                    await self._write_message(item)
                    continue
                # Anything else is the broker's server-side close signal: a
                # SubscriptionsListenResult (bare result object or full
                # response).  Perform the two-signal stdio teardown.
                await self._teardown_listen(request_id, result=item)
                return
        except asyncio.CancelledError:
            # Client-initiated cancellation (or shutdown handled elsewhere):
            # stop pumping, write nothing further for this request.  We MUST
            # also unregister the subscription from the broker — close() is
            # the only thing that removes the _Subscription and frees its
            # queue (research-subs.md §1.5: "free resources").  Without this,
            # a client-cancelled listen leaks: the broker keeps fanning every
            # future list_changed/resource_updated into a queue nobody reads.
            # The HTTP transport does the same in its cleanup() (http.py).
            self._listens.pop(request_id, None)
            with contextlib.suppress(Exception):
                # close() is await-free by contract, so it runs to completion
                # without re-suspending on this already-cancelled task.
                await outcome.close()
            raise

    async def _teardown_listen(self, request_id: str | int, result: dict[str, Any]) -> None:
        """Server-side graceful teardown: cancelled notification THEN result.

        The order embodies both spec clauses (see module docstring): the
        cancellation page's MUST (send notifications/cancelled referencing
        the listen id on teardown) and the subscriptions page's SHOULD
        (answer the listen request with an empty result before closing).
        """
        self._listens.pop(request_id, None)
        await self._write_message(
            {
                "jsonrpc": JSONRPC_VERSION,
                "method": "notifications/cancelled",
                "params": {
                    "requestId": request_id,
                    "reason": "Server closed the subscription stream",
                },
            }
        )
        if "jsonrpc" in result and "id" in result:
            await self._write_message(result)  # broker sent a full response
        else:
            await self._write_message(
                {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}
            )

    # ------------------------------------------------------------------
    # Shutdown on EOF
    # ------------------------------------------------------------------

    async def _shutdown(self) -> None:
        """EOF: drain fast work, tear down listens gracefully, cancel the rest.

        "Exit promptly" (spec SHOULD) is balanced against not discarding
        answers that are milliseconds away: ordinary in-flight requests get
        a short drain window to write their responses, then anything still
        running is cancelled — safe, because the stateless protocol lets
        clients simply re-issue lost requests against a fresh process.
        """
        pending = [task for rid, task in list(self._tasks.items()) if rid not in self._listens]
        if pending:
            _done, still_running = await asyncio.wait(pending, timeout=self.drain_timeout)
            for task in still_running:
                task.cancel()
            for task in still_running:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

        # Graceful listen teardown while stdout is still writable — the
        # client (or its next incarnation) learns these streams ended
        # cleanly rather than inferring loss from the pipe closing.
        for request_id, outcome in list(self._listens.items()):
            pump = self._tasks.get(request_id)
            if pump is not None:
                pump.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pump
            with contextlib.suppress(Exception):
                result = await outcome.close()
                await self._teardown_listen(request_id, result=result)
        self._listens.clear()
        self._tasks.clear()


async def run_stdio_modern(dispatcher: Dispatcher) -> None:
    """Serve the modern protocol on this process's real stdin/stdout.

    This is the entry point the integrator calls for
    ``VIRTUAL_LIBRARY_TRANSPORT=stdio-modern``.  Reads are pushed to a
    worker thread (stdin has no portable async API); writes flush per line
    so the client never waits on a buffered response.
    """
    loop = asyncio.get_running_loop()

    def _blocking_readline() -> bytes:
        return sys.stdin.buffer.readline()

    async def read_line() -> str | None:
        data = await loop.run_in_executor(None, _blocking_readline)
        if not data:
            return None  # EOF
        # Messages MUST be UTF-8; replace-errors keeps the loop alive to
        # answer -32700 rather than crashing on a bad byte.
        return data.decode("utf-8", errors="replace")

    async def write_line(line: str) -> None:
        # stdout carries ONLY protocol messages (spec MUST) — anything else
        # this process logs goes to stderr via the logging module.
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    server = ModernStdioServer(dispatcher)
    await server.run(read_line, write_line)
