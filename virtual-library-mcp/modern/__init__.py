"""
MCP 2026-07-28 ("the modern era") implemented from scratch — for learning.

The rest of this repository speaks legacy MCP (2025-11-25 and earlier)
through FastMCP.  This package deliberately uses NO MCP SDK: it implements
the 2026-07-28 revision directly from the specification, because the best
way to understand what changed — and why — is to build it.  Every module
carries teaching docstrings citing the spec and the SEPs that shaped it.

What makes 2026-07-28 a new era rather than another increment:

- **Stateless protocol (SEP-2575).**  ``initialize``/``notifications/
  initialized`` and protocol-level sessions (SEP-2567) are gone.  Every
  request carries protocol version, client info, and client capabilities in
  ``params._meta``; a new mandatory ``server/discover`` RPC replaces the
  handshake for up-front capability discovery.  ``ping``, ``logging/
  setLevel``, and ``notifications/roots/list_changed`` were removed.

- **MRTR — Multi Round-Trip Requests (SEP-2322).**  Servers never initiate
  JSON-RPC requests anymore.  Elicitation, sampling, and roots are embedded
  in an ``InputRequiredResult`` (``resultType: "input_required"``) and the
  client RETRIES the original request with ``inputResponses`` plus the
  server's opaque, integrity-protected ``requestState``.  Every result now
  requires a ``resultType`` field.

- **Header mirroring on Streamable HTTP (SEP-2243).**  ``Mcp-Method`` and
  ``Mcp-Name`` headers mirror body fields so intermediaries can route
  without parsing JSON; mismatches are ``-32020`` HeaderMismatch.  Values
  that are not header-safe travel Base64-encoded in the ``=?base64?...?=``
  sentinel format (see modern/meta.py).

- **Cacheable results (SEP-2549).**  Discover/list/read results carry
  required ``ttlMs`` and ``cacheScope`` — possible only because sessions are
  gone and list results no longer vary per connection.

- **Subscriptions via one long-lived request (SEP-2575).**  The HTTP GET
  stream and ``resources/subscribe`` are replaced by ``subscriptions/
  listen``, whose response stream carries only opted-in notifications.

- **Deprecations, not deletions (SEP-2577).**  Roots, sampling, and logging
  remain functional for >= 12 months but are marked deprecated; tasks moved
  out of core into the ``io.modelcontextprotocol/tasks`` extension
  (SEP-2663); skills arrive as an extension too (SEP-2640).

Package layout: ``types`` (wire models + constants), ``errors`` (JSON-RPC
error hierarchy with HTTP status mapping), ``meta`` (per-request ``_meta``
validation + Base64 sentinel codec), plus context/mrtr/registry/dispatcher/
broker/http/stdio/auth modules that build the full server on top of these.

Spec: https://modelcontextprotocol.io/specification/draft (wire version
string "2026-07-28"), changelog: /specification/draft/changelog.
"""

from modern.errors import (
    HeaderMismatchError,
    InternalError,
    InvalidParamsError,
    InvalidRequestError,
    McpError,
    MethodNotFoundError,
    MissingClientCapabilityError,
    ParseError,
    UnsupportedProtocolVersionError,
)
from modern.meta import (
    RequestMeta,
    decode_header_value,
    encode_header_value,
    parse_request_meta,
)
from modern.types import (
    HEADER_MISMATCH,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    JSONRPC_VERSION,
    LEGACY_VERSIONS,
    LOGGING_LEVELS,
    META_CLIENT_CAPS,
    META_CLIENT_INFO,
    META_LOG_LEVEL,
    META_PROGRESS_TOKEN,
    META_PROTOCOL_VERSION,
    META_SUBSCRIPTION_ID,
    METHOD_NOT_FOUND,
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    MODERN_VERSIONS,
    PARSE_ERROR,
    PROTOCOL_VERSION,
    RESULT_COMPLETE,
    RESULT_INPUT_REQUIRED,
    SUPPORTED_VERSIONS,
    UNSUPPORTED_PROTOCOL_VERSION,
    Annotations,
    AudioContent,
    BlobResourceContents,
    CacheableResult,
    CallToolResult,
    ClientCapabilities,
    CompleteResult,
    Completion,
    ContentBlock,
    CreateMessageRequest,
    CreateMessageRequestParams,
    CreateMessageResult,
    DiscoverResult,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitRequestURLParams,
    ElicitResult,
    EmbeddedResource,
    GetPromptResult,
    Icon,
    ImageContent,
    Implementation,
    InputRequest,
    InputRequiredResult,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListRootsRequest,
    ListRootsResult,
    ListToolsResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    ReadResourceResult,
    Resource,
    ResourceLink,
    ResourceTemplate,
    Result,
    Root,
    SamplingMessage,
    ServerCapabilities,
    SubscriptionFilter,
    TextContent,
    TextResourceContents,
    Tool,
    ToolAnnotations,
    complete_result,
    error_response,
)

__all__ = [
    "HEADER_MISMATCH",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "JSONRPC_VERSION",
    "LEGACY_VERSIONS",
    "LOGGING_LEVELS",
    "META_CLIENT_CAPS",
    "META_CLIENT_INFO",
    "META_LOG_LEVEL",
    "META_PROGRESS_TOKEN",
    "META_PROTOCOL_VERSION",
    "META_SUBSCRIPTION_ID",
    "METHOD_NOT_FOUND",
    "MISSING_REQUIRED_CLIENT_CAPABILITY",
    "MODERN_VERSIONS",
    "PARSE_ERROR",
    "PROTOCOL_VERSION",
    "RESULT_COMPLETE",
    "RESULT_INPUT_REQUIRED",
    "SUPPORTED_VERSIONS",
    "UNSUPPORTED_PROTOCOL_VERSION",
    "Annotations",
    "AudioContent",
    "BlobResourceContents",
    "CacheableResult",
    "CallToolResult",
    "ClientCapabilities",
    "CompleteResult",
    "Completion",
    "ContentBlock",
    "CreateMessageRequest",
    "CreateMessageRequestParams",
    "CreateMessageResult",
    "DiscoverResult",
    "ElicitRequest",
    "ElicitRequestFormParams",
    "ElicitRequestURLParams",
    "ElicitResult",
    "EmbeddedResource",
    "GetPromptResult",
    "HeaderMismatchError",
    "Icon",
    "ImageContent",
    "Implementation",
    "InputRequest",
    "InputRequiredResult",
    "InternalError",
    "InvalidParamsError",
    "InvalidRequestError",
    "ListPromptsResult",
    "ListResourceTemplatesResult",
    "ListResourcesResult",
    "ListRootsRequest",
    "ListRootsResult",
    "ListToolsResult",
    "McpError",
    "MethodNotFoundError",
    "MissingClientCapabilityError",
    "ParseError",
    "Prompt",
    "PromptArgument",
    "PromptMessage",
    "ReadResourceResult",
    "RequestMeta",
    "Resource",
    "ResourceLink",
    "ResourceTemplate",
    "Result",
    "Root",
    "SamplingMessage",
    "ServerCapabilities",
    "SubscriptionFilter",
    "TextContent",
    "TextResourceContents",
    "Tool",
    "ToolAnnotations",
    "UnsupportedProtocolVersionError",
    "complete_result",
    "decode_header_value",
    "encode_header_value",
    "error_response",
    "parse_request_meta",
]
