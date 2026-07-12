"""
MRTR engine — stateless Multi Round-Trip Requests for MCP 2026-07-28
(SEP-2322).

This module is the heart of the modern era.  Legacy MCP let a server pause
mid-tool-call and send its OWN JSON-RPC request to the client (elicitation/
create, sampling/createMessage, roots/list), holding the original request
open on a stateful connection until the answer came back.  2026-07-28
deleted that pattern outright: connections carry no session, any retry may
land on a DIFFERENT server instance behind a load balancer, and servers may
not initiate requests at all.  MRTR is the replacement:

1. The client calls e.g. ``tools/call``.
2. Instead of the final result, the server returns ``resultType:
   "input_required"`` with an ``inputRequests`` map (server-chosen keys ->
   plain ``{method, params}`` objects) and an opaque ``requestState`` blob.
3. The client gathers the answers and RETRIES the original request — new
   JSON-RPC id, same method/name/arguments — adding ``inputResponses``
   (same keys) and echoing ``requestState`` byte-for-byte.
4. The server reconstitutes everything it needs from the retry alone.

**The re-execution model.**  Where does the server "resume" from, with no
session to hold a paused coroutine?  It doesn't resume — it RE-EXECUTES the
handler from the top on every retry.  The trick that makes this correct is
deterministic call keys: each ``ctx.elicit()``/``ctx.sample()`` call site is
numbered in call order (``elicit:0``, ``sample:0``, ``sample:1``, ...), and
answered calls return instantly from the memo of collected responses.  A
handler that asks two questions runs three times:

    run 1: elicit:0 missing            -> input_required {elicit:0}
    run 2: elicit:0 memoized, elicit:1 missing -> input_required {elicit:1}
    run 3: both memoized               -> complete result

The memo travels INSIDE ``requestState`` — the server keeps nothing.  This
is the same bargain as event-sourcing or React reconciliation: pay
re-execution cost to buy statelessness.  The contract handlers must honor:
same inputs -> same sequence of input calls (and side effects before the
last input call re-run on every retry, so they should be idempotent or
deferred — see modern/context.py).

**Why the HMAC?**  ``requestState`` transits the CLIENT.  The spec is
blunt: servers MUST treat it as attacker-controlled, MUST integrity-protect
it when it influences authorization/resource access/business logic, and
MUST reject state that fails verification.  Our state carries elicitation
answers ("yes, waive the fine check") — that IS business logic, so we sign:

    state = base64url(payload-json) + "." + base64url(HMAC-SHA256(secret, payload-json))

(the shape of a JWS, hand-rolled so every byte is visible to the reader).
The payload also embeds the anti-replay trio the spec says SHOULD be
verified — and we verify all three:

- ``p``: the authenticated principal — a state minted for Alice is useless
  to Bob;
- ``exp``: a short TTL (15 minutes) — bounds the replay window;
- ``m``/``n``/``a``: the originating request's method, tool/resource name,
  and a digest of its arguments — consent to "checkout book X for patron Y"
  cannot be replayed onto "checkout book Z".

Note the spec's warning, faithfully repeated: these bound the replay window
but do NOT make the state single-use.  A client can legally retry the same
state twice inside the TTL.  At-most-once effects (our checkout creates a
loan!) must be enforced by the business layer — which is why handlers put
side effects AFTER input gathering.

Tampered, expired, or re-bound state -> ``-32602`` Invalid params with a
message that says which check failed (teaching server: loud failures).

Spec: MCP 2026-07-28, basic/patterns/mrtr; SEP-2322 (resultType +
InputRequiredResult), SEP-2575 (statelessness that motivates it all).
"""

import base64
import binascii
import hashlib
import hmac
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from modern.context import InputRequiredInterrupt
from modern.errors import InvalidParamsError
from modern.types import RESULT_INPUT_REQUIRED, complete_result

#: The spec leaves expiry to server policy ("SHOULD include a short TTL");
#: 15 minutes comfortably covers a human answering a form.
DEFAULT_TTL_SECONDS = 900

#: requestState schema version — lets a future revision of this server
#: reject blobs minted by an incompatible older/newer implementation.
_STATE_VERSION = 1


def canonical_arguments_hash(arguments: dict[str, Any] | None) -> str:
    """Digest of the request's salient arguments, for state binding.

    Canonical JSON (sorted keys, no whitespace) makes the digest independent
    of client-side key ordering — two retries with semantically identical
    arguments MUST verify against the same state.  16 hex chars (64 bits)
    is plenty: this is a binding check, not a cryptographic commitment (the
    HMAC over the whole payload provides the integrity).
    """
    canonical = json.dumps(arguments or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class RequestStateCodec:
    """Signs and verifies the opaque ``requestState`` blob.

    Encode: serialize the payload dict as JSON, MAC it with HMAC-SHA256,
    emit ``base64url(payload) + "." + base64url(mac)``.  Decode: verify the
    MAC in constant time over the EXACT received bytes (never re-serialize
    before verifying — canonicalization bugs are how signature bypasses are
    born), then check expiry.  Request binding (method/name/args/principal)
    is the engine's job because only it knows the current request.
    """

    def __init__(self, secret: bytes) -> None:
        if not secret:
            raise ValueError("RequestStateCodec requires a non-empty secret")
        self._secret = secret

    def encode(self, payload: dict[str, Any]) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        mac = hmac.new(self._secret, body, hashlib.sha256).digest()
        return (
            base64.urlsafe_b64encode(body).decode("ascii")
            + "."
            + base64.urlsafe_b64encode(mac).decode("ascii")
        )

    def decode(self, state: str) -> dict[str, Any]:
        """Verify and open a ``requestState`` string.

        Raises:
            InvalidParamsError: malformed encoding, failed MAC (tampering —
                the spec's MUST-reject case), or expired TTL.  All map to
                ``-32602`` per the modern error taxonomy.
        """
        head, sep, tail = state.partition(".")
        if not sep or not head or not tail:
            raise InvalidParamsError(
                "Invalid requestState: expected '<payload>.<mac>' format "
                "(the value must be echoed back exactly as the server sent it)"
            )
        try:
            body = base64.urlsafe_b64decode(head.encode("ascii"))
            received_mac = base64.urlsafe_b64decode(tail.encode("ascii"))
        except (ValueError, binascii.Error) as exc:
            raise InvalidParamsError(f"Invalid requestState: bad base64 ({exc})") from exc

        expected_mac = hmac.new(self._secret, body, hashlib.sha256).digest()
        # compare_digest: constant-time comparison so response timing cannot
        # be used to forge a MAC byte by byte.
        if not hmac.compare_digest(expected_mac, received_mac):
            raise InvalidParamsError(
                "Invalid requestState: integrity verification failed — the state was "
                "modified in transit or minted with a different secret (tampered state "
                "MUST be rejected, MCP 2026-07-28 basic/patterns/mrtr)"
            )

        try:
            payload = json.loads(body)
        except ValueError as exc:  # unreachable if we minted it, but be loud
            raise InvalidParamsError("Invalid requestState: payload is not JSON") from exc
        if not isinstance(payload, dict):
            raise InvalidParamsError("Invalid requestState: payload is not an object")

        if payload.get("v") != _STATE_VERSION:
            raise InvalidParamsError(
                f"Invalid requestState: unsupported state version {payload.get('v')!r}"
            )

        exp = payload.get("exp")
        if not isinstance(exp, int | float) or isinstance(exp, bool):
            raise InvalidParamsError("Invalid requestState: missing expiry")
        if time.time() > exp:
            raise InvalidParamsError(
                "Invalid requestState: state has expired — re-issue the original "
                "request without requestState to start over"
            )
        return payload


async def run_with_mrtr(
    execute: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    *,
    method: str,
    name: str,
    arguments: dict[str, Any] | None,
    params: dict[str, Any],
    codec: RequestStateCodec,
    principal_id: str = "anon",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    """Run one (re-)execution of an MRTR-capable request.

    Only ``tools/call``, ``prompts/get``, and ``resources/read`` may return
    ``InputRequiredResult`` (spec MUST NOT elsewhere) — the dispatcher
    routes exactly those three through here.

    Args:
        execute: runs the handler against a memo dict of collected input
            responses (a fresh ModernContext wraps the memo); returns the
            final result dict or raises :class:`InputRequiredInterrupt`.
        method/name/arguments: identity of the ORIGINATING request, bound
            into the signed state and verified on every retry.
        params: the raw request params — supplies ``requestState`` and
            ``inputResponses`` on retries.
        principal_id: authenticated principal ("anon" when auth is off);
            state minted under one principal is rejected under another.
    """
    args_hash = canonical_arguments_hash(arguments)

    # 1. Reconstitute prior answers from the signed state, if any.
    collected: dict[str, Any] = {}
    state = params.get("requestState")
    if state is not None:
        if not isinstance(state, str):
            raise InvalidParamsError("requestState must be a string")
        payload = codec.decode(state)  # MAC + expiry verified inside
        # Request binding (spec SHOULD, all three verified): the state must
        # have been minted for THIS method + name + arguments + principal.
        if payload.get("m") != method or payload.get("n") != name:
            raise InvalidParamsError(
                "Invalid requestState: state is bound to a different request "
                f"({payload.get('m')!r} {payload.get('n')!r}, not {method!r} {name!r})"
            )
        if payload.get("a") != args_hash:
            raise InvalidParamsError(
                "Invalid requestState: state is bound to different arguments — "
                "retries MUST repeat the original arguments unchanged"
            )
        if payload.get("p") != principal_id:
            raise InvalidParamsError(
                "Invalid requestState: state is bound to a different principal"
            )
        replayed = payload.get("r")
        if isinstance(replayed, dict):
            collected.update(replayed)

    # 2. Merge the client's NEW answers.  Unknown keys are tolerated (spec
    # SHOULD ignore unrecognized entries) — they simply go unconsumed.
    responses = params.get("inputResponses")
    if responses is not None:
        if not isinstance(responses, dict):
            raise InvalidParamsError("inputResponses must be an object")
        collected.update(responses)

    # 3. Re-execute the handler from the top against the memo.
    try:
        result = await execute(collected)
    except InputRequiredInterrupt as interrupt:
        # 4. The handler needs (more) input: seal everything collected so
        # far into a fresh signed state (sliding TTL window) and hand the
        # client exactly one request to fulfill.  At least one of
        # inputRequests/requestState MUST be present — we always send both.
        request_state = codec.encode(
            {
                "v": _STATE_VERSION,
                "m": method,
                "n": name,
                "a": args_hash,
                "p": principal_id,
                "exp": int(time.time()) + ttl_seconds,
                "r": collected,
            }
        )
        return {
            "resultType": RESULT_INPUT_REQUIRED,
            "inputRequests": {interrupt.key: interrupt.input_request},
            "requestState": request_state,
        }

    # 5. Done — guarantee the wire-required resultType on the way out.
    return complete_result(result)
