"""
JSON-RPC / MCP error hierarchy for MCP 2026-07-28.

In the modern era an error is a three-part story: a JSON-RPC ``code``, an
optional structured ``data`` payload, and — on Streamable HTTP — an HTTP
status.  2025-era MCP tunneled every JSON-RPC error inside HTTP 200; the
2026-07-28 revision instead makes the HTTP status carry meaning so
intermediaries (load balancers, caches, API gateways) can react without
parsing bodies:

- ``400 Bad Request`` — all three MCP-allocated codes MUST use it
  (HeaderMismatch ``-32020``, MissingRequiredClientCapability ``-32021``,
  UnsupportedProtocolVersion ``-32022``), as well as ``-32602`` for missing
  required ``_meta`` fields.
- ``404 Not Found`` — a method the server does not implement (``-32601``).
  The JSON-RPC body distinguishes this from a bare 404 off a legacy
  HTTP+SSE server, which matters for era detection.
- ``500 Internal Server Error`` — ``-32603``.

The error-code space itself was formalized in this revision: the JSON-RPC
implementation-defined range is partitioned into ``-32000..-32019``
(implementation-defined, spec will never allocate) and ``-32020..-32099``
(spec-reserved, allocated sequentially).  The retired codes ``-32002``
(resource-not-found, now ``-32602``) and ``-32042`` (URL elicitation
required) are reserved forever and MUST NOT be emitted.

``http_status`` on these exceptions applies ONLY to the Streamable HTTP
transport — stdio has no status line, so the stdio driver just serializes
the JSON-RPC error body and ignores the attribute.

Spec references: MCP 2026-07-28 base protocol (error-code allocation
policy), streamable-http transport §server-validation, SEP-2575.
"""

from collections.abc import Sequence
from typing import Any

from modern.types import (
    HEADER_MISMATCH,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    PARSE_ERROR,
    UNSUPPORTED_PROTOCOL_VERSION,
    error_response,
)


class McpError(Exception):
    """Base protocol error: carries everything needed to answer the peer.

    ``code``/``message``/``data`` map straight onto the JSON-RPC error
    object; ``http_status`` tells the HTTP layer which status line to use
    (ignored on stdio).  Handlers raise these; the dispatcher catches them
    and calls :meth:`to_error_response`.
    """

    def __init__(
        self,
        code: int,
        message: str,
        data: dict[str, Any] | None = None,
        http_status: int = 400,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data
        self.http_status = http_status

    def to_error_response(self, request_id: str | int | None) -> dict[str, Any]:
        """Render the JSON-RPC error response dict for this error.

        ``request_id`` is None only when the incoming request's id could not
        be read (parse/invalid-request failures) — the ``id`` key is then
        omitted, matching the schema's optional ``JSONRPCErrorResponse.id``.
        """
        return error_response(request_id, self.code, self.message, self.data)


class ParseError(McpError):
    """-32700: the body was not valid JSON at all."""

    def __init__(self, message: str = "Parse error") -> None:
        super().__init__(PARSE_ERROR, message, http_status=400)


class InvalidRequestError(McpError):
    """-32600: valid JSON but not a valid JSON-RPC request.

    Covers e.g. a batch array (modern MCP forbids batching), a missing
    ``jsonrpc: "2.0"`` member, or a null request id (MCP is stricter than
    base JSON-RPC: ids MUST be string or integer, never null).
    """

    def __init__(self, message: str = "Invalid request") -> None:
        super().__init__(INVALID_REQUEST, message, http_status=400)


class MethodNotFoundError(McpError):
    """-32601: unknown method, or one gated behind an unadvertised SERVER
    capability.

    On HTTP this rides status 404 — deliberately distinguishable from a
    legacy HTTP+SSE server's bare 404 because the body is a JSON-RPC error.
    (A missing CLIENT capability is -32021, not this.)
    """

    def __init__(self, message: str = "Method not found") -> None:
        super().__init__(METHOD_NOT_FOUND, message, http_status=404)


class InvalidParamsError(McpError):
    """-32602: bad params — the workhorse rejection code in 2026-07-28.

    The spec funnels many failures here: missing required ``_meta`` fields,
    unknown tool/prompt names, invalid tool arguments, bad pagination
    cursors, invalid log levels, undeclared elicitation modes, and
    resource-not-found (which retired the legacy ``-32002``).
    """

    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(INVALID_PARAMS, message, data=data, http_status=400)


class InternalError(McpError):
    """-32603: the server broke.  HTTP 500."""

    def __init__(self, message: str = "Internal error", data: dict[str, Any] | None = None) -> None:
        super().__init__(INTERNAL_ERROR, message, data=data, http_status=500)


class HeaderMismatchError(McpError):
    """-32020 HeaderMismatch (SEP-2243): the HTTP envelope lied about the body.

    Streamable HTTP mirrors body fields into headers (``MCP-Protocol-Version``,
    ``Mcp-Method``, ``Mcp-Name``, ``Mcp-Param-*``) so intermediaries can route
    without parsing JSON.  A server that processes the body MUST verify the
    mirror is truthful — a mismatch means an intermediary made a decision on
    different data than the server executed (a split-source-of-truth attack).
    Also raised for missing required standard headers and invalid header
    characters (including malformed Base64 sentinel values).
    """

    def __init__(
        self,
        message: str = (
            "The HTTP headers do not match the corresponding values in the "
            "request body, or required headers are missing or malformed"
        ),
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(HEADER_MISMATCH, message, data=data, http_status=400)


class MissingClientCapabilityError(McpError):
    """-32021 MissingRequiredClientCapability.

    Modern capabilities are declared per request in ``_meta``; if the current
    request needs something the client did not declare (e.g. the handler
    wants to elicit but the request carried no ``elicitation`` capability),
    the server MUST refuse with this code and name what was missing in
    ``data.requiredCapabilities`` — shaped like a ClientCapabilities object,
    so the client can diff it against what it sends.
    """

    def __init__(
        self,
        required: dict[str, Any],
        message: str | None = None,
    ) -> None:
        self.required = required
        super().__init__(
            MISSING_REQUIRED_CLIENT_CAPABILITY,
            message or "Server requires client capabilities that were not declared on this request",
            data={"requiredCapabilities": required},
            http_status=400,
        )


class UnsupportedProtocolVersionError(McpError):
    """-32022 UnsupportedProtocolVersion.

    With no handshake, version agreement happens per request: the client
    states a version in ``_meta`` and the server either serves it or rejects
    with this error, whose ``data`` MUST carry ``supported`` (the server's
    version list, so the client can pick one and retry) and ``requested``
    (what the client asked for).  This error doubles as an era beacon: a
    dual-era client that sees -32022 in a 400 body knows it is talking to a
    MODERN server and must not fall back to ``initialize``.
    """

    def __init__(
        self,
        requested: str,
        supported: Sequence[str],
        message: str = "Unsupported protocol version",
    ) -> None:
        self.requested = requested
        self.supported = list(supported)
        super().__init__(
            UNSUPPORTED_PROTOCOL_VERSION,
            message,
            data={"supported": self.supported, "requested": requested},
            http_status=400,
        )
