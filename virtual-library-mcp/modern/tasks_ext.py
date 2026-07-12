"""
The ``io.modelcontextprotocol/tasks`` extension (SEP-2663, Final).

MCP 2026-07-28 made the protocol stateless: SEP-2575 removed the initialize
handshake and SEP-2567 removed sessions, so a server may not remember
ANYTHING about a client between requests.  But some work genuinely outlives
one request/response exchange — this server's ``regenerate_catalog`` tool
runs a four-stage rebuild that can take longer than a client wants to hold
an HTTP request open.  The tasks extension is the spec-sanctioned answer:
**explicit, client-held state**.  Instead of the server keeping a session,
it hands the client a *task handle* — an unguessable ``taskId`` string —
and the client carries that handle back on every poll.  The state lives on
the server, but the REFERENCE to it travels on the wire, exactly like MRTR's
``requestState`` token (SEP-2322).  That is the teaching point: in stateless
MCP, cross-call state is never ambient (a session), always explicit (a token
the client chooses to present).

Tasks moved OUT of the 2025-11-25 core into this extension, and the wire
format is NOT compatible with the old core tasks:

- ``tasks/result`` is GONE — results/errors ride inline on ``tasks/get``.
- ``tasks/list`` is GONE by design: without sessions there is no scope to
  enumerate "your" tasks, so clients persist their own ids (which also makes
  ids bearer-token-like — hence the entropy requirement below).
- ``tasks/update`` is NEW — the client-to-server input path for tasks that
  pause in ``input_required`` (replacing the old "call tasks/result early to
  open an SSE side channel" trick).
- ``CreateTaskResult`` is flattened: ``resultType: "task"`` plus the Task
  fields at the top level of ``result`` (no nested ``task`` object), and the
  TTL fields are renamed ``ttlMs`` / ``pollIntervalMs``.

Negotiation is per request (there is no handshake to negotiate in): the
client declares ``extensions["io.modelcontextprotocol/tasks"]`` inside the
``io.modelcontextprotocol/clientCapabilities`` ``_meta`` key, and the server
advertises the same id in ``DiscoverResult.capabilities.extensions``.  Task
returns are *server-directed* ("unsolicited task returns"): a declaring
client MUST be ready for either a normal result or a ``CreateTaskResult`` on
any supported request (``tools/call`` only, today), while the server MUST
NOT return a task to a client that did not declare the extension ON THAT
REQUEST — prior requests prove nothing in a stateless protocol.

Error-code note (research-extensions.md): the extension text still shows
``-32003`` for Missing Required Client Capability, but the core 2026-07-28
spec renumbered the spec-reserved range; we emit the core value ``-32021``
with ``data.requiredCapabilities`` as the core ``_meta`` section mandates.

Streamable HTTP routing (SEP-2243): clients MUST mirror ``params.taskId``
into the ``Mcp-Name`` header on ``tasks/get`` / ``tasks/update`` /
``tasks/cancel`` POSTs so intermediaries can route the poll to the instance
holding the task state.  Enforcing that header is modern/http.py's job; this
module only implements the method bodies.

Normative source: github.com/modelcontextprotocol/ext-tasks
(specification/draft/tasks.md); SEP-2663.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from modern.errors import InvalidParamsError, McpError, MissingClientCapabilityError
from modern.meta import RequestMeta
from modern.types import RESULT_COMPLETE, ClientCapabilities

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Extension identifier (reserved label; the ``tasks/`` method prefix and the
#: ``"task"`` resultType value are reserved along with it).
TASKS_EXTENSION_ID = "io.modelcontextprotocol/tasks"

#: The extension's addition to the resultType vocabulary (SEP-2663 §2.2).
#: Servers MUST set it on CreateTaskResult and on nothing else.
RESULT_TASK = "task"

#: Task status values and their legal transitions: working <-> input_required,
#: and either may move to exactly one terminal status.
TaskStatus = Literal["working", "input_required", "completed", "cancelled", "failed"]
TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "cancelled", "failed"})

#: Defaults for the freshness metadata every Task carries.  ttlMs is measured
#: from creation; clients MAY treat the task as unusable after createdAt+ttlMs
#: and servers MAY purge it.  pollIntervalMs is a politeness hint — clients
#: SHOULD honor it, servers MAY rate-limit those that do not.
DEFAULT_TTL_MS = 300_000
DEFAULT_POLL_INTERVAL_MS = 1_000


def _now_iso() -> str:
    """ISO 8601 UTC timestamp, Z-suffixed like the spec's examples."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def client_declares_tasks(capabilities: ClientCapabilities) -> bool:
    """Did THIS request declare the tasks extension?

    Per-request by design: capabilities arrive in ``_meta`` on every request
    and the server "MUST NOT return CreateTaskResult to a client that did not
    include the extension capability on that request, regardless of prior
    declarations".  An empty settings object ``{}`` counts as support.
    """
    extensions = capabilities.extensions or {}
    return TASKS_EXTENSION_ID in extensions


# ---------------------------------------------------------------------------
# TaskRecord + TaskStore — the in-memory task table
# ---------------------------------------------------------------------------


@dataclass
class TaskRecord:
    """One task's server-side state.

    ``task_id`` doubles as a bearer capability: there is no tasks/list, so
    knowledge of the id IS the access check (SEP-2663 security notes require
    unguessable ids; we use uuid4 — 122 bits of randomness).  ``result`` and
    ``error`` are mutually exclusive and only present in terminal states:
    ``completed`` carries the ORIGINAL request's result object verbatim
    (including tool results with ``isError: true`` — a tool-level failure is
    a successful protocol exchange), while ``failed`` carries a JSON-RPC
    error object and is reserved for protocol-level failures only.
    """

    task_id: str
    status: TaskStatus
    created_at: str
    last_updated_at: str
    ttl_ms: int | None
    poll_interval_ms: int | None
    status_message: str | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    #: The asyncio task executing the work — kept so tasks/cancel can
    #: actually interrupt it (cancellation is cooperative; see cancel()).
    runner: asyncio.Task[None] | None = None

    def to_task_fields(self) -> dict[str, Any]:
        """The base ``Task`` fields, camelCased for the wire.

        ``ttlMs`` is REQUIRED (null = unlimited); ``pollIntervalMs`` and
        ``statusMessage`` are optional and omitted when unset.
        """
        fields: dict[str, Any] = {
            "taskId": self.task_id,
            "status": self.status,
            "createdAt": self.created_at,
            "lastUpdatedAt": self.last_updated_at,
            "ttlMs": self.ttl_ms,
        }
        if self.poll_interval_ms is not None:
            fields["pollIntervalMs"] = self.poll_interval_ms
        if self.status_message is not None:
            fields["statusMessage"] = self.status_message
        return fields

    def to_detailed_task(self) -> dict[str, Any]:
        """The ``DetailedTask`` union member for the current status.

        This is what tasks/get returns and what a notifications/tasks event
        would carry: Task fields plus ``result`` (completed) or ``error``
        (failed).  ``input_required`` tasks would add ``inputRequests`` —
        this server's only task-able tool never pauses for input, so that
        arm is intentionally absent (documented, not invented).
        """
        detailed = self.to_task_fields()
        if self.status == "completed" and self.result is not None:
            detailed["result"] = self.result
        if self.status == "failed" and self.error is not None:
            detailed["error"] = self.error
        return detailed

    def is_expired(self, now: datetime) -> bool:
        """Past ``createdAt + ttlMs``?  (null TTL never expires.)"""
        if self.ttl_ms is None:
            return False
        created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        return (now - created).total_seconds() * 1000 >= self.ttl_ms


class TaskStore:
    """In-memory task table, keyed by taskId.

    In-memory is honest for a teaching server: the spec's durability MUST is
    about *ordering* (a CreateTaskResult may not be returned before a
    tasks/get for that id would resolve), not about surviving restarts.  A
    production server behind a load balancer would back this with shared
    storage and route polls via the ``Mcp-Name: <taskId>`` header.
    """

    def __init__(self) -> None:
        super().__init__()
        self._tasks: dict[str, TaskRecord] = {}

    def create(
        self,
        *,
        ttl_ms: int | None,
        poll_interval_ms: int | None,
        status_message: str | None = None,
    ) -> TaskRecord:
        """Insert a new ``working`` task and return it.

        The insert happens BEFORE the CreateTaskResult is serialized — that
        ordering is the strong-consistency MUST from SEP-2663 §2.4: the
        moment a client holds a taskId, a tasks/get for it must resolve.
        """
        now = _now_iso()
        record = TaskRecord(
            # uuid4: the id is a bearer token (no tasks/list to scope access),
            # so it MUST be unguessable and unenumerable.
            task_id=str(uuid.uuid4()),
            status="working",
            created_at=now,
            last_updated_at=now,
            ttl_ms=ttl_ms,
            poll_interval_ms=poll_interval_ms,
            status_message=status_message,
        )
        self._tasks[record.task_id] = record
        return record

    def get(self, task_id: str) -> TaskRecord:
        """Look up a live task; expired tasks are purged then not-found.

        Both failure modes are ``-32602`` with the informative messages the
        spec itself demonstrates — "purging expired tasks and then returning
        not-found" is called out as compliant behavior.
        """
        record = self._tasks.get(task_id)
        if record is None:
            raise InvalidParamsError("Failed to retrieve task: Task not found")
        if record.is_expired(datetime.now(UTC)):
            del self._tasks[task_id]
            raise InvalidParamsError("Failed to retrieve task: Task has expired")
        return record

    def _transition(self, record: TaskRecord, status: TaskStatus) -> None:
        """Move a task to a new status; terminal states are immutable."""
        if record.status in TERMINAL_STATUSES:
            # completed/failed/cancelled are terminal by definition — a late
            # runner callback racing a cancel must not resurrect the task.
            return
        record.status = status
        record.last_updated_at = _now_iso()

    def complete(self, task_id: str, result: dict[str, Any], message: str | None = None) -> None:
        """Terminal success — including tool results with ``isError: true``
        (tasks/get returns exactly what the underlying request would have)."""
        record = self._tasks.get(task_id)
        if record is None:
            return
        if record.status not in TERMINAL_STATUSES:
            record.result = result
            if message is not None:
                record.status_message = message
        self._transition(record, "completed")

    def fail(self, task_id: str, error: dict[str, Any], message: str | None = None) -> None:
        """Terminal failure — ``error`` MUST be a JSON-RPC error object;
        this status is reserved for protocol-level failures only."""
        record = self._tasks.get(task_id)
        if record is None:
            return
        if record.status not in TERMINAL_STATUSES:
            record.error = error
            if message is not None:
                record.status_message = message
        self._transition(record, "failed")

    def cancel(self, task_id: str) -> None:
        """Mark cancelled (no-op if already terminal)."""
        record = self._tasks.get(task_id)
        if record is None:
            return
        self._transition(record, "cancelled")


# ---------------------------------------------------------------------------
# TasksExtension — capability fragment, method handlers, and the tool wrapper
# ---------------------------------------------------------------------------

#: Signature the dispatcher calls extension methods with: the request params
#: and the already-parsed RequestMeta (needed for per-request capability
#: gating — tasks methods themselves require the extension capability).
MethodHandler = Callable[[dict[str, Any], RequestMeta], Awaitable[dict[str, Any]]]


class TasksExtension:
    """Everything the integrator wires for the tasks extension.

    - ``capability_fragment()`` -> merged into ServerCapabilities.extensions.
    - ``methods()`` -> {method name: handler} for ``registry.add_method``.
    - ``maybe_run_as_task(...)`` -> the wrap-a-coroutine helper the modern
      tools/call path routes ``regenerate_catalog`` through: declaring
      clients get a task handle immediately, everyone else gets the plain
      (slow, synchronous) result.
    """

    def __init__(
        self,
        store: TaskStore | None = None,
        *,
        ttl_ms: int | None = DEFAULT_TTL_MS,
        poll_interval_ms: int | None = DEFAULT_POLL_INTERVAL_MS,
    ) -> None:
        super().__init__()
        self.store = store or TaskStore()
        self._ttl_ms = ttl_ms
        self._poll_interval_ms = poll_interval_ms

    def capability_fragment(self) -> dict[str, dict[str, Any]]:
        """Advertised via server/discover.  The extension defines no settings
        object, so the empty object means simply "supported"."""
        return {TASKS_EXTENSION_ID: {}}

    def methods(self) -> dict[str, MethodHandler]:
        """The extension's JSON-RPC surface, for ``registry.add_method``.

        Exactly three methods: get (poll), update (submit input), cancel
        (cooperative).  There is deliberately NO tasks/list and NO
        tasks/result — see the module docstring for why they died.
        """
        return {
            "tasks/get": self.handle_get,
            "tasks/update": self.handle_update,
            "tasks/cancel": self.handle_cancel,
        }

    def register_with(self, registry: Any) -> None:
        """Convenience: attach every handler to a ModernRegistry.

        The capability fragment is advertised on the FIRST handler so
        ``server/discover`` announces ``io.modelcontextprotocol/tasks``
        (clients MUST NOT invoke an extension the server has not declared).
        """
        for i, (name, handler) in enumerate(self.methods().items()):
            registry.add_method(
                name,
                handler,
                capability_fragment=self.capability_fragment() if i == 0 else None,
            )

    # -- the wrap-a-coroutine helper ----------------------------------------

    async def maybe_run_as_task(
        self,
        execute: Callable[[], Awaitable[dict[str, Any]]],
        meta: RequestMeta,
        *,
        status_message: str | None = None,
    ) -> dict[str, Any]:
        """Run ``execute`` inline, or detach it behind a task handle.

        ``execute`` produces the request's normal result object (for
        tools/call, a CallToolResult-shaped dict).  The fork:

        - Client did NOT declare the extension on this request -> await
          inline and return the plain result.  This is the graceful-
          degradation MUST: unsupported extensions revert to core behavior,
          and a CreateTaskResult sent to a non-declaring client would be a
          protocol violation.
        - Client declared it -> insert a task record FIRST (strong
          consistency: once the client sees the taskId, tasks/get resolves),
          spawn the work in the background, and return a flattened
          CreateTaskResult immediately.

        Task returns are the SERVER's choice per request ("unsolicited task
        returns") — a declaring client must handle either shape, which is
        why we can unconditionally detach here.  Servers combining MRTR with
        tasks SHOULD resolve input_required exchanges BEFORE returning the
        task; regenerate_catalog never elicits, so that ordering is trivially
        satisfied.
        """
        if not client_declares_tasks(meta.client_capabilities):
            return await execute()

        record = self.store.create(
            ttl_ms=self._ttl_ms,
            poll_interval_ms=self._poll_interval_ms,
            status_message=status_message or "The operation is now in progress.",
        )

        async def _run() -> None:
            # Terminal-status mapping (SEP-2663 §2.10): McpError -> failed
            # with the JSON-RPC error object; any other exception -> failed
            # with -32603; cancellation -> cancelled; everything else —
            # INCLUDING isError:true tool results — is completed.
            try:
                result = await execute()
            except asyncio.CancelledError:
                self.store.cancel(record.task_id)
                raise
            except McpError as exc:
                # The JSON-RPC error the request WOULD have returned, stored
                # verbatim so tasks/get can replay it in the `error` field.
                json_rpc_error: dict[str, Any] = {"code": exc.code, "message": exc.message}
                if exc.data is not None:
                    json_rpc_error["data"] = exc.data
                self.store.fail(record.task_id, json_rpc_error, message=exc.message)
            except Exception as exc:
                self.store.fail(
                    record.task_id,
                    {"code": -32603, "message": str(exc)},
                    message=str(exc),
                )
            else:
                self.store.complete(record.task_id, result, message="Completed.")

        record.runner = asyncio.create_task(_run())

        # CreateTaskResult = Result & Task, FLATTENED: resultType "task" and
        # the Task fields side by side (2025-11-25 nested them under "task").
        return {"resultType": RESULT_TASK, **record.to_task_fields()}

    # -- method handlers -----------------------------------------------------

    def _require_capability(self, meta: RequestMeta) -> None:
        """Gate tasks/* behind the per-request capability declaration.

        The spec requires the Missing Required Client Capability error for
        non-declaring clients on tasks/get, tasks/update, and tasks/cancel —
        a client that never declared the extension cannot legitimately hold
        a taskId, so an undeclared poll is a protocol error, not a race.
        """
        if not client_declares_tasks(meta.client_capabilities):
            raise MissingClientCapabilityError(
                required={"extensions": {TASKS_EXTENSION_ID: {}}},
                message="tasks methods require the io.modelcontextprotocol/tasks extension",
            )

    @staticmethod
    def _extract_task_id(params: dict[str, Any]) -> str:
        task_id = params.get("taskId")
        if not isinstance(task_id, str) or not task_id:
            raise InvalidParamsError("params.taskId must be a non-empty string")
        return task_id

    async def handle_get(self, params: dict[str, Any], meta: RequestMeta) -> dict[str, Any]:
        """``tasks/get`` — the poll.  A pure, idempotent read.

        GetTaskResult = Result & DetailedTask with resultType "complete"
        (the "task" resultType marks CREATION only).  Unknown or expired
        ids are -32602 (MUST).
        """
        self._require_capability(meta)
        record = self.store.get(self._extract_task_id(params))
        return {"resultType": RESULT_COMPLETE, **record.to_detailed_task()}

    async def handle_update(self, params: dict[str, Any], meta: RequestMeta) -> dict[str, Any]:
        """``tasks/update`` — client-to-server input for paused tasks.

        The ack is an EMPTY result (resultType "complete") and is eventually
        consistent — observable status may lag the write.  Per spec, the
        server SHOULD ignore inputResponses for keys that are not currently
        outstanding.  This server's only task-able tool (regenerate_catalog)
        never enters ``input_required``, so NO key is ever outstanding and
        every submitted response is ignored wholesale — the method exists,
        validates the taskId (SHOULD error on unknown ids), and acks, which
        is the full write-path contract for a task that never pauses.
        """
        self._require_capability(meta)
        # Validates existence/expiry (unknown taskId SHOULD error) — the
        # record itself is untouched because nothing is ever outstanding.
        self.store.get(self._extract_task_id(params))
        input_responses = params.get("inputResponses")
        if input_responses is not None and not isinstance(input_responses, dict):
            raise InvalidParamsError("params.inputResponses must be an object")
        return {"resultType": RESULT_COMPLETE}

    async def handle_cancel(self, params: dict[str, Any], meta: RequestMeta) -> dict[str, Any]:
        """``tasks/cancel`` — cooperative cancellation.

        The server's only obligation is the empty ack: cancellation is a
        REQUEST, not a guarantee.  The task may already be terminal, may
        finish anyway, or may land in a terminal status other than
        "cancelled".  We do actually cancel the running coroutine here, but
        the ack goes out regardless — clients MAY discard all task state the
        moment they send cancel, no follow-up poll required.  Note that
        ``notifications/cancelled`` (the request-cancellation notification)
        MUST NOT be used for tasks; this method is the only cancel path.
        """
        self._require_capability(meta)
        record = self.store.get(self._extract_task_id(params))
        if record.status not in TERMINAL_STATUSES:
            if record.runner is not None and not record.runner.done():
                record.runner.cancel()
            self.store.cancel(record.task_id)
        return {"resultType": RESULT_COMPLETE}
