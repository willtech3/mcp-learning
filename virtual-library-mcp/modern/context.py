"""
ModernContext — the per-request context injected into handlers under
MCP 2026-07-28.

The whole point of this module is that the SAME handler functions serve
both protocol eras. tools/circulation.py awaits ``ctx.elicit(...)``,
tools/book_insights.py awaits ``ctx.sample(...)``, and
tools/catalog_maintenance.py calls ``ctx.report_progress`` / ``ctx.info`` /
``ctx.disable_components`` — all written against FastMCP's legacy Context.
ModernContext duck-types exactly that surface (same signatures, same return
shapes — it even reuses FastMCP's own elicitation schema/response helpers)
while implementing 2026-07-28 semantics underneath:

**Elicitation, sampling, roots become MRTR (SEP-2322).**  In the legacy era
``ctx.elicit`` sent a server-initiated ``elicitation/create`` JSON-RPC
request and blocked mid-execution for the reply.  The 2026-07-28 revision
DELETED server-initiated requests: a server that needs client input must
instead END the current request with ``resultType: "input_required"``,
embedding a plain ``{method, params}`` request object, and the client
RETRIES the original request carrying the answer.  ModernContext bridges
the two worlds with an interrupt-and-replay model:

- Each ``elicit``/``sample`` call gets a DETERMINISTIC key from a
  per-request counter: ``elicit:0``, ``sample:0``, ``sample:1``, ...
- If the memo (responses accumulated across retries; see modern/mrtr.py)
  already holds an answer under that key, the call returns immediately with
  a FastMCP-shaped result object — the handler cannot tell it was replayed.
- Otherwise the call raises :class:`InputRequiredInterrupt`, unwinding the
  handler; the MRTR engine converts that into the ``InputRequiredResult``.

The contract that makes this sound: **handlers are re-executed from scratch
on every retry and must reach their input calls in the same order with the
same shapes.**  That holds for deterministic handlers (same arguments ->
same call sequence), which is exactly the discipline the stateless protocol
demands.  Handler side effects BEFORE the first elicit/sample run again on
each retry — same as any at-least-once execution model; put side effects
after input gathering or make them idempotent.

Note on the interrupt's base class: it derives from ``BaseException``, not
``Exception``.  Handlers legitimately wrap ``ctx.elicit`` in ``except
Exception`` to degrade gracefully when a client lacks the capability
(checkout_book does).  A control-flow unwind that could be swallowed by
business error handling would silently break MRTR — the same reasoning that
moved ``asyncio.CancelledError`` to ``BaseException``.

**Logging is per-request (SEP-2575/2577).**  ``logging/setLevel`` is gone;
each request may carry ``_meta["io.modelcontextprotocol/logLevel"]``.  If
it is absent the server MUST NOT emit ``notifications/message`` for that
request, so ``ctx.info(...)`` silently drops.  Progress is unchanged in
shape but strictly gated on the request's ``progressToken``.

Spec: MCP 2026-07-28, basic/patterns/mrtr (SEP-2322), client/elicitation,
client/sampling + client/roots (deprecated, SEP-2577), server/utilities/
logging (deprecated), basic/patterns/progress.
"""

import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from fastmcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
    handle_elicit_accept,
    parse_elicit_response_type,
)
from fastmcp.server.sampling import SamplingTool
from pydantic import ValidationError

from modern.errors import (
    InvalidParamsError,
    MissingClientCapabilityError,
)
from modern.meta import RequestMeta
from modern.types import (
    JSONRPC_VERSION,
    LOGGING_LEVELS,
    CreateMessageResult,
    ElicitResult,
    TextContent,
    ToolResultContent,
    ToolUseContent,
)

logger = logging.getLogger(__name__)

#: FastMCP's default when a handler omits max_tokens; ``maxTokens`` is
#: REQUIRED on the wire (CreateMessageRequestParams), so we must fill it.
_DEFAULT_MAX_TOKENS = 512

#: Safety valve for the sampling tool loop: each LLM turn costs one full
#: MRTR round trip, so a runaway loop would ping-pong forever.  Both parties
#: SHOULD implement iteration limits (spec, client/sampling).
_MAX_SAMPLING_TURNS = 16


class InputRequiredInterrupt(BaseException):
    """Control-flow unwind: "this request needs client input to continue".

    Raised by ModernContext when a handler asks for input that is not yet
    memoized; caught ONLY by the MRTR engine (modern/mrtr.py), which turns
    it into the ``InputRequiredResult`` wire shape.

    ``BaseException`` on purpose — see the module docstring.  DESIGN.md
    sketched this as an ``Exception`` subclass, but the shared handlers
    wrap ``ctx.elicit`` in ``except Exception`` for capability fallback,
    which would swallow the unwind and break the round trip.
    """

    def __init__(self, key: str, input_request: dict[str, Any]) -> None:
        super().__init__(f"input required: {key}")
        #: The server-assigned identifier — the key under which this request
        #: appears in ``inputRequests`` and under which the client's answer
        #: must come back in ``inputResponses``.
        self.key = key
        #: Plain ``{"method": ..., "params": ...}`` object (NOT a JSON-RPC
        #: request: no id, no jsonrpc — the map key is the correlation id).
        self.input_request = input_request


@dataclass
class SamplingCallResult:
    """Duck-types fastmcp.server.sampling.SamplingResult.

    Handlers only touch ``.text`` today, but we mirror the full attribute
    set (text/result/history) so future handlers written against FastMCP
    keep working unmodified under the modern era.
    """

    text: str | None
    result: Any
    history: list[dict[str, Any]] = field(default_factory=list)


class ModernContext:
    """The 2026-07-28 stand-in for ``fastmcp.Context``.

    One instance exists per request EXECUTION (a retry gets a fresh one with
    a fuller memo).  Everything the legacy Context learned from the session
    now comes from the request itself:

    - ``meta``: the validated per-request ``_meta`` (version, client info,
      capabilities, log level, progress token) — see modern/meta.py.
    - ``memo``: input responses accumulated across MRTR retries, keyed by
      the deterministic call keys.  The MRTR engine owns this dict; the
      context only reads it (and deletes entries it must re-request).
    - ``notify``: request-scoped notification sink (progress/log messages
      ride the SAME response stream as the final result — never a
      subscriptions/listen stream).
    - ``registry``: visibility control (disable_components/reset_visibility).
    """

    def __init__(
        self,
        *,
        meta: RequestMeta,
        request_id: str | int | None = None,
        principal: Any | None = None,
        memo: dict[str, Any] | None = None,
        notify: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        registry: Any | None = None,
    ) -> None:
        self.meta = meta
        self.request_id = request_id
        self.principal = principal
        #: MRTR response memo — shared with (and mutated by) the engine.
        self._memo = memo if memo is not None else {}
        self._notify = notify
        self._registry = registry
        # Per-request call counters -> deterministic MRTR keys.  Re-executing
        # the handler from scratch re-runs the same calls in the same order,
        # so "elicit:0" always names the same conceptual question.
        self._elicit_calls = 0
        self._sample_calls = 0
        self._roots_calls = 0

    # ------------------------------------------------------------------
    # Elicitation (MRTR, SEP-2322; modes per client/elicitation)
    # ------------------------------------------------------------------

    async def elicit(
        self,
        message: str,
        response_type: Any = None,
        *,
        response_title: str | None = None,
        response_description: str | None = None,
    ) -> Any:
        """Ask the user a question — via an MRTR round trip.

        Signature and return shapes mirror ``fastmcp.Context.elicit``
        exactly: ``AcceptedElicitation`` (with ``.data``), or
        ``DeclinedElicitation`` / ``CancelledElicitation``.  We reuse
        FastMCP's own helpers to build the requestedSchema and to adapt the
        accepted content, so e.g. ``response_type=None`` produces the same
        approval-only ``{"type": "object", "properties": {}}`` schema and
        ``response_type=Literal[...]`` the same wrapped enum schema the
        legacy era sends — the handler sees identical results either way.
        """
        # Capability gate FIRST (spec MUST): a server MUST NOT embed an
        # elicitation InputRequest the client did not declare support for.
        # We only ever send form mode; an empty {"elicitation": {}} equals
        # {"form": {}} per the spec's backwards-compat rule.
        caps = self.meta.client_capabilities
        elicitation = caps.elicitation
        form_ok = elicitation is not None and (
            elicitation.form is not None or (elicitation.form is None and elicitation.url is None)
        )
        if not form_ok:
            raise MissingClientCapabilityError(
                {"elicitation": {}},
                message="This request requires the client elicitation capability (form mode)",
            )

        config = parse_elicit_response_type(response_type, response_title, response_description)

        key = f"elicit:{self._elicit_calls}"
        self._elicit_calls += 1

        if key not in self._memo:
            raise InputRequiredInterrupt(
                key,
                {
                    "method": "elicitation/create",
                    "params": {
                        # "mode" MAY be omitted for form (it is the default);
                        # we send it explicitly — teaching servers show their work.
                        "mode": "form",
                        "message": message,
                        "requestedSchema": config.schema,
                    },
                },
            )

        # Replay path: the client answered on a retry.  Validate the wire
        # shape strictly (a malformed InputResponse is a protocol error,
        # -32602), then adapt to the FastMCP result objects.
        try:
            answer = ElicitResult.model_validate(self._memo[key])
        except ValidationError as exc:
            raise InvalidParamsError(
                f"inputResponses[{key!r}] is not a valid ElicitResult: {exc.error_count()} "
                "validation error(s)"
            ) from exc

        if answer.action == "decline":
            return DeclinedElicitation()
        if answer.action == "cancel":
            return CancelledElicitation()

        try:
            return handle_elicit_accept(config, answer.content or {})
        except (ValidationError, ValueError):
            # Accepted but the content does not satisfy the requested
            # schema.  The spec SAYS: if the client omits requested info the
            # server SHOULD re-request rather than error — so we drop the
            # bad answer from the memo and re-raise the interrupt, producing
            # a fresh InputRequiredResult for the same key.
            del self._memo[key]
            self._elicit_calls -= 1
            return await self.elicit(
                message,
                response_type,
                response_title=response_title,
                response_description=response_description,
            )

    # ------------------------------------------------------------------
    # Sampling (MRTR; deprecated feature per SEP-2577 but still delivered)
    # ------------------------------------------------------------------

    async def sample(
        self,
        messages: Any,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model_preferences: Any = None,
        tools: Sequence[Any] | None = None,
        **_unsupported: Any,
    ) -> SamplingCallResult:
        """Ask the client's LLM for a completion — via MRTR round trips.

        Mirrors ``fastmcp.Context.sample`` for the argument subset our
        handlers use (messages, system_prompt, temperature, max_tokens,
        model_preferences, tools).  Tool-enabled sampling (SEP-1577) runs
        the same agentic loop FastMCP runs — LLM asks for a tool, WE execute
        it server-side, extended transcript goes back out — except that
        under MRTR each LLM turn costs one full retry of the original
        request: ``sample:0``, ``sample:1``, ... one key per turn.

        Sampling is deprecated as of 2026-07-28 (SEP-2577; migrate to direct
        LLM provider APIs) but remains functional for >= 12 months — serving
        it correctly IS the migration-window story.
        """
        caps = self.meta.client_capabilities
        if caps.sampling is None:
            raise MissingClientCapabilityError(
                {"sampling": {}},
                message="This request requires the client sampling capability",
            )

        sampling_tools = [self._as_sampling_tool(t) for t in tools] if tools else []
        if sampling_tools and caps.sampling.tools is None:
            # Tool-enabled sampling needs its own sub-capability: the client
            # must know how to run the tool loop protocol (SEP-1577).
            raise MissingClientCapabilityError(
                {"sampling": {"tools": {}}},
                message="This request requires the client sampling.tools capability",
            )
        tool_map = {t.name: t for t in sampling_tools}

        history = _normalize_sampling_messages(messages)

        for _turn in range(_MAX_SAMPLING_TURNS):
            key = f"sample:{self._sample_calls}"
            self._sample_calls += 1

            if key not in self._memo:
                params: dict[str, Any] = {
                    "messages": list(history),
                    # maxTokens is wire-REQUIRED; FastMCP's default is 512.
                    "maxTokens": max_tokens if max_tokens is not None else _DEFAULT_MAX_TOKENS,
                }
                if system_prompt is not None:
                    params["systemPrompt"] = system_prompt
                if temperature is not None:
                    params["temperature"] = temperature
                prefs = _normalize_model_preferences(model_preferences)
                if prefs is not None:
                    params["modelPreferences"] = prefs
                if sampling_tools:
                    params["tools"] = [
                        {
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": t.parameters,
                        }
                        for t in sampling_tools
                    ]
                raise InputRequiredInterrupt(
                    key, {"method": "sampling/createMessage", "params": params}
                )

            try:
                result = CreateMessageResult.model_validate(self._memo[key])
            except ValidationError as exc:
                raise InvalidParamsError(
                    f"inputResponses[{key!r}] is not a valid CreateMessageResult: "
                    f"{exc.error_count()} validation error(s)"
                ) from exc

            blocks = result.content if isinstance(result.content, list) else [result.content]
            history.append(
                {
                    "role": result.role,
                    "content": [b.to_wire() for b in blocks],
                }
            )

            tool_calls = [b for b in blocks if isinstance(b, ToolUseContent)]
            if result.stop_reason == "toolUse" and tool_calls and tool_map:
                # Execute the requested tools HERE (they are server-side
                # functions) and reply with a user message of ONLY tool
                # results — the spec forbids mixing tool results with other
                # content in one message.
                tool_results = [await _run_sampling_tool(tool_map, call) for call in tool_calls]
                history.append({"role": "user", "content": tool_results})
                continue

            text = next((b.text for b in blocks if isinstance(b, TextContent)), None)
            return SamplingCallResult(text=text, result=text, history=history)

        raise InvalidParamsError(
            f"Sampling tool loop exceeded {_MAX_SAMPLING_TURNS} turns without a final response"
        )

    @staticmethod
    def _as_sampling_tool(tool: Any) -> SamplingTool:
        """Accept plain callables (the handler-facing sugar) or SamplingTools."""
        if isinstance(tool, SamplingTool):
            return tool
        return SamplingTool.from_function(tool)

    # ------------------------------------------------------------------
    # Roots (MRTR; deprecated feature per SEP-2577)
    # ------------------------------------------------------------------

    async def list_roots(self) -> list[dict[str, Any]]:
        """Request the client's roots list via MRTR (``roots/list``).

        No current handler uses roots (they are deprecated: migrate to tool
        parameters / resource URIs / server configuration), but the third
        InputRequest type is implemented for completeness of the lesson.
        """
        caps = self.meta.client_capabilities
        if caps.roots is None:
            raise MissingClientCapabilityError(
                {"roots": {}},
                message="This request requires the client roots capability",
            )
        key = f"roots:{self._roots_calls}"
        self._roots_calls += 1
        if key not in self._memo:
            raise InputRequiredInterrupt(key, {"method": "roots/list"})
        response = self._memo[key]
        roots = response.get("roots") if isinstance(response, dict) else None
        if not isinstance(roots, list):
            raise InvalidParamsError(f"inputResponses[{key!r}] is not a valid ListRootsResult")
        return roots

    # ------------------------------------------------------------------
    # Progress (basic/patterns/progress — server -> client only now)
    # ------------------------------------------------------------------

    async def report_progress(
        self,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        """Emit ``notifications/progress`` on this request's response stream.

        Strictly opt-in: no ``progressToken`` in the request's ``_meta`` ->
        no-op (the receiver is never obligated to send progress, and MUST
        NOT reference tokens the client did not provide).
        """
        if self.meta.progress_token is None or self._notify is None:
            return
        params: dict[str, Any] = {
            "progressToken": self.meta.progress_token,
            "progress": progress,
        }
        if total is not None:
            params["total"] = total
        if message is not None:
            params["message"] = message
        await self._notify(
            {"jsonrpc": JSONRPC_VERSION, "method": "notifications/progress", "params": params}
        )

    # ------------------------------------------------------------------
    # Logging (deprecated SEP-2577; per-request logLevel replaces setLevel)
    # ------------------------------------------------------------------

    async def _log(
        self,
        level: str,
        message: str,
        logger_name: str | None,
        extra: Mapping[str, Any] | None,
    ) -> None:
        """Send ``notifications/message`` iff this REQUEST opted in.

        The 2026-07-28 rule is absolute: a request without the
        ``io.modelcontextprotocol/logLevel`` ``_meta`` key MUST NOT receive
        message notifications.  When present, it is the minimum severity —
        compare positions in the RFC 5424 ordering, not strings.
        """
        if self.meta.log_level is None or self._notify is None:
            return
        if LOGGING_LEVELS.index(level) < LOGGING_LEVELS.index(self.meta.log_level):
            return
        data: Any = message if not extra else {"message": message, **dict(extra)}
        params: dict[str, Any] = {"level": level, "data": data}
        if logger_name is not None:
            params["logger"] = logger_name
        await self._notify(
            {"jsonrpc": JSONRPC_VERSION, "method": "notifications/message", "params": params}
        )

    async def debug(
        self, message: str, logger_name: str | None = None, extra: Mapping[str, Any] | None = None
    ) -> None:
        await self._log("debug", message, logger_name, extra)

    async def info(
        self, message: str, logger_name: str | None = None, extra: Mapping[str, Any] | None = None
    ) -> None:
        await self._log("info", message, logger_name, extra)

    async def warning(
        self, message: str, logger_name: str | None = None, extra: Mapping[str, Any] | None = None
    ) -> None:
        await self._log("warning", message, logger_name, extra)

    async def error(
        self, message: str, logger_name: str | None = None, extra: Mapping[str, Any] | None = None
    ) -> None:
        await self._log("error", message, logger_name, extra)

    # ------------------------------------------------------------------
    # Component visibility (maintenance mode; drives list_changed events)
    # ------------------------------------------------------------------

    async def disable_components(
        self,
        *,
        names: set[str] | None = None,
        keys: set[str] | None = None,
        version: Any | None = None,
        tags: set[str] | None = None,
        components: set[Literal["tool", "resource", "template", "prompt"]] | None = None,
        match_all: bool = False,
    ) -> None:
        """Hide components from list results (mirrors FastMCP's signature).

        Our handlers only use the ``names`` + ``components`` axes (see
        tools/catalog_maintenance.py); the other selectors exist for
        signature compatibility and are ignored with a debug note.  The
        registry filters its lists and fires ``on_list_changed`` so the
        broker can push ``notifications/*/list_changed`` to opted-in
        ``subscriptions/listen`` streams.
        """
        if keys or version or tags or match_all:
            logger.debug("ModernContext.disable_components ignores keys/version/tags/match_all")
        if self._registry is None or not names:
            return
        self._registry.disable(names, kinds=components)

    async def reset_visibility(self) -> None:
        """Undo every disable_components call (end of maintenance mode)."""
        if self._registry is None:
            return
        self._registry.reset_visibility()


# ---------------------------------------------------------------------------
# Sampling helpers
# ---------------------------------------------------------------------------


def _normalize_sampling_messages(messages: Any) -> list[dict[str, Any]]:
    """Coerce the handler-facing ``messages`` sugar into wire SamplingMessages.

    Accepts a plain string, a sequence of strings, or already-shaped message
    dicts / models — the same conveniences FastMCP offers.
    """

    def one(m: Any) -> dict[str, Any]:
        if isinstance(m, str):
            return {"role": "user", "content": {"type": "text", "text": m}}
        if isinstance(m, dict):
            return m
        if hasattr(m, "to_wire"):
            return m.to_wire()
        if hasattr(m, "model_dump"):
            return m.model_dump(by_alias=True, exclude_none=True, mode="json")
        raise TypeError(f"Unsupported sampling message type: {type(m).__name__}")

    if isinstance(messages, str):
        return [one(messages)]
    return [one(m) for m in messages]


def _normalize_model_preferences(prefs: Any) -> dict[str, Any] | None:
    """Convert the str / list[str] / model sugar into wire ModelPreferences."""
    if prefs is None:
        return None
    if isinstance(prefs, str):
        return {"hints": [{"name": prefs}]}
    if isinstance(prefs, dict):
        return prefs
    if isinstance(prefs, list | tuple):
        return {"hints": [{"name": name} for name in prefs]}
    if hasattr(prefs, "to_wire"):
        return prefs.to_wire()
    if hasattr(prefs, "model_dump"):
        return prefs.model_dump(by_alias=True, exclude_none=True, mode="json")
    raise TypeError(f"Unsupported model_preferences type: {type(prefs).__name__}")


async def _run_sampling_tool(
    tool_map: dict[str, SamplingTool], call: ToolUseContent
) -> dict[str, Any]:
    """Execute one requested tool and shape the ToolResultContent block.

    Tool failures are reported IN-BAND (``isError: true``) so the client's
    LLM can self-correct — mirroring how tool execution errors work in
    tools/call itself.
    """
    tool = tool_map.get(call.name)
    if tool is None:
        return ToolResultContent(
            tool_use_id=call.id,
            content=[TextContent(text=f"Error: unknown tool {call.name!r}")],
            is_error=True,
        ).to_wire()
    try:
        value = await tool.run(call.input)
    except Exception as exc:
        return ToolResultContent(
            tool_use_id=call.id,
            content=[TextContent(text=f"Error executing {call.name}: {exc}")],
            is_error=True,
        ).to_wire()
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return ToolResultContent(
        tool_use_id=call.id,
        content=[TextContent(text=text)],
    ).to_wire()


# AcceptedElicitation is re-exported so callers/tests can isinstance-check
# the same classes handlers see (they come straight from FastMCP).
__all__ = [
    "AcceptedElicitation",
    "CancelledElicitation",
    "DeclinedElicitation",
    "InputRequiredInterrupt",
    "ModernContext",
    "SamplingCallResult",
]
