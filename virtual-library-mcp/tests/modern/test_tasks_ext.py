"""
Tests for modern/tasks_ext.py — the io.modelcontextprotocol/tasks extension
(SEP-2663).

The behaviors under test are the extension's normative core:

- the create -> working -> completed lifecycle observed purely through
  ``tasks/get`` polling (there is no tasks/result and no tasks/list);
- the flattened ``CreateTaskResult`` shape: ``resultType: "task"`` with the
  Task fields at the TOP level, and required ``ttlMs``;
- the unsolicited-return rule's flip side: a client that did not declare the
  extension ON THIS REQUEST gets the plain inline result, never a task;
- strong creation consistency: the moment a CreateTaskResult exists, a
  tasks/get for its id resolves;
- error mapping: unknown/expired ids -> -32602, McpError during execution ->
  status "failed" with the JSON-RPC error inline, ``isError: true`` tool
  results -> status "completed" (tool failures are successful exchanges);
- capability gating on tasks/* methods (-32021 for non-declaring clients)
  and the cooperative tasks/cancel ack.
"""

import asyncio

import pytest

from modern.errors import (
    InternalError,
    InvalidParamsError,
    McpError,
    MissingClientCapabilityError,
)
from modern.meta import RequestMeta
from modern.tasks_ext import (
    TASKS_EXTENSION_ID,
    TasksExtension,
    TaskStore,
    client_declares_tasks,
)
from modern.types import (
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    ClientCapabilities,
    Implementation,
)


def make_meta(*, tasks: bool) -> RequestMeta:
    """A parsed RequestMeta, with or without the tasks extension declared."""
    extensions = {TASKS_EXTENSION_ID: {}} if tasks else None
    return RequestMeta(
        protocol_version="2026-07-28",
        client_info=Implementation(name="TestClient", version="1.0.0"),
        client_capabilities=ClientCapabilities(extensions=extensions),
        log_level=None,
        progress_token=None,
        trace={},
    )


@pytest.fixture
def ext() -> TasksExtension:
    return TasksExtension()


async def poll_until_terminal(ext: TasksExtension, task_id: str, meta: RequestMeta) -> dict:
    """Poll tasks/get like a real client until the task leaves 'working'."""
    for _ in range(100):
        detailed = await ext.handle_get({"taskId": task_id}, meta)
        if detailed["status"] != "working":
            return detailed
        await asyncio.sleep(0.01)
    pytest.fail("task never reached a terminal status")


# ---------------------------------------------------------------------------
# Lifecycle: create -> working -> completed, observed via tasks/get
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_create_working_completed_via_polling(self, ext):
        meta = make_meta(tasks=True)
        gate = asyncio.Event()

        async def execute() -> dict:
            await gate.wait()
            return {
                "resultType": "complete",
                "content": [{"type": "text", "text": "catalog rebuilt"}],
            }

        created = await ext.maybe_run_as_task(execute, meta)

        # CreateTaskResult: resultType "task", Task fields FLATTENED at the
        # top level (no nested "task" object), ttlMs required.
        assert created["resultType"] == "task"
        assert created["status"] == "working"
        assert isinstance(created["taskId"], str)
        assert created["taskId"]
        assert "ttlMs" in created
        assert created["pollIntervalMs"] > 0
        assert "task" not in created  # the 2025-11-25 nesting is gone
        # Timestamps are ISO 8601, Z-suffixed like the spec examples.
        assert created["createdAt"].endswith("Z")
        assert created["lastUpdatedAt"].endswith("Z")

        # Strong consistency: a poll issued immediately after creation MUST
        # resolve — the task is durably created before the result returns.
        polled = await ext.handle_get({"taskId": created["taskId"]}, meta)
        assert polled["resultType"] == "complete"  # "task" marks CREATION only
        assert polled["status"] == "working"
        assert "result" not in polled  # no result until terminal

        gate.set()
        done = await poll_until_terminal(ext, created["taskId"], meta)
        assert done["status"] == "completed"
        # The result field holds exactly what the underlying tools/call
        # would have returned, verbatim.
        assert done["result"]["content"][0]["text"] == "catalog rebuilt"
        assert done["result"]["resultType"] == "complete"
        assert "error" not in done

    async def test_task_ids_are_unique_and_unguessable_shaped(self, ext):
        meta = make_meta(tasks=True)

        async def execute() -> dict:
            return {"resultType": "complete", "content": []}

        first = await ext.maybe_run_as_task(execute, meta)
        second = await ext.maybe_run_as_task(execute, meta)
        assert first["taskId"] != second["taskId"]
        assert len(first["taskId"]) >= 32  # uuid4 hex-with-hyphens length
        # Drain both background runners so the event loop closes clean.
        for created in (first, second):
            await poll_until_terminal(ext, created["taskId"], meta)

    async def test_tool_error_result_is_completed_not_failed(self, ext):
        """CallToolResult with isError: true is a SUCCESSFUL protocol
        exchange — MUST land in "completed", never "failed"."""
        meta = make_meta(tasks=True)

        async def execute() -> dict:
            return {
                "resultType": "complete",
                "content": [{"type": "text", "text": "boom"}],
                "isError": True,
            }

        created = await ext.maybe_run_as_task(execute, meta)
        done = await poll_until_terminal(ext, created["taskId"], meta)
        assert done["status"] == "completed"
        assert done["result"]["isError"] is True

    async def test_mcp_error_during_execution_becomes_failed(self, ext):
        """ "failed" is reserved for JSON-RPC errors; the error object rides
        inline on tasks/get (this replaced tasks/result)."""
        meta = make_meta(tasks=True)

        async def execute() -> dict:
            raise InternalError("database exploded")

        created = await ext.maybe_run_as_task(execute, meta)
        done = await poll_until_terminal(ext, created["taskId"], meta)
        assert done["status"] == "failed"
        assert done["error"]["code"] == -32603
        assert done["error"]["message"] == "database exploded"
        assert "result" not in done

    async def test_unexpected_exception_becomes_failed_with_internal_error(self, ext):
        meta = make_meta(tasks=True)

        async def execute() -> dict:
            raise RuntimeError("surprise")

        created = await ext.maybe_run_as_task(execute, meta)
        done = await poll_until_terminal(ext, created["taskId"], meta)
        assert done["status"] == "failed"
        assert done["error"]["code"] == -32603


# ---------------------------------------------------------------------------
# The immediate-result path (extension not declared on the request)
# ---------------------------------------------------------------------------


class TestImmediatePath:
    async def test_non_declaring_client_gets_inline_result(self, ext):
        """Server MUST NOT return CreateTaskResult to a client that did not
        declare the extension ON THIS REQUEST — it runs inline instead."""
        meta = make_meta(tasks=False)
        ran = False

        async def execute() -> dict:
            nonlocal ran
            ran = True
            return {"resultType": "complete", "content": [{"type": "text", "text": "done"}]}

        result = await ext.maybe_run_as_task(execute, meta)
        assert ran  # awaited synchronously, not detached
        assert result["resultType"] == "complete"
        assert "taskId" not in result

    async def test_inline_errors_propagate_to_the_caller(self, ext):
        """Without a task there is nowhere to park an error — it surfaces as
        the request's own JSON-RPC error, exactly like core tools/call."""
        meta = make_meta(tasks=False)

        async def execute() -> dict:
            raise InternalError("database exploded")

        with pytest.raises(McpError):
            await ext.maybe_run_as_task(execute, meta)

    def test_capability_detection_reads_per_request_extensions(self):
        assert client_declares_tasks(ClientCapabilities(extensions={TASKS_EXTENSION_ID: {}}))
        assert not client_declares_tasks(ClientCapabilities())
        assert not client_declares_tasks(ClientCapabilities(extensions={"com.example/other": {}}))


# ---------------------------------------------------------------------------
# tasks/get, tasks/update, tasks/cancel error handling + gating
# ---------------------------------------------------------------------------


class TestMethodHandlers:
    async def test_unknown_task_id_is_invalid_params(self, ext):
        meta = make_meta(tasks=True)
        with pytest.raises(InvalidParamsError, match="not found"):
            await ext.handle_get({"taskId": "no-such-task"}, meta)
        with pytest.raises(InvalidParamsError):
            await ext.handle_update({"taskId": "no-such-task", "inputResponses": {}}, meta)
        with pytest.raises(InvalidParamsError):
            await ext.handle_cancel({"taskId": "no-such-task"}, meta)

    async def test_missing_task_id_param_is_invalid_params(self, ext):
        meta = make_meta(tasks=True)
        with pytest.raises(InvalidParamsError):
            await ext.handle_get({}, meta)

    async def test_non_declaring_client_gets_32021_on_tasks_methods(self, ext):
        """tasks/get, update, and cancel all require the extension capability
        on the request itself (core code -32021, not the extension text's
        legacy -32003)."""
        meta = make_meta(tasks=False)
        for handler in (ext.handle_get, ext.handle_update, ext.handle_cancel):
            with pytest.raises(MissingClientCapabilityError) as excinfo:
                await handler({"taskId": "anything"}, meta)
            assert excinfo.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY
            assert excinfo.value.data == {
                "requiredCapabilities": {"extensions": {TASKS_EXTENSION_ID: {}}}
            }

    async def test_expired_task_is_purged_then_not_found(self):
        """TTL backstop: servers MAY fail/purge expired tasks; purging then
        returning not-found is explicitly compliant."""
        ext = TasksExtension(ttl_ms=0)  # expires immediately
        meta = make_meta(tasks=True)

        async def execute() -> dict:
            return {"resultType": "complete", "content": []}

        created = await ext.maybe_run_as_task(execute, meta)
        with pytest.raises(InvalidParamsError, match="expired"):
            await ext.handle_get({"taskId": created["taskId"]}, meta)
        # Purged: the second poll is a plain not-found.
        with pytest.raises(InvalidParamsError, match="not found"):
            await ext.handle_get({"taskId": created["taskId"]}, meta)

    async def test_update_acks_with_empty_result(self, ext):
        """tasks/update MUST ack with an empty result; responses for keys
        that are not outstanding are ignored (none ever are here, because
        regenerate_catalog never pauses for input)."""
        meta = make_meta(tasks=True)
        gate = asyncio.Event()

        async def execute() -> dict:
            await gate.wait()
            return {"resultType": "complete", "content": []}

        created = await ext.maybe_run_as_task(execute, meta)
        ack = await ext.handle_update(
            {"taskId": created["taskId"], "inputResponses": {"stale-key": {"action": "accept"}}},
            meta,
        )
        assert ack == {"resultType": "complete"}
        gate.set()
        done = await poll_until_terminal(ext, created["taskId"], meta)
        assert done["status"] == "completed"

    async def test_cancel_acks_and_cancels_the_running_work(self, ext):
        meta = make_meta(tasks=True)
        started = asyncio.Event()

        async def execute() -> dict:
            started.set()
            await asyncio.sleep(60)  # would block a full minute if not cancelled
            return {"resultType": "complete", "content": []}

        created = await ext.maybe_run_as_task(execute, meta)
        await started.wait()

        ack = await ext.handle_cancel({"taskId": created["taskId"]}, meta)
        assert ack == {"resultType": "complete"}  # ack-only; no task object

        done = await poll_until_terminal(ext, created["taskId"], meta)
        assert done["status"] == "cancelled"
        assert "result" not in done
        assert "error" not in done

    async def test_cancel_after_completion_is_still_an_ack(self, ext):
        """Cancellation is cooperative: acking a cancel for an already
        terminal task is fine, and the terminal status does not change."""
        meta = make_meta(tasks=True)

        async def execute() -> dict:
            return {"resultType": "complete", "content": []}

        created = await ext.maybe_run_as_task(execute, meta)
        done = await poll_until_terminal(ext, created["taskId"], meta)
        assert done["status"] == "completed"

        ack = await ext.handle_cancel({"taskId": created["taskId"]}, meta)
        assert ack == {"resultType": "complete"}
        after = await ext.handle_get({"taskId": created["taskId"]}, meta)
        assert after["status"] == "completed"  # terminal states are immutable


# ---------------------------------------------------------------------------
# Wiring surface: capability fragment + method table
# ---------------------------------------------------------------------------


class TestWiring:
    def test_capability_fragment(self, ext):
        # No settings are defined for this extension: {} means "supported".
        assert ext.capability_fragment() == {TASKS_EXTENSION_ID: {}}

    def test_method_table_has_exactly_the_three_extension_methods(self, ext):
        methods = ext.methods()
        # tasks/list and tasks/result are GONE in the modern extension —
        # exposing them would resurrect the 2025-11-25 wire format.
        assert set(methods) == {"tasks/get", "tasks/update", "tasks/cancel"}

    def test_register_with_adds_every_method(self, ext):
        added: dict[str, object] = {}
        capabilities: dict[str, dict] = {}

        class FakeRegistry:
            # Mirrors ModernRegistry.add_method's real signature, including
            # the optional capability_fragment (register_with declares the
            # extension's capability so server/discover advertises it).
            def add_method(
                self,
                name: str,
                handler: object,
                capability_fragment: dict[str, dict] | None = None,
            ) -> None:
                added[name] = handler
                if capability_fragment:
                    capabilities.update(capability_fragment)

        ext.register_with(FakeRegistry())
        assert set(added) == {"tasks/get", "tasks/update", "tasks/cancel"}
        # The extension MUST be advertised, or a spec-compliant client will
        # refuse to call tasks/* (clients MUST NOT invoke an undeclared
        # extension). Regression guard for the discover wiring.
        assert "io.modelcontextprotocol/tasks" in capabilities

    def test_store_is_shared_and_injectable(self):
        store = TaskStore()
        ext = TasksExtension(store)
        assert ext.store is store
