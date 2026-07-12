"""
Per-request ``_meta`` parsing and the Base64 sentinel header codec.

MCP 2026-07-28 (SEP-2575) deleted the ``initialize`` handshake, so the
protocol facts a legacy server learned once per session now arrive on EVERY
request inside ``params._meta``:

- ``io.modelcontextprotocol/protocolVersion`` (required)
- ``io.modelcontextprotocol/clientInfo``      (required, Implementation)
- ``io.modelcontextprotocol/clientCapabilities`` (required, per-request!)
- ``io.modelcontextprotocol/logLevel``        (optional, deprecated SEP-2577)
- ``progressToken``                           (optional, unprefixed reserved)
- ``traceparent`` / ``tracestate`` / ``baggage`` (optional, OTel, SEP-414)

:func:`parse_request_meta` is the modern dispatcher's front door: it runs
BEFORE method routing on every request, because a request without valid
``_meta`` is malformed regardless of what method it names.  The spec is
strict about the failure modes and we mirror them exactly:

- missing ``_meta`` or any required key -> ``-32602`` Invalid params
  (HTTP 400).  Statelessness only works if servers refuse to guess.
- a version outside this dispatcher's modern set -> ``-32022``
  UnsupportedProtocolVersion with ``data.supported``/``data.requested``
  (HTTP 400) so the client can pick a mutual version and retry.  Note the
  dual-era subtlety: the LEGACY versions our FastMCP side speaks also land
  here, because era routing happens in the HTTP layer before dispatch — by
  the time this code runs, only 2026-07-28 requests belong on this path.

This module also implements the Base64 sentinel codec from the Streamable
HTTP binding (SEP-2243, spec §value-encoding).  HTTP mirrors ``params.name``/
``params.uri`` into the ``Mcp-Name`` header (and annotated tool arguments
into ``Mcp-Param-*`` headers) so intermediaries can route without parsing
bodies — but HTTP field values are limited to visible ASCII.  Values that
are not representable (non-ASCII, control characters, leading/trailing
whitespace) travel as ``=?base64?{base64-of-utf8}?=``.  Two easy-to-miss
rules from the spec:

1. The markers ``=?base64?`` and ``?=`` are CASE-SENSITIVE and lowercase —
   ``=?BASE64?...?=`` is not a sentinel, it is a literal value.
2. Anti-ambiguity: a plain-ASCII value that ITSELF matches the sentinel
   pattern must be encoded anyway, otherwise a literal ``"=?base64?x?="``
   string and an encoded value would be indistinguishable on the wire.

Servers MUST decode sentinel-encoded headers before comparing them to body
values during header validation; a malformed sentinel payload is a header
validation failure (``-32020`` HeaderMismatch, HTTP 400).
"""

import base64
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from modern.errors import (
    HeaderMismatchError,
    InvalidParamsError,
    UnsupportedProtocolVersionError,
)
from modern.types import (
    LOGGING_LEVELS,
    META_CLIENT_CAPS,
    META_CLIENT_INFO,
    META_LOG_LEVEL,
    META_PROGRESS_TOKEN,
    META_PROTOCOL_VERSION,
    MODERN_VERSIONS,
    SUPPORTED_VERSIONS,
    TRACE_META_KEYS,
    ClientCapabilities,
    Implementation,
)

# ---------------------------------------------------------------------------
# RequestMeta — the validated view of params._meta
# ---------------------------------------------------------------------------


@dataclass
class RequestMeta:
    """Validated per-request protocol metadata.

    One of these is produced for every request the modern dispatcher
    handles.  It is the ONLY place downstream code should learn the client's
    version/identity/capabilities from — never from prior requests, never
    from the transport connection (statelessness, SEP-2575).
    """

    protocol_version: str
    client_info: Implementation
    client_capabilities: ClientCapabilities
    #: None means the request opted OUT of logging: the server MUST NOT emit
    #: notifications/message for this request (per-request replacement for
    #: the removed logging/setLevel RPC; deprecated SEP-2577).
    log_level: str | None
    #: None means the client did not opt in to notifications/progress.
    progress_token: str | int | None
    #: OTel trace-context passthrough (traceparent/tracestate/baggage).
    trace: dict[str, str]


def parse_request_meta(params: dict[str, Any] | None) -> RequestMeta:
    """Extract and strictly validate ``params._meta`` for a modern request.

    Raises:
        InvalidParamsError: ``_meta`` (or a required key) is missing or
            malformed — the spec mandates ``-32602`` / HTTP 400.
        UnsupportedProtocolVersionError: the stated version is not one this
            dispatcher serves — ``-32022`` / HTTP 400 with
            ``data.supported`` listing every version the dual-era server
            accepts (modern AND legacy), so clients can renegotiate.
    """
    # `params` itself may legally be absent on some requests (server/discover
    # takes nothing beyond _meta) — but _meta can then not be present either,
    # which is exactly the malformed-request case the spec calls out.
    if not isinstance(params, dict):
        raise InvalidParamsError(
            "Request params must be an object containing '_meta' "
            "(required on every MCP 2026-07-28 request)"
        )

    meta_value = params.get("_meta")
    if not isinstance(meta_value, dict):
        raise InvalidParamsError(
            "Request params must include an '_meta' object with the required keys "
            f"'{META_PROTOCOL_VERSION}', '{META_CLIENT_INFO}', '{META_CLIENT_CAPS}'"
        )
    meta: dict[str, Any] = meta_value

    # Presence of the required trio first: a request missing any of them is
    # malformed (-32602) BEFORE we consider whether we like the version.
    missing = [
        key
        for key in (META_PROTOCOL_VERSION, META_CLIENT_INFO, META_CLIENT_CAPS)
        if key not in meta
    ]
    if missing:
        raise InvalidParamsError(
            "Request _meta is missing required key(s): " + ", ".join(f"'{k}'" for k in missing)
        )

    requested_version = meta[META_PROTOCOL_VERSION]
    if not isinstance(requested_version, str):
        raise InvalidParamsError(f"_meta['{META_PROTOCOL_VERSION}'] must be a string")

    # Version gate: this dispatcher only speaks the modern era.  The error
    # data still advertises the FULL dual-era list — a client that retries
    # with a legacy version will be routed to the FastMCP app by the HTTP
    # layer and never reach this code again.
    if requested_version not in MODERN_VERSIONS:
        raise UnsupportedProtocolVersionError(
            requested=requested_version,
            supported=list(SUPPORTED_VERSIONS),
        )

    try:
        client_info = Implementation.model_validate(meta[META_CLIENT_INFO])
    except ValidationError as exc:
        raise InvalidParamsError(
            f"_meta['{META_CLIENT_INFO}'] is not a valid Implementation "
            "(requires 'name' and 'version')"
        ) from exc

    try:
        client_capabilities = ClientCapabilities.model_validate(meta[META_CLIENT_CAPS])
    except ValidationError as exc:
        raise InvalidParamsError(
            f"_meta['{META_CLIENT_CAPS}'] is not a valid ClientCapabilities object"
        ) from exc

    # Optional: per-request log level.  The spec routes "invalid log level"
    # to -32602, so we validate against the RFC 5424 set rather than accept
    # arbitrary strings.
    log_level = meta.get(META_LOG_LEVEL)
    if log_level is not None and log_level not in LOGGING_LEVELS:
        raise InvalidParamsError(
            f"_meta['{META_LOG_LEVEL}'] must be one of {list(LOGGING_LEVELS)}, got {log_level!r}"
        )

    # Optional: progress token — string or integer per ProgressToken.
    # bool is excluded explicitly (Python bools ARE ints, JSON booleans are
    # not JSON-RPC ids/tokens).
    progress_token = meta.get(META_PROGRESS_TOKEN)
    if progress_token is not None and (
        isinstance(progress_token, bool) or not isinstance(progress_token, str | int)
    ):
        raise InvalidParamsError(f"_meta['{META_PROGRESS_TOKEN}'] must be a string or integer")

    # OTel passthrough: opaque, but only string values are format-valid.
    trace = {key: value for key in TRACE_META_KEYS if isinstance(value := meta.get(key), str)}

    return RequestMeta(
        protocol_version=requested_version,
        client_info=client_info,
        client_capabilities=client_capabilities,
        log_level=log_level,
        progress_token=progress_token,
        trace=trace,
    )


# ---------------------------------------------------------------------------
# Base64 sentinel codec (Streamable HTTP value encoding, SEP-2243 §2.8)
# ---------------------------------------------------------------------------

#: Case-sensitive, lowercase — MUST appear exactly as shown on the wire.
SENTINEL_PREFIX = "=?base64?"
SENTINEL_SUFFIX = "?="


def _is_plain_header_safe(value: str) -> bool:
    """Can ``value`` travel as a raw RFC 9110 field value, unmodified?

    RFC 9110 field values are visible ASCII (0x21-0x7E) plus interior space
    and horizontal tab.  Leading/trailing whitespace is disqualifying even
    though space/tab are otherwise legal: HTTP strips optional whitespace
    around field values, so a padded value would be silently corrupted in
    transit — the spec therefore requires encoding it.
    """
    if value != value.strip(" \t"):
        return False
    return all(ch in (" ", "\t") or "\x21" <= ch <= "\x7e" for ch in value)


def _matches_sentinel_pattern(value: str) -> bool:
    """Does ``value`` LOOK like an encoded sentinel (starts/ends with the
    markers)?  Used for both decode detection and the anti-ambiguity rule."""
    return value.startswith(SENTINEL_PREFIX) and value.endswith(SENTINEL_SUFFIX)


def encode_header_value(value: str) -> str:
    """Encode a body value for use in ``Mcp-Name`` / ``Mcp-Param-*`` headers.

    Plain-ASCII-safe values pass through untouched.  Everything else —
    non-ASCII, control characters (newlines!), leading/trailing whitespace —
    becomes ``=?base64?{base64(utf8(value))}?=``.

    Anti-ambiguity rule (spec MUST): a value that is itself shaped like a
    sentinel (starts ``=?base64?``, ends ``?=``) is Base64-encoded even when
    it is otherwise header-safe.  Without this, the literal string
    ``"=?base64?foo?="`` and an encoded value would collide on the wire and
    :func:`decode_header_value` could not round-trip.
    """
    if _is_plain_header_safe(value) and not _matches_sentinel_pattern(value):
        return value
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"{SENTINEL_PREFIX}{encoded}{SENTINEL_SUFFIX}"


def decode_header_value(value: str) -> str:
    """Decode a header value that MAY be sentinel-encoded.

    Values not shaped like a sentinel pass through unchanged.  The marker
    comparison is case-sensitive per spec: ``=?BASE64?...?=`` is a literal
    header value, not an encoding.  Servers MUST run this before comparing
    ``Mcp-Name`` / ``Mcp-Param-*`` headers against body values.

    Raises:
        HeaderMismatchError: the value claims to be sentinel-encoded but the
            payload is not valid Base64 / UTF-8.  That is a malformed header
            (-32020, HTTP 400) — the http layer can let this propagate
            straight into the error response.
    """
    if not _matches_sentinel_pattern(value):
        return value
    payload = value[len(SENTINEL_PREFIX) : -len(SENTINEL_SUFFIX)]
    try:
        # validate=True rejects non-alphabet characters instead of silently
        # discarding them — a lenient decode would let two different header
        # strings compare equal to the same body value.
        raw = base64.b64decode(payload.encode("ascii"), validate=True)
        return raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise HeaderMismatchError(f"Malformed Base64 sentinel in header value: {exc}") from exc
