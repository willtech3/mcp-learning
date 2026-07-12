"""
Wire types and protocol constants for MCP 2026-07-28.

This module is the vocabulary of the "modern era" of the Model Context
Protocol.  MCP 2026-07-28 (SEP-2575) removed the ``initialize`` handshake and
protocol-level sessions (SEP-2567): the protocol is now STATELESS, and every
request carries everything a server needs to process it — protocol version,
client identity, and client capabilities — inside ``params._meta``.  The types
here mirror the authoritative TypeScript definitions in
``schema/draft/schema.ts`` from the modelcontextprotocol repository, using
pydantic v2 models with camelCase wire aliases so Python code stays idiomatic
(snake_case) while the JSON on the wire matches the spec byte for byte.

Key protocol concepts encoded in this module:

1. **Required ``resultType`` (SEP-2322)** — every result object MUST carry a
   ``resultType`` field ("complete" | "input_required" | extension values).
   This is the backbone of MRTR (Multi Round-Trip Requests): instead of the
   server initiating JSON-RPC requests at the client (elicitation, sampling,
   roots — all removed as server-initiated requests), the server returns an
   ``InputRequiredResult`` embedding plain ``{method, params}`` request
   objects, and the client retries the ORIGINAL request with the answers.

2. **``CacheableResult`` (SEP-2549)** — list/read/discover results MUST carry
   ``ttlMs`` (freshness hint, analogous to Cache-Control max-age) and
   ``cacheScope`` ("public" = shareable across authorization contexts,
   "private" = per-authorization-context only).  Because there are no
   sessions, results no longer vary per-connection, which is what makes
   caching by intermediaries safe at all.

3. **Per-request capabilities** — ``ClientCapabilities`` arrive on EVERY
   request via ``_meta``; servers MUST NOT infer capabilities from prior
   requests.  Both capability objects gained an ``extensions`` map (keys are
   prefixed extension identifiers such as ``io.modelcontextprotocol/tasks``).

4. **Spec-reserved error codes** — the JSON-RPC implementation-defined range
   is now partitioned: ``-32000..-32019`` stays implementation-defined, while
   ``-32020..-32099`` is reserved for the MCP spec.  The three codes allocated
   so far (HeaderMismatch ``-32020``, MissingRequiredClientCapability
   ``-32021``, UnsupportedProtocolVersion ``-32022``) all ride HTTP 400 on
   Streamable HTTP.

Deprecated-but-present (SEP-2577, >= 12-month grace period): the client
``roots`` and ``sampling`` capabilities, the server ``logging`` capability,
and the ``io.modelcontextprotocol/logLevel`` ``_meta`` key.  We model them
faithfully — teaching the deprecation story is part of the lesson.

Spec references: https://modelcontextprotocol.io/specification/draft
(schema: schema/draft/schema.ts; changelog: /specification/draft/changelog).
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Protocol version constants
# ---------------------------------------------------------------------------

#: The protocol revision this package implements.  The draft spec
#: self-identifies as "2026-07-28" on the wire (never the string "draft").
PROTOCOL_VERSION = "2026-07-28"

#: Legacy ("initialize"-handshake) revisions served by the FastMCP side of the
#: dual-era server.  Modern-era code rejects these with -32022, but the
#: server as a whole still supports them — hence they appear in
#: server/discover's supportedVersions.
LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

#: Everything the dual-era server supports, newest first.  Advertised by
#: server/discover and carried in UnsupportedProtocolVersionError.data.
SUPPORTED_VERSIONS = (PROTOCOL_VERSION, *LEGACY_VERSIONS)

#: Versions handled by the modern (stateless) dispatcher.  A legacy version
#: arriving on the modern path is still -32022: era routing happens in the
#: HTTP layer BEFORE dispatch, so by the time meta parsing runs, only modern
#: versions are acceptable.
MODERN_VERSIONS = (PROTOCOL_VERSION,)

#: JSON-RPC version string — MCP is JSON-RPC 2.0, full stop.
JSONRPC_VERSION = "2.0"

# ---------------------------------------------------------------------------
# Reserved _meta keys (MCP 2026-07-28, base protocol)
#
# Any _meta prefix whose second dot-label is "modelcontextprotocol" or "mcp"
# is reserved for the spec.  The three "required trio" keys below replace the
# initialize handshake entirely (SEP-2575).
# ---------------------------------------------------------------------------

META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
META_CLIENT_CAPS = "io.modelcontextprotocol/clientCapabilities"
#: Per-request minimum log level; replaces the logging/setLevel RPC.  If a
#: request omits it, the server MUST NOT emit notifications/message for that
#: request.  Deprecated as of 2026-07-28 (SEP-2577) but still functional.
META_LOG_LEVEL = "io.modelcontextprotocol/logLevel"
#: Present on every notification delivered via a subscriptions/listen stream;
#: value is the JSON-RPC id of the listen request that opened the stream.
META_SUBSCRIPTION_ID = "io.modelcontextprotocol/subscriptionId"
#: NOTE: progressToken is an UNPREFIXED reserved key — a deliberate
#: grandfathered exception to the prefix rule, like the OTel trace keys.
META_PROGRESS_TOKEN = "progressToken"

#: OpenTelemetry trace-context keys (SEP-414) — the other unprefixed
#: exceptions.  Values follow W3C Trace Context / W3C Baggage formats and are
#: passed through opaquely.
TRACE_META_KEYS = ("traceparent", "tracestate", "baggage")

#: RFC 5424 logging levels, ordered least severe -> most severe.  Index into
#: this tuple to compare severities ("does this message meet the requested
#: minimum level?").
LOGGING_LEVELS = (
    "debug",
    "info",
    "notice",
    "warning",
    "error",
    "critical",
    "alert",
    "emergency",
)

# ---------------------------------------------------------------------------
# Error codes
#
# Standard JSON-RPC codes cover general failures.  MCP 2026-07-28 formally
# partitions the JSON-RPC server-error range: -32000..-32019 is
# implementation-defined (the spec will never allocate there), while
# -32020..-32099 is reserved for the spec, allocated sequentially.  The
# retired codes -32002 (resource not found; replaced by -32602) and -32042
# (URL elicitation required) are reserved forever and MUST NOT be emitted.
# ---------------------------------------------------------------------------

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

HEADER_MISMATCH = -32020
MISSING_REQUIRED_CLIENT_CAPABILITY = -32021
UNSUPPORTED_PROTOCOL_VERSION = -32022

# ---------------------------------------------------------------------------
# resultType values (SEP-2322)
# ---------------------------------------------------------------------------

RESULT_COMPLETE = "complete"
RESULT_INPUT_REQUIRED = "input_required"


# ---------------------------------------------------------------------------
# Base model
# ---------------------------------------------------------------------------


class WireModel(BaseModel):
    """Base for every wire type in this package.

    - ``populate_by_name=True`` lets Python code construct models with
      snake_case names while the wire uses camelCase aliases.
    - ``extra="allow"`` is a protocol requirement in spirit: the schema's
      ``Result`` type is open (``[key: string]: unknown``) and capability
      objects are explicitly "not closed sets" — a 2026-07-28 peer may send
      fields we do not know about, and we must tolerate and round-trip them
      rather than reject.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    def to_wire(self) -> dict[str, Any]:
        """Serialize to the exact JSON object shape the spec defines.

        ``by_alias`` produces the camelCase field names; ``exclude_none``
        drops optional fields we did not set (the spec marks them optional —
        an explicit ``null`` would be schema-invalid for most of them).
        """
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")


# ---------------------------------------------------------------------------
# Implementation and Icon — the clientInfo & serverInfo shapes
# ---------------------------------------------------------------------------


class Icon(WireModel):
    """An icon for a tool/resource/prompt/implementation (schema ``Icon``).

    Clients that render icons MUST support PNG and JPEG, SHOULD support
    SVG/WebP, and MUST reject unsafe URI schemes (javascript:, file:, ...).
    That enforcement is a CLIENT duty; the server just describes.
    """

    src: str
    mime_type: str | None = Field(default=None, alias="mimeType")
    sizes: list[str] | None = None  # e.g. ["48x48"] or ["any"] for SVG
    theme: Literal["light", "dark"] | None = None


class Implementation(WireModel):
    """Identity of an MCP client or server (schema ``Implementation``).

    Carried on EVERY modern request as ``_meta["io.modelcontextprotocol/
    clientInfo"]`` — there is no handshake to establish identity once, so it
    travels with each message.  ``name`` and ``version`` are required.
    """

    name: str
    version: str
    title: str | None = None
    description: str | None = None
    website_url: str | None = Field(default=None, alias="websiteUrl")
    icons: list[Icon] | None = None


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


class SamplingCapability(WireModel):
    """Client's sampling support.  Deprecated as of 2026-07-28 (SEP-2577).

    ``context`` declares support for ``includeContext``; ``tools`` declares
    support for tool-enabled sampling (SEP-1577).  Presence of the sub-key
    (even ``{}``) is the declaration.
    """

    context: dict[str, Any] | None = None
    tools: dict[str, Any] | None = None


class ElicitationCapability(WireModel):
    """Client's elicitation support: ``form`` and/or ``url`` modes.

    A server MUST NOT embed an elicitation InputRequest whose mode the client
    has not declared (that is a -32021 MissingRequiredClientCapability).
    """

    form: dict[str, Any] | None = None
    url: dict[str, Any] | None = None


class ClientCapabilities(WireModel):
    """What the client can do — declared per request (schema ``ClientCapabilities``).

    Modern MCP has no negotiation: the client repeats this object in ``_meta``
    on every request and the server MUST NOT remember it across requests.
    An empty object means "no optional capabilities".  Capability sets are
    not closed — unknown members are tolerated (``extra="allow"``).
    """

    experimental: dict[str, dict[str, Any]] | None = None
    #: Deprecated as of 2026-07-28 (SEP-2577); empty object declares support.
    roots: dict[str, Any] | None = None
    #: Deprecated as of 2026-07-28 (SEP-2577).
    sampling: SamplingCapability | None = None
    elicitation: ElicitationCapability | None = None
    #: Extension id -> settings; ``{}`` = supported with no settings.  Keys
    #: MUST follow the _meta naming rules WITH a mandatory prefix,
    #: e.g. "io.modelcontextprotocol/tasks".
    extensions: dict[str, dict[str, Any]] | None = None


class PromptsCapability(WireModel):
    list_changed: bool | None = Field(default=None, alias="listChanged")


class ResourcesCapability(WireModel):
    subscribe: bool | None = None
    list_changed: bool | None = Field(default=None, alias="listChanged")


class ToolsCapability(WireModel):
    list_changed: bool | None = Field(default=None, alias="listChanged")


class ServerCapabilities(WireModel):
    """What the server offers — advertised via server/discover.

    The ``listChanged``/``subscribe`` booleans survive from the legacy era
    but now describe which notification types a ``subscriptions/listen``
    stream can deliver, since resources/subscribe and the HTTP GET stream
    were removed (SEP-2575).
    """

    experimental: dict[str, dict[str, Any]] | None = None
    #: Deprecated as of 2026-07-28 (SEP-2577).
    logging: dict[str, Any] | None = None
    completions: dict[str, Any] | None = None
    prompts: PromptsCapability | None = None
    resources: ResourcesCapability | None = None
    tools: ToolsCapability | None = None
    #: Extension id -> settings, same naming rules as the client side —
    #: e.g. {"io.modelcontextprotocol/tasks": {...},
    #:       "io.modelcontextprotocol/skills": {"directoryRead": true}}.
    extensions: dict[str, dict[str, Any]] | None = None


# ---------------------------------------------------------------------------
# Result bases: Result / CacheableResult (SEP-2322, SEP-2549)
# ---------------------------------------------------------------------------


class Result(WireModel):
    """Base of every result object: ``resultType`` is REQUIRED on the wire.

    Servers implementing 2026-07-28 MUST include ``resultType``; clients
    talking to OLDER servers must treat an absent field as "complete".  We
    default it to "complete" so every serialized result is compliant even if
    a handler forgets to set it.
    """

    result_type: str = Field(default=RESULT_COMPLETE, alias="resultType")
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


class CacheableResult(Result):
    """Mixin for results that clients and intermediaries may cache (SEP-2549).

    Both fields are wire-REQUIRED:

    - ``ttlMs``: freshness hint in milliseconds (Cache-Control max-age
      analog).  0 = immediately stale; positive = fresh for that long.
    - ``cacheScope``: "public" results contain no user-specific data and MAY
      be cached across authorization contexts (shared gateways!); "private"
      results MUST NOT be shared across authorization contexts.

    Applies to (SEP-2549): DiscoverResult, the four list results
    (tools/prompts/resources/templates), and ReadResourceResult.  Explicitly
    NOT cacheable: CallToolResult, GetPromptResult, CompleteResult,
    InputRequiredResult, SubscriptionsListenResult.
    """

    ttl_ms: int = Field(alias="ttlMs", ge=0)
    cache_scope: Literal["public", "private"] = Field(alias="cacheScope")


class PaginatedCacheableResult(CacheableResult):
    """CacheableResult + opaque pagination cursor (the list results)."""

    next_cursor: str | None = Field(default=None, alias="nextCursor")


# ---------------------------------------------------------------------------
# server/discover (SEP-2575) — the replacement for initialize
# ---------------------------------------------------------------------------


class DiscoverResult(CacheableResult):
    """Result of ``server/discover`` — servers MUST implement the method.

    Unlike initialize, discover is OPTIONAL for clients: any request can be
    sent inline and version mismatches surface as -32022 with the supported
    list.  Discover exists so clients can select a version and read
    capabilities/instructions up front, and it is cacheable (a big win over
    initialize, which was per-session by construction).
    """

    supported_versions: list[str] = Field(alias="supportedVersions")
    capabilities: ServerCapabilities
    server_info: Implementation = Field(alias="serverInfo")
    #: Natural-language guidance for the LLM (may go into a system prompt);
    #: should not duplicate individual tool descriptions.
    instructions: str | None = None


# ---------------------------------------------------------------------------
# Annotations (display metadata on resources/content)
# ---------------------------------------------------------------------------


class Annotations(WireModel):
    audience: list[Literal["user", "assistant"]] | None = None
    priority: float | None = Field(default=None, ge=0.0, le=1.0)
    last_modified: str | None = Field(default=None, alias="lastModified")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class ToolAnnotations(WireModel):
    """Behavior HINTS about a tool — untrusted by definition.

    Clients use them for UX (confirmation prompts, display precedence
    title -> annotations.title -> name), never for security decisions.
    """

    title: str | None = None
    read_only_hint: bool | None = Field(default=None, alias="readOnlyHint")
    destructive_hint: bool | None = Field(default=None, alias="destructiveHint")
    idempotent_hint: bool | None = Field(default=None, alias="idempotentHint")
    open_world_hint: bool | None = Field(default=None, alias="openWorldHint")


class Tool(WireModel):
    """A callable tool definition (schema ``Tool``).

    2026-07-28 loosened ``inputSchema`` to FULL JSON Schema 2020-12
    (SEP-2106) — any keyword is allowed, though the root must still be
    ``type: "object"``.  Property schemas may carry the ``x-mcp-header``
    annotation (SEP-2243) telling Streamable HTTP clients to mirror an
    argument into an ``Mcp-Param-{Name}`` header.  We keep the schema as a
    plain dict: validating tool schemas is the registry's job, not the
    wire type's.
    """

    name: str
    title: str | None = None
    description: str | None = None
    input_schema: dict[str, Any] = Field(alias="inputSchema")
    output_schema: dict[str, Any] | None = Field(default=None, alias="outputSchema")
    annotations: ToolAnnotations | None = None
    icons: list[Icon] | None = None
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


class Resource(WireModel):
    uri: str
    name: str
    title: str | None = None
    description: str | None = None
    mime_type: str | None = Field(default=None, alias="mimeType")
    size: int | None = None
    annotations: Annotations | None = None
    icons: list[Icon] | None = None
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


class ResourceTemplate(WireModel):
    """A parameterized resource (RFC 6570 URI template, level 1)."""

    uri_template: str = Field(alias="uriTemplate")
    name: str
    title: str | None = None
    description: str | None = None
    mime_type: str | None = Field(default=None, alias="mimeType")
    annotations: Annotations | None = None
    icons: list[Icon] | None = None
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


class TextResourceContents(WireModel):
    uri: str
    mime_type: str | None = Field(default=None, alias="mimeType")
    text: str
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


class BlobResourceContents(WireModel):
    uri: str
    mime_type: str | None = Field(default=None, alias="mimeType")
    #: base64-encoded binary payload.
    blob: str
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


ResourceContents = TextResourceContents | BlobResourceContents


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


class PromptArgument(WireModel):
    name: str
    title: str | None = None
    description: str | None = None
    required: bool | None = None


class Prompt(WireModel):
    name: str
    title: str | None = None
    description: str | None = None
    arguments: list[PromptArgument] | None = None
    icons: list[Icon] | None = None
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


# ---------------------------------------------------------------------------
# Content blocks (discriminated on "type", exactly like the schema union)
# ---------------------------------------------------------------------------


class TextContent(WireModel):
    type: Literal["text"] = "text"
    text: str
    annotations: Annotations | None = None
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


class ImageContent(WireModel):
    type: Literal["image"] = "image"
    #: base64-encoded image data.
    data: str
    mime_type: str = Field(alias="mimeType")
    annotations: Annotations | None = None
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


class AudioContent(WireModel):
    type: Literal["audio"] = "audio"
    #: base64-encoded audio data.
    data: str
    mime_type: str = Field(alias="mimeType")
    annotations: Annotations | None = None
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


class ResourceLink(WireModel):
    """A reference to a resource, delivered inline as tool-result content."""

    type: Literal["resource_link"] = "resource_link"
    uri: str
    name: str
    title: str | None = None
    description: str | None = None
    mime_type: str | None = Field(default=None, alias="mimeType")
    size: int | None = None
    annotations: Annotations | None = None
    icons: list[Icon] | None = None
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


class EmbeddedResource(WireModel):
    """Resource contents embedded directly in a message."""

    type: Literal["resource"] = "resource"
    resource: TextResourceContents | BlobResourceContents
    annotations: Annotations | None = None
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


ContentBlock = Annotated[
    TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Sampling content (superset used inside sampling/createMessage; SEP-1577
# added tool_use/tool_result blocks).  All sampling types are deprecated as
# of 2026-07-28 (SEP-2577) but remain functional for >= 12 months.
# ---------------------------------------------------------------------------


class ToolUseContent(WireModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


class ToolResultContent(WireModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str = Field(alias="toolUseId")
    content: list[ContentBlock] | None = None
    structured_content: Any = Field(default=None, alias="structuredContent")
    is_error: bool | None = Field(default=None, alias="isError")
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


SamplingContent = Annotated[
    TextContent | ImageContent | AudioContent | ToolUseContent | ToolResultContent,
    Field(discriminator="type"),
]


class SamplingMessage(WireModel):
    role: Literal["user", "assistant"]
    content: SamplingContent | list[SamplingContent]


class ModelHint(WireModel):
    name: str | None = None


class ModelPreferences(WireModel):
    """Model-selection HINTS: the client maps them to models it has."""

    hints: list[ModelHint] | None = None
    cost_priority: float | None = Field(default=None, alias="costPriority", ge=0.0, le=1.0)
    speed_priority: float | None = Field(default=None, alias="speedPriority", ge=0.0, le=1.0)
    intelligence_priority: float | None = Field(
        default=None, alias="intelligencePriority", ge=0.0, le=1.0
    )


class SamplingTool(WireModel):
    """A tool definition offered to the client-side LLM (SEP-1577)."""

    name: str
    description: str | None = None
    input_schema: dict[str, Any] = Field(alias="inputSchema")


class CreateMessageRequestParams(WireModel):
    """Params of an embedded ``sampling/createMessage`` InputRequest.

    Deprecated as of 2026-07-28 (SEP-2577): the recommended migration is to
    call LLM provider APIs directly.  ``includeContext`` values "thisServer"
    and "allServers" are additionally deprecated — servers SHOULD send
    "none" or omit the field.
    """

    messages: list[SamplingMessage]
    max_tokens: int = Field(alias="maxTokens")
    model_preferences: ModelPreferences | None = Field(default=None, alias="modelPreferences")
    system_prompt: str | None = Field(default=None, alias="systemPrompt")
    include_context: Literal["none", "thisServer", "allServers"] | None = Field(
        default=None, alias="includeContext"
    )
    temperature: float | None = None
    stop_sequences: list[str] | None = Field(default=None, alias="stopSequences")
    metadata: dict[str, Any] | None = None
    tools: list[SamplingTool] | None = None
    tool_choice: dict[str, Any] | None = Field(default=None, alias="toolChoice")


class CreateMessageRequest(WireModel):
    """An embedded ``sampling/createMessage`` InputRequest (plain
    method+params object — NOT a JSON-RPC request).  Deprecated (SEP-2577)."""

    method: Literal["sampling/createMessage"] = "sampling/createMessage"
    params: CreateMessageRequestParams


class CreateMessageResult(WireModel):
    """Client's completion answer, embedded in ``inputResponses``.

    NOTE: this is NOT a top-level JSON-RPC result — it does not extend
    ``Result`` and carries no ``resultType``.  It only ever appears inside
    the retry request's ``inputResponses`` map (MRTR, SEP-2322).
    """

    role: Literal["user", "assistant"]
    content: SamplingContent | list[SamplingContent]
    model: str
    #: Open union: "endTurn" | "stopSequence" | "maxTokens" | "toolUse" | ...
    stop_reason: str | None = Field(default=None, alias="stopReason")


# ---------------------------------------------------------------------------
# Elicitation (form + url modes)
# ---------------------------------------------------------------------------


class ElicitRequestFormParams(WireModel):
    """Form-mode elicitation: ``mode`` is optional because form is default.

    ``requestedSchema`` is a RESTRICTED JSON Schema subset — a flat object of
    primitive-typed properties (string/number/boolean/enum), no nesting.  We
    keep it as a dict; the ModernContext helper is responsible for producing
    conforming schemas.
    """

    mode: Literal["form"] | None = None
    message: str
    requested_schema: dict[str, Any] = Field(alias="requestedSchema")


class ElicitRequestURLParams(WireModel):
    """URL-mode elicitation: send the user to an external URL (e.g. OAuth)."""

    mode: Literal["url"]
    message: str
    url: str


ElicitRequestParams = ElicitRequestURLParams | ElicitRequestFormParams


class ElicitRequest(WireModel):
    """An embedded ``elicitation/create`` InputRequest (plain method+params
    object — NOT a JSON-RPC request; it has no ``jsonrpc`` or ``id``)."""

    method: Literal["elicitation/create"] = "elicitation/create"
    params: ElicitRequestParams


class ElicitResult(WireModel):
    """Client's answer to an elicitation, embedded in ``inputResponses``.

    ``content`` is present only when ``action == "accept"`` AND the mode was
    "form" (URL-mode results are delivered out of band).  Values are
    restricted by the spec to string | number | boolean | string[].
    """

    action: Literal["accept", "decline", "cancel"]
    content: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Roots — deprecated as of 2026-07-28 by SEP-2577
# ---------------------------------------------------------------------------


class Root(WireModel):
    uri: str
    name: str | None = None
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


class ListRootsRequest(WireModel):
    """An embedded ``roots/list`` InputRequest.  Deprecated (SEP-2577)."""

    method: Literal["roots/list"] = "roots/list"
    params: dict[str, Any] | None = None


class ListRootsResult(WireModel):
    """Client's roots answer — an InputResponse, so no ``resultType``."""

    roots: list[Root]


# ---------------------------------------------------------------------------
# MRTR — InputRequiredResult, per SEP-2322
# ---------------------------------------------------------------------------

#: The three request shapes a server may embed.  Discriminated on "method",
#: mirroring the schema's InputRequest union.
InputRequest = Annotated[
    CreateMessageRequest | ListRootsRequest | ElicitRequest,
    Field(discriminator="method"),
]


class InputRequiredResult(Result):
    """The server's "I need more input" reply (MRTR, SEP-2322).

    Returned ONLY from tools/call, prompts/get, and resources/read.  At least
    one of ``inputRequests``/``requestState`` MUST be present.  The client
    fulfills each embedded request, then RETRIES the original request (with a
    NEW JSON-RPC id) carrying ``inputResponses`` keyed identically and
    echoing ``requestState`` verbatim.  ``requestState`` is opaque to the
    client and attacker-controlled from the server's perspective — the
    server MUST integrity-protect it if it influences anything that matters
    (see modern/mrtr.py for the HMAC codec).
    """

    result_type: str = Field(default=RESULT_INPUT_REQUIRED, alias="resultType")
    input_requests: dict[str, InputRequest] | None = Field(default=None, alias="inputRequests")
    request_state: str | None = Field(default=None, alias="requestState")


# ---------------------------------------------------------------------------
# Concrete results
# ---------------------------------------------------------------------------


class CallToolResult(Result):
    """tools/call success result.  NOT cacheable (tools have side effects).

    Tool-originated failures ride IN the result with ``isError: true`` so
    the LLM can see them and self-correct; protocol-level failures (unknown
    tool, invalid params) are JSON-RPC errors instead.
    """

    content: list[ContentBlock] = Field(default_factory=list)
    structured_content: Any = Field(default=None, alias="structuredContent")
    is_error: bool | None = Field(default=None, alias="isError")


class ListToolsResult(PaginatedCacheableResult):
    tools: list[Tool]


class ListResourcesResult(PaginatedCacheableResult):
    resources: list[Resource]


class ListResourceTemplatesResult(PaginatedCacheableResult):
    resource_templates: list[ResourceTemplate] = Field(alias="resourceTemplates")


class ListPromptsResult(PaginatedCacheableResult):
    prompts: list[Prompt]


class ReadResourceResult(CacheableResult):
    contents: list[TextResourceContents | BlobResourceContents]


class PromptMessage(WireModel):
    role: Literal["user", "assistant"]
    content: ContentBlock


class GetPromptResult(Result):
    """prompts/get result — NOT cacheable (prompts render per-arguments)."""

    description: str | None = None
    messages: list[PromptMessage]


class Completion(WireModel):
    values: list[str]
    total: int | None = None
    has_more: bool | None = Field(default=None, alias="hasMore")


class CompleteResult(Result):
    # NOT a CacheableResult: SEP-2549 excludes completion/complete from the
    # methods that carry ttlMs/cacheScope (like prompts/get and tools/call).
    completion: Completion


# ---------------------------------------------------------------------------
# Subscriptions — SEP-2575
# ---------------------------------------------------------------------------


class SubscriptionFilter(WireModel):
    """What a ``subscriptions/listen`` stream should carry — strictly opt-in.

    The server MUST NOT deliver notification types the client did not
    request, and acknowledges the subset it actually honors in
    ``notifications/subscriptions/acknowledged`` (the first stream event).
    ``resourceSubscriptions`` replaces the removed resources/subscribe RPC:
    the client lists exact URIs it wants ``notifications/resources/updated``
    for.
    """

    tools_list_changed: bool | None = Field(default=None, alias="toolsListChanged")
    prompts_list_changed: bool | None = Field(default=None, alias="promptsListChanged")
    resources_list_changed: bool | None = Field(default=None, alias="resourcesListChanged")
    resource_subscriptions: list[str] | None = Field(default=None, alias="resourceSubscriptions")


# ---------------------------------------------------------------------------
# JSON-RPC envelope helpers
# ---------------------------------------------------------------------------


def complete_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Return ``payload`` with ``resultType`` guaranteed present.

    Servers on 2026-07-28 MUST include ``resultType`` on every result
    (SEP-2322).  This helper is the last line of defense for handlers that
    build plain dicts: it defaults an absent field to "complete" but never
    overrides an explicit value (e.g. "input_required").
    """
    result = dict(payload)
    result.setdefault("resultType", RESULT_COMPLETE)
    return result


def error_response(
    request_id: str | int | None,
    code: int,
    message: str,
    data: Any = None,
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 error response object.

    ``request_id`` may be None only when the id could not be read from a
    malformed request — the schema's JSONRPCErrorResponse marks ``id`` as
    optional for exactly that case, and we OMIT the key rather than send
    ``"id": null`` (request ids must never be null in MCP).
    """
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    response: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "error": error}
    if request_id is not None:
        response["id"] = request_id
    return response
