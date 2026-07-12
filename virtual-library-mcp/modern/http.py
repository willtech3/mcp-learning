"""
Streamable HTTP binding + dual-era endpoint for MCP 2026-07-28.

MCP 2026-07-28 rewrote Streamable HTTP around one idea: **each JSON-RPC
message is its own HTTP POST, and each request's reply is its own response**
— either a single ``application/json`` object or a request-scoped
``text/event-stream``.  Everything connection-shaped was removed (SEP-2567,
SEP-2575): no ``Mcp-Session-Id`` sessions, no standalone GET SSE stream, no
``Last-Event-ID`` resumability, no server-initiated JSON-RPC requests.  A
broken stream simply loses the in-flight request; the client re-issues it
with a NEW id.

This module implements the server side of that binding, plus the "dual-era"
front door that lets ONE endpoint serve both 2026-07-28 clients and legacy
(``initialize``-handshake) clients side by side:

- **Era classification** (Versioning: Backward Compatibility).  Era is
  decided per POST from the ``MCP-Protocol-Version`` header and the body:
  a legacy version header or an ``initialize`` method routes to the legacy
  (FastMCP) app; a present header with any other value, or modern ``_meta``
  in the body, routes to the modern pipeline; anything ambiguous defaults to
  legacy, because pre-2025-06-18 clients sent no header at all.  GET/DELETE
  go to the legacy app too (legacy sessions need them) — a modern-only
  deployment would answer ``405 Method Not Allowed`` instead, which is what
  the modern app by itself does.

- **Header mirroring & validation** (SEP-2243).  Modern POSTs mirror body
  fields into headers — ``MCP-Protocol-Version``, ``Mcp-Method``, and (for
  tools/call, resources/read, prompts/get) ``Mcp-Name`` — so intermediaries
  can route and rate-limit without parsing JSON.  Mirrors invite lies: a
  proxy might route on a header naming one tool while the body executes
  another.  A server that processes the body therefore MUST verify header ==
  body (Base64 ``=?base64?...?=`` sentinel decoded first) and reject any
  mismatch, missing required header, or malformed value with HTTP 400 +
  JSON-RPC ``-32020`` HeaderMismatch.  Tool arguments annotated with
  ``x-mcp-header`` in the input schema are likewise mirrored as
  ``Mcp-Param-{Name}`` headers and validated here; unrecognized ``Mcp-Param-*``
  headers are ignored per RFC 9110.

- **Errors ride the HTTP status.**  Unlike the 2025 era (everything tunneled
  in HTTP 200), the status line now carries meaning: ``-32020``/``-32021``/
  ``-32022``/``-32602`` → 400, ``-32601`` → 404 (deliberately distinguishable
  from a legacy HTTP+SSE server's bare 404 because the body is a JSON-RPC
  error — this is how dual-era clients detect a modern server), ``-32603`` →
  500.  Notification POSTs get ``202 Accepted`` with no body; the spec
  defines no client→server notifications over HTTP in this revision and no
  header requirements for them, so they are accepted without ``Mcp-Method``.

- **Request-scoped SSE.**  If a request opts into progress
  (``_meta.progressToken``) or per-request logging
  (``_meta["io.modelcontextprotocol/logLevel"]``, deprecated SEP-2577), the
  response is an SSE stream: ``notifications/progress`` /
  ``notifications/message`` events as the handler emits them, then the final
  JSON-RPC response, then EOF.  ``subscriptions/listen`` (SEP-2575) is ALWAYS
  SSE: acknowledgment first, then only the opted-in change notifications,
  with ``:keepalive`` comment lines during quiet periods (comments are
  ignored by SSE parsers by definition).  ``X-Accel-Buffering: no`` is sent
  on every stream so reverse proxies do not buffer events.  Frames never
  carry an ``id:`` field — SSE event ids fed resumability, which is gone.

- **Disconnect IS cancellation.**  With one response stream per request,
  closing it is an unambiguous cancellation signal — ``notifications/
  cancelled`` is stdio-only now.  The server MUST stop work as soon as
  practical and MUST NOT send anything further for that request; here a
  disconnect cancels the dispatch task and unregisters any listen
  subscription, silently.

- **Origin validation.**  Servers MUST validate ``Origin`` to prevent DNS
  rebinding: a browser page on attacker.example can address 127.0.0.1, but
  it cannot forge its ``Origin`` header.  Invalid origin → ``403 Forbidden``
  (body MAY be an id-less JSON-RPC error).  Loopback origins are allowed by
  default since this is a local teaching server.

Authorization is deliberately pluggable: :func:`create_modern_asgi` takes an
optional bearer-token ``verifier`` plus 401/403 ``WWW-Authenticate`` challenge
builders (see modern/auth/*), keeping this module free of JWT concerns.
Well-known PRM / demo-AS routes are passed in as ``extra_routes`` and mounted
OUTSIDE the auth gate (well-known documents must be publicly readable).

Spec references: MCP 2026-07-28 basic/transports/streamable-http (SEP-2243,
SEP-2567, SEP-2575), basic/patterns/subscriptions, basic/patterns/
cancellation, basic/versioning (dual-era matrix).
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Mount, Route

from modern.broker import ListenOutcome
from modern.errors import (
    HeaderMismatchError,
    InternalError,
    InvalidRequestError,
    McpError,
    ParseError,
)
from modern.meta import decode_header_value
from modern.types import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    JSONRPC_VERSION,
    LEGACY_VERSIONS,
    META_LOG_LEVEL,
    META_PROGRESS_TOKEN,
    META_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    error_response,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Header names (comparison is case-insensitive per RFC 9110; the spec's own
# examples mix "MCP-Protocol-Version" with "Mcp-*" capitalization).
# ---------------------------------------------------------------------------

HEADER_PROTOCOL_VERSION = "MCP-Protocol-Version"
HEADER_METHOD = "Mcp-Method"
HEADER_NAME = "Mcp-Name"
#: Prefix for SEP-2243 custom headers mirrored from x-mcp-header annotations.
HEADER_PARAM_PREFIX = "mcp-param-"

#: Which body field Mcp-Name mirrors, per method.  Only these three methods
#: require the header at all; note it doubles for params.name AND params.uri.
_NAME_SOURCE_FIELD = {
    "tools/call": "name",
    "resources/read": "uri",
    "prompts/get": "name",
}

#: Hosts always acceptable as Origin — DNS rebinding cannot forge these, and
#: this is a localhost teaching server (spec SHOULD: bind to loopback).
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

#: RFC 9110 §5.1 token characters — the only ones legal in a header NAME,
#: which is what an x-mcp-header annotation value becomes.
_TCHAR_RE = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")

#: Sentinel marking "dispatch finished" on the request-scoped notification
#: queue (distinguishable from any JSON-RPC message dict).
_DISPATCH_DONE = object()

#: Sentinel for "argument absent from the body" — distinct from an explicit
#: JSON null, though both mean the client MUST omit the mirrored header.
_ABSENT = object()


class Dispatcher(Protocol):
    """The dispatcher surface this transport consumes (modern/dispatcher.py).

    ``handle`` returns a complete JSON-RPC response dict, a ListenOutcome
    (for ``subscriptions/listen``), or None (notifications — which this HTTP
    layer answers with 202 itself, so None is defensive here).  Protocol
    errors are raised as :class:`~modern.errors.McpError`; this layer maps
    ``McpError.http_status`` onto the HTTP status line.  ``env`` is typed
    loosely because outcomes/environments are matched structurally — see
    :class:`RequestEnv`.
    """

    async def handle(self, message: dict[str, Any], env: Any) -> Any: ...


@dataclass
class RequestEnv:
    """Per-request environment handed to the dispatcher.

    Structurally identical to ``modern.dispatcher.RequestEnv`` (the design's
    dispatcher contract); defined here as well so the transport has no import
    dependency on the dispatcher module.  The dispatcher only reads the three
    attributes, so either class satisfies it at runtime.
    """

    transport: Literal["http", "stdio"]
    #: Authenticated principal (modern/auth/bearer.py) or None when auth is
    #: disabled/anonymous.
    principal: Any | None
    #: Request-scoped notification sink: complete JSON-RPC notification dicts
    #: (notifications/progress, notifications/message) emitted while THIS
    #: request runs.  They are only ever delivered on this request's own
    #: response stream — never on a listen stream (spec MUST).
    notify: Callable[[dict[str, Any]], Awaitable[None]]


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _as_dict(value: Any) -> dict[str, Any] | None:
    """Typed narrowing helper — wire values are Any until proven objects."""
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)
    return None


def _sse_frame(payload: dict[str, Any]) -> str:
    """One SSE event carrying a JSON-RPC message.

    Always ``event: message`` + a single ``data:`` line.  Deliberately no
    ``id:`` field, ever — SSE event ids existed to feed ``Last-Event-ID``
    resumability, which 2026-07-28 removed (SEP-2575).
    """
    return f"event: message\ndata: {json.dumps(payload)}\n\n"


def _json_error(payload: dict[str, Any], status: int) -> JSONResponse:
    return JSONResponse(payload, status_code=status)


def _status_for_response(response: dict[str, Any]) -> int:
    """HTTP status for a dispatcher-RETURNED response dict.

    Successful results are 200.  If the dispatcher chose to return (rather
    than raise) an error response, recover the status the spec assigns to
    the code: -32601 rides 404, -32603 rides 500, everything else the spec
    mentions (parse/invalid/params/-3202x) rides 400.
    """
    error = _as_dict(response.get("error"))
    if error is None:
        return 200
    code = error.get("code")
    if code == METHOD_NOT_FOUND:
        return 404
    if code == INTERNAL_ERROR:
        return 500
    return 400


def _raw_meta(message: dict[str, Any]) -> dict[str, Any]:
    """Best-effort peek at ``params._meta`` (validation is the dispatcher's job)."""
    params = _as_dict(message.get("params"))
    if params is not None:
        meta = _as_dict(params.get("_meta"))
        if meta is not None:
            return meta
    return {}


def _is_listen_outcome(outcome: Any) -> bool:
    """Structural check for a listen outcome.

    isinstance would be enough for outcomes built by modern/broker.py, but
    the dispatcher is free to wrap or redefine the dataclass — the contract
    is the three attributes, so match on those.
    """
    if isinstance(outcome, ListenOutcome):
        return True
    return all(hasattr(outcome, attr) for attr in ("ack", "queue", "close"))


def _origin_allowed(origin: str, allowed_origins: frozenset[str]) -> bool:
    """DNS-rebinding gate: is this Origin acceptable?

    Exact (case-insensitive) match against the configured allowlist, or a
    loopback hostname — a rebinding attack can point a hostile DOMAIN at
    127.0.0.1, but the browser still reports the hostile origin, which fails
    both checks.
    """
    if origin.lower() in allowed_origins:
        return True
    try:
        host = urlsplit(origin).hostname
    except ValueError:
        return False
    return host in _LOOPBACK_HOSTS if host else False


def _require_header_safe(value: str, header: str) -> None:
    """Reject header values containing invalid characters (spec: -32020).

    Real HTTP stacks refuse CR/LF/control bytes long before us, but the spec
    lists "a header value contains invalid characters" as a validation
    failure a body-processing server must catch, so belt and braces.
    """
    if any((ord(ch) < 0x20 and ch != "\t") or ord(ch) == 0x7F for ch in value):
        raise HeaderMismatchError(f"{header} header value contains invalid characters")


def _value_at(arguments: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Instance value at an exact property path, or _ABSENT."""
    node: Any = arguments
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return _ABSENT
        node = node[key]
    return node


def _header_annotations(schema: dict[str, Any]) -> dict[str, tuple[tuple[str, ...], str]]:
    """Collect x-mcp-header annotations: lowercased header name -> (path, type).

    SEP-2243 constrains which properties may be annotated: primitive types
    only (string/integer/boolean — ``number`` is banned because float
    round-tripping through a decimal header string is ambiguous), reachable
    from the schema root through ``properties`` keys ONLY (never ``items``,
    composition keywords, or ``$ref`` — those make the path statically
    unresolvable), and named with non-empty RFC 9110 tokens, unique
    case-insensitively.  Annotations violating the constraints invalidate
    the TOOL on the client side (it must be dropped from tools/list); the
    server side simply never recognizes them, which is what skipping here
    implements.
    """
    found: dict[str, tuple[tuple[str, ...], str]] = {}

    def walk(node: dict[str, Any], path: tuple[str, ...]) -> None:
        properties = _as_dict(node.get("properties"))
        if properties is None:
            return
        for key, subschema_value in properties.items():
            subschema = _as_dict(subschema_value)
            if subschema is None:
                continue
            header = subschema.get("x-mcp-header")
            ptype = subschema.get("type")
            if (
                isinstance(header, str)
                and _TCHAR_RE.fullmatch(header)
                and ptype in ("string", "integer", "boolean")
            ):
                # setdefault: on a (schema-invalid) case-insensitive
                # duplicate, first declaration wins and the rest are ignored.
                found.setdefault(header.lower(), ((*path, key), ptype))
            walk(subschema, (*path, key))

    walk(schema, ())
    return found


def _param_matches(decoded: str, body_value: Any, ptype: str) -> bool:
    """Compare a decoded header value with the body argument, per type.

    Booleans mirror as lowercase "true"/"false"; integers compare
    NUMERICALLY (spec SHOULD: "42.0" == 42, so a well-meaning intermediary
    that reserializes the number does not break validation); strings compare
    exactly.
    """
    if ptype == "boolean":
        return isinstance(body_value, bool) and decoded == ("true" if body_value else "false")
    if ptype == "integer":
        if isinstance(body_value, bool) or not isinstance(body_value, int | float):
            return False
        try:
            return float(decoded) == float(body_value)
        except ValueError:
            return False
    return isinstance(body_value, str) and decoded == body_value


def _validate_param_headers(
    headers: Any,
    arguments: Any,
    schema: dict[str, Any],
) -> None:
    """Enforce the SEP-2243 Mcp-Param-{Name} behavior table for one tools/call.

    For every recognized annotation: value present in the body → the header
    MUST be present and match (a client that omits it is non-conforming and
    the request is rejected); value absent or null → the header MUST be
    omitted.  ``Mcp-Param-*`` headers that match no annotation are forwarded
    /ignored per RFC 9110 — only RECOGNIZED headers are validated.
    """
    annotations = _header_annotations(schema)
    if not annotations:
        return
    args = _as_dict(arguments) or {}
    for lower_name, (path, ptype) in annotations.items():
        header_name = f"Mcp-Param-{lower_name}"
        raw = headers.get(HEADER_PARAM_PREFIX + lower_name)
        body_value = _value_at(args, path)
        if body_value is _ABSENT or body_value is None:
            if raw is not None:
                raise HeaderMismatchError(
                    f"{header_name} header is present but the corresponding "
                    f"argument {'.'.join(path)!r} is absent from the body"
                )
            continue
        if raw is None:
            raise HeaderMismatchError(
                f"Argument {'.'.join(path)!r} is present in the body but the "
                f"required {header_name} header is missing"
            )
        _require_header_safe(raw, header_name)
        decoded = decode_header_value(raw)
        if not _param_matches(decoded, body_value, ptype):
            raise HeaderMismatchError(
                f"{header_name} header value {decoded!r} does not match body value {body_value!r}"
            )


def _validate_headers(
    headers: Any,
    message: dict[str, Any],
    tool_schema_lookup: Callable[[str], dict[str, Any] | None] | None,
) -> None:
    """SEP-2243 server validation: the header mirror must tell the truth.

    Raises HeaderMismatchError (-32020, HTTP 400) for: a missing required
    standard header, a header value that does not match the body value
    (Base64 sentinel decoded first), or invalid characters.  When the BODY
    side of a comparison is missing/malformed we defer instead — that is a
    ``-32602`` Invalid params failure and the dispatcher's meta validation
    reports it with a more precise message.
    """
    params = _as_dict(message.get("params")) or {}
    meta = _raw_meta(message)

    # MCP-Protocol-Version: required on every modern POST.  We do not accept
    # header-less requests here — the dual-era front door already routed
    # pre-2025-06-18 (header-less) traffic to the legacy app, so a request
    # reaching this pipeline without the header is non-conforming.
    header_version = headers.get(HEADER_PROTOCOL_VERSION)
    if header_version is None:
        raise HeaderMismatchError(f"Required {HEADER_PROTOCOL_VERSION} header is missing")
    body_version = meta.get(META_PROTOCOL_VERSION)
    if isinstance(body_version, str) and header_version != body_version:
        raise HeaderMismatchError(
            f"{HEADER_PROTOCOL_VERSION} header {header_version!r} does not match "
            f"body _meta value {body_version!r}"
        )
    # NOTE: whether the (matching) version is one we SUPPORT is a different
    # question with a different error (-32022) — the dispatcher answers it.

    # Mcp-Method: required on all requests; values are case-SENSITIVE.
    method = message["method"]
    header_method = headers.get(HEADER_METHOD)
    if header_method is None:
        raise HeaderMismatchError(f"Required {HEADER_METHOD} header is missing")
    if header_method != method:
        raise HeaderMismatchError(
            f"{HEADER_METHOD} header {header_method!r} does not match body method {method!r}"
        )

    # Mcp-Name: required for the three name-addressed methods; mirrors
    # params.name OR params.uri and may arrive sentinel-encoded (resource
    # URIs and unicode tool names are not header-safe).
    name_field = _NAME_SOURCE_FIELD.get(method)
    if name_field is not None:
        header_name = headers.get(HEADER_NAME)
        if header_name is None:
            raise HeaderMismatchError(
                f"Required {HEADER_NAME} header is missing for {method} requests"
            )
        _require_header_safe(header_name, HEADER_NAME)
        decoded = decode_header_value(header_name)  # may raise -32020 itself
        body_name = params.get(name_field)
        if isinstance(body_name, str) and decoded != body_name:
            raise HeaderMismatchError(
                f"{HEADER_NAME} header value {decoded!r} does not match "
                f"body params.{name_field} value {body_name!r}"
            )

    # Mcp-Param-*: only meaningful for tools/call, and only when we can see
    # the tool's schema.  The lookup is injected so this transport does not
    # depend on the registry module.
    if method == "tools/call" and tool_schema_lookup is not None:
        tool_name = params.get("name")
        schema = tool_schema_lookup(tool_name) if isinstance(tool_name, str) else None
        if isinstance(schema, dict):
            _validate_param_headers(headers, params.get("arguments"), schema)


# ---------------------------------------------------------------------------
# Dispatch plumbing
# ---------------------------------------------------------------------------


async def _run_dispatch(
    dispatcher: Dispatcher,
    message: dict[str, Any],
    env: RequestEnv,
    request_id: str | int,
) -> tuple[str, Any, int]:
    """Run the dispatcher and normalize its outcome to (kind, payload, status).

    kinds: "response" (payload = complete JSON-RPC response dict), "listen"
    (payload = ListenOutcome), "none" (notification — defensive; HTTP answers
    those with 202 before dispatch).  McpErrors raised by the dispatcher
    become error responses carrying their spec-assigned HTTP status; anything
    else is a -32603 with the details kept server-side (500 bodies must not
    leak stack traces).
    """
    try:
        outcome = await dispatcher.handle(message, env)
    except McpError as exc:
        return ("response", exc.to_error_response(request_id), exc.http_status)
    except Exception:
        logger.exception("Unhandled error dispatching %s", message.get("method"))
        internal = InternalError("Internal server error")
        return ("response", internal.to_error_response(request_id), internal.http_status)
    if outcome is None:
        return ("none", None, 202)
    response = _as_dict(outcome)
    if response is not None:
        return ("response", response, _status_for_response(response))
    if _is_listen_outcome(outcome):
        return ("listen", outcome, 200)
    logger.error("Dispatcher returned unrecognized outcome type %s", type(outcome).__name__)
    internal = InternalError("Internal server error")
    return ("response", internal.to_error_response(request_id), internal.http_status)


async def _wait_disconnect(receive: Callable[[], Awaitable[Any]]) -> None:
    """Block until the client goes away.  Disconnect IS cancellation on HTTP."""
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return


async def _listen_frames(
    outcome: Any,
    keepalive_interval: float,
) -> AsyncGenerator[str, None]:
    """SSE frames for a subscriptions/listen stream.

    Ack first (spec MUST), then queue items as they arrive.  Quiet periods
    produce ``:keepalive`` comment lines — SSE parsers ignore comment lines
    by definition, so they cost nothing protocol-wise but keep NATs, LBs and
    idle-timeout proxies from killing the connection (this also replaces the
    removed ``ping`` RPC).  A queue item WITHOUT a ``method`` key is the
    graceful-close JSON-RPC response (see modern/broker.py): emit it, then
    end the stream per "the final response SHOULD terminate the stream".
    """
    yield _sse_frame(outcome.ack)
    while True:
        try:
            item = await asyncio.wait_for(outcome.queue.get(), timeout=keepalive_interval)
        except TimeoutError:
            yield ":keepalive\n\n"
            continue
        yield _sse_frame(item)
        if "method" not in item:
            return


async def _request_stream_frames(
    queue: asyncio.Queue[Any],
    dispatch_task: asyncio.Task[tuple[str, Any, int]],
    keepalive_interval: float,
) -> AsyncGenerator[str, None]:
    """SSE frames for a request that opted into progress/log streaming.

    Request-scoped notifications are relayed live as the handler emits them
    (this is the whole point of progressToken), then the final JSON-RPC
    response ends the stream.  Should the request turn out to be a
    subscriptions/listen, we chain straight into the listen framing on the
    same stream.
    """
    while True:
        item = await queue.get()
        if item is _DISPATCH_DONE:
            break
        yield _sse_frame(item)
    if dispatch_task.cancelled():
        return
    kind, payload, _status = dispatch_task.result()
    if kind == "listen":
        async for frame in _listen_frames(payload, keepalive_interval):
            yield frame
    elif kind == "response":
        # Errors surface here too: once streaming starts the HTTP status is
        # spent (200), so a failed dispatch rides the stream as a JSON-RPC
        # error response object — exactly why McpError.http_status only
        # matters on the buffered path.
        yield _sse_frame(payload)


class _SseResponse(Response):
    """A hand-rolled SSE response with cancellation-by-disconnect semantics.

    Starlette's StreamingResponse would pump the generator for us, but the
    2026-07-28 cancellation rules are exact enough to be worth owning: the
    frame pump races a disconnect watcher; if the client closes the stream
    first, the pump is cancelled and NOTHING further is sent (spec MUST NOT),
    then ``cleanup`` runs — cancelling the dispatch task and/or unregistering
    the listen subscription with the broker.
    """

    def __init__(
        self,
        frames: AsyncGenerator[str, None],
        cleanup: Callable[[], Awaitable[None]],
    ) -> None:
        super().__init__(
            content=None,
            status_code=200,
            media_type="text/event-stream",
            # no-store: an SSE stream is a live channel, never cache fodder;
            # X-Accel-Buffering disables reverse-proxy buffering (spec SHOULD
            # — a buffering nginx would hold events until the buffer fills).
            headers={"cache-control": "no-store", "x-accel-buffering": "no"},
        )
        # Response.init_headers computed content-length for the empty body;
        # a stream has no predetermined length, so strip it.
        self.raw_headers = [(k, v) for (k, v) in self.raw_headers if k != b"content-length"]
        self._frames = frames
        self._cleanup = cleanup

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:  # noqa: ARG002
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        pump = asyncio.create_task(self._pump(send))
        watch = asyncio.create_task(_wait_disconnect(receive))
        done, pending = await asyncio.wait({pump, watch}, return_when=asyncio.FIRST_COMPLETED)
        # If the watcher won the race, the client disconnected: that IS the
        # cancellation signal — stop the pump and send nothing further.
        disconnected = pump not in done
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await self._frames.aclose()
        await self._cleanup()
        if not disconnected:
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            if not pump.cancelled() and (exc := pump.exception()) is not None:
                raise exc

    async def _pump(self, send: Any) -> None:
        async for frame in self._frames:
            await send(
                {
                    "type": "http.response.body",
                    "body": frame.encode("utf-8"),
                    "more_body": True,
                }
            )


# ---------------------------------------------------------------------------
# The modern ASGI app
# ---------------------------------------------------------------------------


def create_modern_asgi(
    dispatcher: Dispatcher,
    *,
    allowed_origins: Sequence[str] = (),
    require_auth: bool = False,
    verifier: Any | None = None,
    challenge_401: Callable[[], str] | None = None,
    challenge_403: Callable[[], str] | None = None,
    tool_schema_lookup: Callable[[str], dict[str, Any] | None] | None = None,
    extra_routes: Sequence[BaseRoute] | None = None,
    mcp_path: str = "/mcp",
    keepalive_interval: float = 15.0,
) -> Starlette:
    """Build the modern-era (2026-07-28) Streamable HTTP application.

    Args:
        dispatcher: the method router (modern/dispatcher.py contract).
        allowed_origins: extra Origin values to accept verbatim; loopback
            hosts are always allowed.  Anything else → 403.
        require_auth: enforce Bearer authentication on the MCP endpoint.
        verifier: bearer-token verifier — either an object exposing
            ``verify(token) -> principal`` (modern/auth/bearer.TokenVerifier)
            or a plain callable ``token -> principal``.  Any exception it
            raises means "invalid token" (401); an exception whose
            ``http_status`` attribute equals 403 means "authenticated but
            insufficient" and produces a 403 challenge instead.
        challenge_401 / challenge_403: zero-argument builders returning the
            ``WWW-Authenticate`` header value for the respective status
            (modern/auth/metadata.py provides them; the integrator binds
            prm_url/scopes via functools.partial).  Fallback is a bare
            ``Bearer`` challenge.
        tool_schema_lookup: ``tool name -> inputSchema dict | None``, used to
            recognize x-mcp-header annotations for Mcp-Param-* validation
            without importing the registry.
        extra_routes: additional public routes (RFC 9728 protected-resource
            metadata, the demo authorization server) mounted OUTSIDE the auth
            gate — a client must be able to READ the auth metadata before it
            can authenticate.
        mcp_path: the single MCP endpoint path (spec: servers MUST provide
            one endpoint supporting POST only — other verbs 405 here, which
            Starlette's router answers for us on a modern-only deployment).
        keepalive_interval: seconds of listen-stream silence between
            ``:keepalive`` comments (injectable for tests).
    """
    if require_auth and verifier is None:
        raise ValueError("require_auth=True requires a verifier")

    origin_allowlist = frozenset(origin.lower() for origin in allowed_origins)

    def _challenge_response(status: int, builder: Callable[[], str] | None) -> Response:
        value = builder() if builder is not None else "Bearer"
        return Response(status_code=status, headers={"WWW-Authenticate": value})

    def _authenticate(request: Request) -> Any | Response:
        """Bearer auth per the draft resource-server model (401/403 challenges)."""
        header = request.headers.get("authorization") or ""
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            # No usable credentials: 401 with a challenge pointing the client
            # at the protected-resource metadata so it can discover the AS.
            return _challenge_response(401, challenge_401)
        try:
            verify = getattr(verifier, "verify", None)
            if callable(verify):
                return verify(token.strip())
            return verifier(token.strip())  # type: ignore[misc]
        except Exception as exc:
            if getattr(exc, "http_status", 401) == 403:
                # Token is valid but lacks scope: 403 challenge (step-up).
                return _challenge_response(403, challenge_403)
            return _challenge_response(401, challenge_401)

    # A protocol endpoint is a gauntlet of early rejections (origin, auth,
    # parse, shape, headers) before dispatch — the return count reflects the
    # spec's validation pipeline, not incidental complexity.
    async def mcp_endpoint(request: Request) -> Response:  # noqa: PLR0911
        # --- 1. Origin validation (DNS rebinding, spec MUST) ---------------
        origin = request.headers.get("origin")
        if origin is not None and not _origin_allowed(origin, origin_allowlist):
            # 403; the body MAY be a JSON-RPC error with no id (spec).
            return _json_error(
                error_response(None, INVALID_REQUEST, f"Origin {origin!r} is not allowed"),
                403,
            )

        # --- 2. Authorization ----------------------------------------------
        principal: Any | None = None
        if require_auth:
            outcome = _authenticate(request)
            if isinstance(outcome, Response):
                return outcome
            principal = outcome

        # --- 3. Body: one JSON-RPC request or notification, never a batch --
        raw_body = await request.body()
        try:
            parsed: Any = json.loads(raw_body)
        except (ValueError, UnicodeDecodeError):
            exc = ParseError("Request body is not valid JSON")
            return _json_error(exc.to_error_response(None), exc.http_status)
        if isinstance(parsed, list):
            exc = InvalidRequestError(
                "JSON-RPC batch requests were removed from MCP; send one message per POST"
            )
            return _json_error(exc.to_error_response(None), exc.http_status)
        message = _as_dict(parsed)
        if (
            message is None
            or message.get("jsonrpc") != JSONRPC_VERSION
            or not isinstance(message.get("method"), str)
        ):
            exc = InvalidRequestError("Body must be a single JSON-RPC 2.0 request object")
            return _json_error(exc.to_error_response(None), exc.http_status)

        # Notification POST (no id): 202 Accepted, no body.  This revision
        # defines no client→server notifications over HTTP (cancellation is
        # closing the stream) and no header requirements for notification
        # POSTs, so we accept without Mcp-Method and do not dispatch.
        if "id" not in message:
            return Response(status_code=202)

        request_id = message["id"]
        if isinstance(request_id, bool) or not isinstance(request_id, str | int):
            # MCP is stricter than JSON-RPC: ids are string or integer, never
            # null/bool/float.
            exc = InvalidRequestError("Request id must be a string or integer")
            return _json_error(exc.to_error_response(None), exc.http_status)

        # --- 4. Header mirror validation (SEP-2243) -------------------------
        try:
            _validate_headers(request.headers, message, tool_schema_lookup)
        except HeaderMismatchError as exc:
            return _json_error(exc.to_error_response(request_id), exc.http_status)

        # --- 5. Dispatch -----------------------------------------------------
        notification_queue: asyncio.Queue[Any] = asyncio.Queue()
        # Set as soon as the handler emits its first request-scoped
        # notification — the signal that it is genuinely executing (and so
        # an HTTP 200 SSE stream is the right response).
        first_notification = asyncio.Event()

        async def notify(notification: dict[str, Any]) -> None:
            notification_queue.put_nowait(notification)
            first_notification.set()

        env = RequestEnv(transport="http", principal=principal, notify=notify)
        dispatch_task = asyncio.create_task(_run_dispatch(dispatcher, message, env, request_id))

        async def cleanup() -> None:
            """Runs when a stream ends, disconnects, or errors out."""
            if not dispatch_task.done():
                dispatch_task.cancel()
                await asyncio.gather(dispatch_task, return_exceptions=True)
                return
            if dispatch_task.cancelled():
                return
            kind, payload, _status = dispatch_task.result()
            if kind == "listen":
                # Idempotent broker unregistration; result deliberately
                # discarded — after a disconnect nothing may be sent, and
                # after a graceful close it was already streamed.
                await payload.close()

        # Response-mode choice.  A request that opted into progress or
        # per-request logging MAY get its notifications streamed live over
        # SSE; anything else gets a single buffered JSON object.  (The spec
        # allows either at the server's discretion.)
        #
        # But we must not commit an HTTP 200 SSE stream to a request that is
        # about to FAIL: -32601 rides 404, and bad _meta/version (-32602/
        # -32022) ride 400 — statuses the transport spec makes MUSTs, and
        # which an already-sent "200 text/event-stream" would bury.  Those
        # errors are raised before any handler runs, so they finish dispatch
        # with ZERO notifications.  So we race the dispatch against the first
        # notification: if the handler emits one, it is genuinely executing
        # (stream it, 200 is correct); if dispatch instead finishes first
        # with nothing queued, buffer the result/error with its real status.
        meta = _raw_meta(message)
        if META_PROGRESS_TOKEN in meta or META_LOG_LEVEL in meta:
            first_evt = asyncio.create_task(first_notification.wait())
            try:
                await asyncio.wait({dispatch_task, first_evt}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                first_evt.cancel()
                await asyncio.gather(first_evt, return_exceptions=True)

            stream_it = first_notification.is_set()
            if not stream_it:
                # No notification emitted, so dispatch is the task that
                # finished the race.  Stream a SUCCESS (honoring the client's
                # opt-in) but buffer an ERROR so its spec-mandated HTTP status
                # (404 for -32601, 400 for -32602/-32022) is not buried under
                # an already-committed "200 text/event-stream".
                kind, _payload, status = dispatch_task.result()
                stream_it = kind != "response" or status == 200
            if stream_it:
                dispatch_task.add_done_callback(
                    lambda _task: notification_queue.put_nowait(_DISPATCH_DONE)
                )
                frames = _request_stream_frames(
                    notification_queue, dispatch_task, keepalive_interval
                )
                return _SseResponse(frames, cleanup)
            # Error with no notifications: fall through to the buffered path,
            # which reports the correct status.

        # Buffered path: race the handler against a client disconnect —
        # closing the response stream is the ONLY cancellation signal on
        # Streamable HTTP (notifications/cancelled is stdio-only).
        watch = asyncio.create_task(_wait_disconnect(request.receive))
        try:
            done, _pending = await asyncio.wait(
                {dispatch_task, watch}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            watch.cancel()
            await asyncio.gather(watch, return_exceptions=True)

        if dispatch_task not in done:
            # Client vanished mid-dispatch: stop work, send nothing further.
            await cleanup()
            return Response(status_code=204)

        kind, payload, status = dispatch_task.result()
        if kind == "listen":
            # subscriptions/listen is ALWAYS SSE: the response to the listen
            # request is the stream itself.
            return _SseResponse(_listen_frames(payload, keepalive_interval), cleanup)
        if kind == "none":
            return Response(status_code=202)
        return _json_error(payload, status) if status != 200 else JSONResponse(payload)

    routes: list[BaseRoute] = [Route(mcp_path, mcp_endpoint, methods=["POST"], name="mcp")]
    if extra_routes:
        routes.extend(extra_routes)
    return Starlette(routes=routes)


# ---------------------------------------------------------------------------
# Dual-era front door
# ---------------------------------------------------------------------------


def _scope_header(scope: dict[str, Any], name: str) -> str | None:
    """Read one header from a raw ASGI scope (names case-insensitive)."""
    target = name.lower().encode("latin-1")
    for key, value in scope.get("headers") or ():
        if key.lower() == target:
            decoded = value.decode("latin-1").strip()
            return decoded or None
    return None


async def _buffer_body(
    receive: Callable[[], Awaitable[dict[str, Any]]],
) -> tuple[bytes, Callable[[], Awaitable[dict[str, Any]]]]:
    """Drain the request body, returning it plus a replaying ``receive``.

    Era classification must inspect the body, but the chosen sub-app needs to
    read that same body itself — so we hand it a receive callable that first
    replays the buffered bytes as a single ``http.request`` message and then
    delegates (so later ``http.disconnect`` events still flow through).
    """
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] == "http.request":
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        elif message["type"] == "http.disconnect":
            break
    body = b"".join(chunks)

    replayed = False

    async def replay_receive() -> dict[str, Any]:
        nonlocal replayed
        if not replayed:
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return body, replay_receive


def _classify_era(
    header_version: str | None,
    message: dict[str, Any] | None,
) -> Literal["modern", "legacy"]:
    """Decide which era a POST to the MCP endpoint belongs to.

    Order matters (Versioning: Backward Compatibility):

    1. A legacy version in ``MCP-Protocol-Version`` is decisive — those
       clients negotiated the value during ``initialize`` and echo it back.
    2. ``initialize`` itself is inherently legacy (the modern era deleted it;
       a modern-only server SHOULD name its supported versions when
       rejecting one — our legacy side simply serves it instead).
    3. Any OTHER header value, or modern ``_meta`` in the body, marks a
       modern client — even if the version turns out to be unsupported, the
       modern pipeline owns producing the -32022 with the supported list.
    4. Everything else defaults to LEGACY: pre-2025-06-18 clients sent no
       header at all, and misclassifying them as modern would reject them
       with errors they cannot interpret.
    """
    if header_version in LEGACY_VERSIONS:
        return "legacy"
    if message is not None and message.get("method") == "initialize":
        return "legacy"
    if header_version:
        return "modern"
    if message is not None:
        params = _as_dict(message.get("params"))
        meta = _as_dict(params.get("_meta")) if params is not None else None
        if meta is not None and META_PROTOCOL_VERSION in meta:
            return "modern"
    return "legacy"


async def _send_json(send: Callable[..., Awaitable[None]], status: int, payload: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload, "more_body": False})


def _modern_route_paths(modern: Any, mcp_path: str) -> tuple[set[str], list[str]]:
    """Paths (beyond mcp_path) the modern app serves, for non-MCP routing.

    Introspects a Starlette app's route table: plain routes match exactly,
    mounts match by prefix.  A bare ASGI callable without ``routes`` yields
    nothing, and all non-MCP traffic falls through to the legacy app.
    """
    exact: set[str] = set()
    prefixes: list[str] = []
    routes_value: Any = getattr(modern, "routes", None)
    routes: list[Any] = routes_value if isinstance(routes_value, list) else []
    for route in routes:
        path = getattr(route, "path", None)
        if not isinstance(path, str) or path == mcp_path:
            continue
        if isinstance(route, Mount):
            prefixes.append(path)
        else:
            exact.add(path)
    return exact, prefixes


def create_dual_era_app(
    modern: Any,
    legacy_asgi: Any,
    mcp_path: str = "/mcp",
) -> Callable[[dict[str, Any], Any, Any], Awaitable[None]]:
    """One endpoint, two protocol eras (spec: a dual-era server MAY serve
    both eras concurrently on the same endpoint/process).

    POSTs to ``mcp_path`` are classified per :func:`_classify_era` and
    forwarded — body replayed — to the modern pipeline or the legacy
    (FastMCP) app.  GET/DELETE on ``mcp_path`` always go legacy: those verbs
    only exist in the legacy binding (GET SSE stream, DELETE session
    teardown); a modern-only deployment would answer 405 Method Not Allowed.
    Batch (array) bodies are rejected outright with -32600 — neither era
    accepts them anymore (batching was removed in 2025-06-18).

    On the modern path, ``Mcp-Session-Id`` and ``Last-Event-ID`` headers are
    IGNORED (SEP-2567/SEP-2575): we never read, mint, nor echo them — the
    modern pipeline simply has no code that looks at either header, which is
    the spec's "ignore it" made literal.

    Other paths route to the modern app when they match one of its
    registered routes (PRM well-known, demo AS) and to the legacy app
    otherwise (its own OAuth routes, docs, etc.).  Non-HTTP scopes (lifespan,
    websocket) go to the legacy app, whose FastMCP session manager needs the
    lifespan events; the modern app is stateless and needs none.
    """
    modern_exact, modern_prefixes = _modern_route_paths(modern, mcp_path)

    async def dual_era_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await legacy_asgi(scope, receive, send)
            return

        path = scope.get("path", "")
        if path != mcp_path:
            is_modern_path = path in modern_exact or any(
                path.startswith(prefix) for prefix in modern_prefixes
            )
            target = modern if is_modern_path else legacy_asgi
            await target(scope, receive, send)
            return

        if scope.get("method") != "POST":
            # Legacy sessions still GET (SSE stream) and DELETE (teardown).
            await legacy_asgi(scope, receive, send)
            return

        body, replay_receive = await _buffer_body(receive)
        try:
            parsed = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            # Unparseable bodies cannot be classified by content; the header
            # rules below still apply and ambiguity falls to legacy, whose
            # own parser reports the error in its era's dialect.
            parsed = None
        if isinstance(parsed, list):
            payload = json.dumps(
                error_response(
                    None,
                    INVALID_REQUEST,
                    "JSON-RPC batch requests are not supported by any served protocol version",
                )
            ).encode("utf-8")
            await _send_json(send, 400, payload)
            return

        message = _as_dict(parsed)
        era = _classify_era(_scope_header(scope, HEADER_PROTOCOL_VERSION), message)
        target = modern if era == "modern" else legacy_asgi
        await target(scope, replay_receive, send)

    return dual_era_app
