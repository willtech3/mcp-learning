"""
Dispatcher — the JSON-RPC method router for MCP 2026-07-28.

Transport-agnostic core of the modern server: the HTTP layer and the stdio
driver both feed single JSON-RPC messages into :meth:`Dispatcher.handle`
and get back a complete response dict, a :class:`ListenOutcome` (for the
one long-lived method), or ``None`` (notifications get no reply).

The routing story IS the protocol story:

- **``_meta`` before methods (SEP-2575).**  Every request is validated for
  the required per-request metadata trio (protocolVersion/clientInfo/
  clientCapabilities) before the method is even considered — a stateless
  server cannot process a request whose context it cannot read.  Missing
  fields are ``-32602``; a version we don't serve is ``-32022`` with the
  full supported list so clients can renegotiate.  ONE deliberate
  exception: methods REMOVED from the modern era (initialize, ping, ...)
  are answered first, without metadata demands — a legacy client's
  ``initialize`` carries no modern ``_meta``, and the spec says a
  modern-only server SHOULD name its supported versions in whatever error
  it returns to ``initialize`` (legacy clients have no fall-forward
  mechanism).  Those methods get teaching ``-32601`` errors naming their
  replacement.

- **MRTR gate (SEP-2322).**  Exactly three methods — ``tools/call``,
  ``prompts/get``, ``resources/read`` — run through the MRTR engine and may
  return ``resultType: "input_required"``.  A server MUST NOT send it on
  any other request, which the routing enforces structurally: no other
  path even touches the engine.

- **Caching hints (SEP-2549).**  ``server/discover``, the four list
  methods, and ``resources/read`` — and ONLY those — carry the required
  ``ttlMs``/``cacheScope``.  (``completion/complete`` results are built as
  plain resultType-only dicts on purpose: the spec's cacheable-method list
  does not include it.)

- **Pagination.**  Opaque cursors (base64url of a JSON offset — clients
  MUST NOT parse them, and nothing breaks if they try, it is just an
  offset).  Invalid cursor -> ``-32602``.

- **Extensions.**  Methods registered on the registry (tasks/*, SEP-2663)
  are consulted before declaring ``-32601``; ``resources/directory/read``
  (skills, SEP-2640) is served whenever a resource provider is mounted.

- **subscriptions/listen (SEP-2575).**  Returns a :class:`ListenOutcome`
  for the transport to stream: the acknowledgment, a queue of pre-tagged
  notifications, and a graceful-close callable.  The broker owns the
  subscription state (request-scoped, not connection-scoped).

Errors ride McpError -> JSON-RPC error response; ``http_status`` on the
error is used by the HTTP layer only (stdio has no status line).

Spec: MCP 2026-07-28 basic/{index,versioning,patterns/*}, server/*.
"""

import asyncio
import base64
import binascii
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from modern.broker import ListenOutcome
from modern.context import ModernContext
from modern.errors import (
    InternalError,
    InvalidParamsError,
    InvalidRequestError,
    McpError,
    MethodNotFoundError,
)
from modern.meta import RequestMeta, parse_request_meta
from modern.mrtr import RequestStateCodec, run_with_mrtr
from modern.registry import ListCachePolicy, ModernRegistry
from modern.types import (
    JSONRPC_VERSION,
    METHOD_NOT_FOUND,
    SUPPORTED_VERSIONS,
    DiscoverResult,
    Implementation,
    SubscriptionFilter,
)

logger = logging.getLogger(__name__)

#: Max completion values returned in a single completion/complete result
#: (spec: completion.values is capped at 100). The registry hands us up to
#: one past this so we can set completion.hasMore honestly.
_MAX_COMPLETION_VALUES = 100


@dataclass
class RequestEnv:
    """Transport-supplied facts about the request being handled.

    ``notify`` is the REQUEST-SCOPED notification sink: progress and log
    messages emitted while handling this request go here (the transport
    delivers them on this request's own response stream — never on a
    subscriptions/listen stream).
    """

    transport: Literal["http", "stdio"]
    principal: Any | None
    notify: Callable[[dict[str, Any]], Awaitable[None]]


# ``subscriptions/listen`` returns a ListenOutcome instead of a plain
# response; the transport streams it (ack first, then the broker's queued
# notifications, then a graceful-close result).  This is ONE class shared
# with modern/broker.py and modern/http.py — re-exported here for the
# dispatcher's public contract.  (It must not be a second definition:
# ``handle`` uses ``isinstance(result, ListenOutcome)`` to tell a stream
# apart from a buffered response, and a duplicate class would fail that
# check and wrongly wrap the stream in a JSON response.)


#: Methods that existed in the legacy era and were REMOVED in 2026-07-28.
#: Each maps to a teaching message naming the replacement (and optional
#: error data).  Returned as -32601 Method not found — the code a modern
#: server gives for any RPC it does not implement.
_REMOVED_METHODS: dict[str, tuple[str, dict[str, Any] | None]] = {
    "initialize": (
        "'initialize' was removed in MCP 2026-07-28 (SEP-2575): the protocol is "
        "stateless — there is no handshake. Call 'server/discover' for capabilities, "
        "or send any request with the required '_meta' keys "
        "(io.modelcontextprotocol/protocolVersion, /clientInfo, /clientCapabilities).",
        {"supported": list(SUPPORTED_VERSIONS)},
    ),
    "notifications/initialized": (
        "'notifications/initialized' was removed in MCP 2026-07-28 (SEP-2575): "
        "there is no lifecycle to acknowledge — every request is self-describing.",
        None,
    ),
    "ping": (
        "'ping' was removed in MCP 2026-07-28 (SEP-2575). There is no protocol-level "
        "keep-alive; on Streamable HTTP, SSE comment lines serve that purpose.",
        None,
    ),
    "logging/setLevel": (
        "'logging/setLevel' was removed in MCP 2026-07-28 (SEP-2575): set the "
        "'io.modelcontextprotocol/logLevel' key in each request's '_meta' instead "
        "(the logging feature as a whole is deprecated, SEP-2577).",
        None,
    ),
    "resources/subscribe": (
        "'resources/subscribe' was removed in MCP 2026-07-28 (SEP-2575): open a "
        "'subscriptions/listen' stream with a 'resourceSubscriptions' filter instead.",
        None,
    ),
    "resources/unsubscribe": (
        "'resources/unsubscribe' was removed in MCP 2026-07-28 (SEP-2575): close the "
        "'subscriptions/listen' stream and open a new one with the desired filter.",
        None,
    ),
    "tasks/list": (
        "'tasks/list' does not exist in MCP 2026-07-28: tasks moved to the "
        "'io.modelcontextprotocol/tasks' extension (SEP-2663), which defines no "
        "list method — track the task ids you receive.",
        None,
    ),
    "tasks/result": (
        "'tasks/result' does not exist in MCP 2026-07-28: the tasks extension "
        "(SEP-2663) uses a polling model — call 'tasks/get' until the task is "
        "terminal; the result rides on the terminal response.",
        None,
    ),
}


def _encode_cursor(offset: int) -> str:
    """Mint an opaque pagination cursor (base64url of a JSON offset).

    Opaque BY CONTRACT, not by obfuscation: clients MUST NOT parse cursors,
    and this server honors any cursor it minted regardless of page-size
    changes because it is self-contained (statelessness: cursors must
    survive landing on a different server instance).
    """
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode("ascii")).decode("ascii")


def _decode_cursor(cursor: Any) -> int:
    """Open a cursor; every malformation is the spec's -32602."""
    if not isinstance(cursor, str):
        raise InvalidParamsError("Invalid pagination cursor: must be a string")
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
    except (ValueError, binascii.Error) as exc:
        raise InvalidParamsError("Invalid pagination cursor") from exc
    offset = payload.get("o") if isinstance(payload, dict) else None
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise InvalidParamsError("Invalid pagination cursor")
    return offset


class Dispatcher:
    """Routes validated modern-era requests to the registry and broker."""

    def __init__(
        self,
        registry: ModernRegistry,
        codec: RequestStateCodec,
        server_info: Implementation,
        instructions: str | None,
        broker: Any,
        cache_policy: ListCachePolicy,
        discover_ttl_ms: int = 3_600_000,
        *,
        page_size: int = 50,
        resource_update_hooks: dict[str, Callable[[dict[str, Any]], str]] | None = None,
        task_runner: Callable[..., Awaitable[dict[str, Any]]] | None = None,
        task_tool_names: set[str] | None = None,
    ) -> None:
        self.registry = registry
        self.codec = codec
        self.server_info = server_info
        self.instructions = instructions
        self.broker = broker
        self.cache_policy = cache_policy
        self.discover_ttl_ms = discover_ttl_ms
        self.page_size = page_size
        #: Post-call hook table (integrator-supplied): tool name -> function
        #: from call arguments to the resource URI that call mutates.  After
        #: a successful call, broker.publish_resource_updated(uri) fires so
        #: listen streams subscribed to that URI hear about the change.
        self.resource_update_hooks = resource_update_hooks or {}
        #: Optional tasks-extension wiring (SEP-2663): task_runner is
        #: TasksExtension.maybe_run_as_task; task_tool_names says which
        #: tools it wraps (regenerate_catalog).
        self.task_runner = task_runner
        self.task_tool_names = task_tool_names or set()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def handle(  # noqa: PLR0911 — envelope validation legitimately branches
        self, message: dict[str, Any], env: RequestEnv
    ) -> dict[str, Any] | ListenOutcome | None:
        """Process one JSON-RPC message; never raises for protocol failures.

        Returns the full JSON-RPC response dict, a ListenOutcome for
        ``subscriptions/listen``, or None for notifications (which MUST NOT
        be answered).
        """
        # -- JSON-RPC envelope validation (before anything MCP-specific) --
        if not isinstance(message, dict) or message.get("jsonrpc") != JSONRPC_VERSION:
            return InvalidRequestError(
                "Not a JSON-RPC 2.0 message (batching is not supported in MCP)"
            ).to_error_response(None)

        if "id" not in message:
            # Notification: no reply, ever.  The only meaningful client
            # notification is notifications/cancelled, which the stdio
            # driver intercepts BEFORE dispatch (it owns the task table);
            # anything reaching here is silently ignored per spec.
            return None

        request_id = message.get("id")
        # MCP is stricter than base JSON-RPC: ids MUST be string or integer,
        # never null (and JSON true/false are not ids either).
        if isinstance(request_id, bool) or not isinstance(request_id, str | int):
            return InvalidRequestError(
                "Request id must be a string or integer (null ids are not allowed)"
            ).to_error_response(None)

        method = message.get("method")
        if not isinstance(method, str):
            return InvalidRequestError("Request method must be a string").to_error_response(
                request_id
            )

        params = message.get("params")
        try:
            # Removed legacy methods first — see the module docstring for
            # why these skip _meta validation (legacy clients cannot send
            # modern _meta, and initialize SHOULD learn supported versions).
            removed = _REMOVED_METHODS.get(method)
            if removed is not None:
                teaching_message, data = removed
                raise McpError(METHOD_NOT_FOUND, teaching_message, data=data, http_status=404)

            # _meta before methods: SEP-2575's stateless contract.  A
            # non-dict params fails inside parse_request_meta (-32602), so
            # params is guaranteed to be a dict past this line.
            meta = parse_request_meta(params)
            assert isinstance(params, dict)
            result = await self._route(method, params, meta, env, request_id)
        except McpError as exc:
            return exc.to_error_response(request_id)
        except asyncio.CancelledError:
            raise  # cancellation must unwind the transport's task cleanly
        except Exception:
            logger.exception("Internal error handling %s", method)
            return InternalError().to_error_response(request_id)

        if isinstance(result, ListenOutcome):
            return result
        return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    async def _route(  # noqa: PLR0911 — one return per protocol method, by design
        self,
        method: str,
        params: dict[str, Any],
        meta: RequestMeta,
        env: RequestEnv,
        request_id: str | int,
    ) -> dict[str, Any] | ListenOutcome:
        if method == "server/discover":
            return self._discover()
        if method == "tools/list":
            return self._paginated("tools", self.registry.list_tools(), params)
        if method == "resources/list":
            return self._paginated("resources", self.registry.list_resources(), params)
        if method == "resources/templates/list":
            return self._paginated(
                "resourceTemplates", self.registry.list_resource_templates(), params
            )
        if method == "prompts/list":
            return self._paginated("prompts", self.registry.list_prompts(), params)
        if method == "tools/call":
            return await self._tools_call(params, meta, env, request_id)
        if method == "resources/read":
            return await self._resources_read(params, meta, env, request_id)
        if method == "prompts/get":
            return await self._prompts_get(params, meta, env, request_id)
        if method == "completion/complete":
            return self._complete(params)
        if method == "subscriptions/listen":
            return await self._listen(params, request_id)
        if method == "resources/directory/read" and self.registry.resource_providers:
            uri = params.get("uri")
            if not isinstance(uri, str):
                raise InvalidParamsError("resources/directory/read requires a string 'uri'")
            listing = await self.registry.directory_read(uri)
            return {
                "resultType": "complete",
                "resources": [entry.to_wire() for entry in listing],
            }

        # Extension methods (tasks/get, tasks/update, tasks/cancel, ...)
        # registered via registry.add_method — consulted before -32601.
        extension = self.registry.extension_methods.get(method)
        if extension is not None:
            result = await extension(params, meta)
            result.setdefault("resultType", "complete")
            return result

        raise MethodNotFoundError(f"Method not found: {method}")

    # ------------------------------------------------------------------
    # server/discover
    # ------------------------------------------------------------------

    def _discover(self) -> dict[str, Any]:
        """The replacement for ``initialize`` — and, unlike it, cacheable.

        supportedVersions advertises the DUAL-ERA list: this dispatcher only
        speaks 2026-07-28, but the deployment as a whole still answers
        legacy versions through FastMCP, and discover describes the server,
        not the code path.
        """
        return DiscoverResult(
            supported_versions=list(SUPPORTED_VERSIONS),
            capabilities=self.registry.capabilities(),
            server_info=self.server_info,
            instructions=self.instructions,
            ttl_ms=self.discover_ttl_ms,
            cache_scope=self.cache_policy.cache_scope,
        ).to_wire()

    # ------------------------------------------------------------------
    # List methods: pagination + SEP-2549 caching hints
    # ------------------------------------------------------------------

    def _paginated(self, key: str, items: list[Any], params: dict[str, Any]) -> dict[str, Any]:
        offset = 0
        cursor = params.get("cursor")
        if cursor is not None:
            offset = _decode_cursor(cursor)
        page = items[offset : offset + self.page_size]
        result: dict[str, Any] = {
            "resultType": "complete",
            key: [item.to_wire() for item in page],
            # Required caching hints (SEP-2549).  Every page of one list
            # request carries the same cacheScope (spec MUST).
            "ttlMs": self.cache_policy.ttl_ms,
            "cacheScope": self.cache_policy.cache_scope,
        }
        if offset + self.page_size < len(items):
            result["nextCursor"] = _encode_cursor(offset + self.page_size)
        return result

    # ------------------------------------------------------------------
    # The three MRTR-capable methods
    # ------------------------------------------------------------------

    def _principal_id(self, env: RequestEnv) -> str:
        """Identity bound into requestState: subject claim, or "anon"."""
        subject = getattr(env.principal, "subject", None)
        return subject if isinstance(subject, str) and subject else "anon"

    def _context(
        self,
        meta: RequestMeta,
        env: RequestEnv,
        request_id: str | int,
        memo: dict[str, Any],
    ) -> ModernContext:
        return ModernContext(
            meta=meta,
            request_id=request_id,
            principal=env.principal,
            memo=memo,
            notify=env.notify,
            registry=self.registry,
        )

    async def _tools_call(
        self,
        params: dict[str, Any],
        meta: RequestMeta,
        env: RequestEnv,
        request_id: str | int,
    ) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str):
            raise InvalidParamsError("tools/call requires a string 'name'")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise InvalidParamsError("tools/call 'arguments' must be an object")
        if not self.registry.has_tool(name):
            # Unknown tool is a PROTOCOL error (-32602) — reserve isError
            # results for failures of tools that exist.  (-32002 is retired.)
            raise InvalidParamsError(f"Unknown tool: {name}")

        async def execute(collected: dict[str, Any]) -> dict[str, Any]:
            ctx = self._context(meta, env, request_id, collected)

            async def run() -> dict[str, Any]:
                return await self.registry.call_tool(name, arguments, ctx)

            if self.task_runner is not None and name in self.task_tool_names:
                # Tasks extension (SEP-2663): declaring clients get a task
                # handle immediately; everyone else awaits inline.
                return await self.task_runner(run, meta)
            return await run()

        result = await run_with_mrtr(
            execute,
            method="tools/call",
            name=name,
            arguments=arguments,
            params=params,
            codec=self.codec,
            principal_id=self._principal_id(env),
        )

        # Post-call resource-update hook: a successful state-changing call
        # (checkout/return) invalidates the resource it touched; subscribed
        # listen streams hear it as notifications/resources/updated.
        if (
            result.get("resultType") == "complete"
            and not result.get("isError")
            and name in self.resource_update_hooks
            and self.broker is not None
        ):
            uri = self.resource_update_hooks[name](arguments)
            self.broker.publish_resource_updated(uri)

        return result

    async def _resources_read(
        self,
        params: dict[str, Any],
        meta: RequestMeta,
        env: RequestEnv,
        request_id: str | int,
    ) -> dict[str, Any]:
        uri = params.get("uri")
        if not isinstance(uri, str):
            raise InvalidParamsError("resources/read requires a string 'uri'")

        async def execute(collected: dict[str, Any]) -> dict[str, Any]:
            ctx = self._context(meta, env, request_id, collected)
            contents = await self.registry.read_resource(uri, ctx)
            return {
                "resultType": "complete",
                "contents": contents,
                # resources/read is on SEP-2549's must-carry-hints list.
                "ttlMs": self.cache_policy.ttl_ms,
                "cacheScope": self.cache_policy.cache_scope,
            }

        # The URI is the "name" for state binding (it IS the salient
        # parameter, mirroring the Mcp-Name header rule on HTTP).
        return await run_with_mrtr(
            execute,
            method="resources/read",
            name=uri,
            arguments={},
            params=params,
            codec=self.codec,
            principal_id=self._principal_id(env),
        )

    async def _prompts_get(
        self,
        params: dict[str, Any],
        meta: RequestMeta,
        env: RequestEnv,
        request_id: str | int,
    ) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str):
            raise InvalidParamsError("prompts/get requires a string 'name'")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise InvalidParamsError("prompts/get 'arguments' must be an object")

        async def execute(collected: dict[str, Any]) -> dict[str, Any]:
            ctx = self._context(meta, env, request_id, collected)
            return await self.registry.get_prompt(name, arguments, ctx)

        return await run_with_mrtr(
            execute,
            method="prompts/get",
            name=name,
            arguments=arguments,
            params=params,
            codec=self.codec,
            principal_id=self._principal_id(env),
        )

    # ------------------------------------------------------------------
    # completion/complete
    # ------------------------------------------------------------------

    def _complete(self, params: dict[str, Any]) -> dict[str, Any]:
        ref = params.get("ref")
        argument = params.get("argument")
        if not isinstance(ref, dict) or not isinstance(argument, dict):
            raise InvalidParamsError("completion/complete requires 'ref' and 'argument' objects")
        arg_name = argument.get("name")
        value = argument.get("value", "")
        if not isinstance(arg_name, str) or not isinstance(value, str):
            raise InvalidParamsError("completion argument requires string 'name' and 'value'")
        context = params.get("context") or {}
        context_args = context.get("arguments") if isinstance(context, dict) else None

        # The registry returns up to one past the 100-value cap so we can
        # tell "exactly 100" from "100 and more" and report hasMore honestly.
        values = self.registry.completion(ref, arg_name, value, context_args)
        truncated = values[:_MAX_COMPLETION_VALUES]
        has_more = len(values) > _MAX_COMPLETION_VALUES
        completion: dict[str, Any] = {"values": truncated, "hasMore": has_more}
        # total is optional; report it only when we actually know it (no more
        # results beyond what we returned). When hasMore is true the true
        # count is unknown, so omit it rather than report the truncated length.
        if not has_more:
            completion["total"] = len(truncated)
        # NOTE: deliberately NOT a CacheableResult — completion/complete is
        # absent from SEP-2549's list of methods that carry caching hints.
        return {"resultType": "complete", "completion": completion}

    # ------------------------------------------------------------------
    # subscriptions/listen
    # ------------------------------------------------------------------

    async def _listen(self, params: dict[str, Any], request_id: str | int) -> ListenOutcome:
        raw_filter = params.get("notifications")
        if not isinstance(raw_filter, dict):
            raise InvalidParamsError(
                "subscriptions/listen requires a 'notifications' filter object "
                "(the opt-in is mandatory: servers MUST NOT send unrequested types)"
            )
        try:
            subscription_filter = SubscriptionFilter.model_validate(raw_filter)
        except ValidationError as exc:
            raise InvalidParamsError(
                f"Invalid subscription filter: {exc.error_count()} validation error(s)"
            ) from exc
        # The broker owns everything from here: ack construction (honored
        # subset), subscriptionId tagging, queue fan-out, graceful close.
        return await self.broker.listen(request_id, subscription_filter)
