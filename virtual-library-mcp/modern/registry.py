"""
ModernRegistry — the 2026-07-28 view of the SAME library the FastMCP app
serves.

Global decision #3 of this project: domain logic is shared between eras.
The tools, resources, and prompts are plain typed Python functions declared
once (tools/__init__.py TOOL_SPECS, resources/__init__.py _RESOURCE_GROUPS,
prompts/__init__.py PROMPT_SPECS); FastMCP registers them for the legacy
era, and this registry re-derives the modern era from the very same
objects.  Nothing is duplicated — which is the point: a protocol revision
changes the WIRE, not the domain.

What the registry owns:

- **Schema derivation.**  Tool input/output schemas come from
  ``fastmcp.tools.Tool.from_function`` — the same machinery the legacy era
  uses, so both eras publish byte-identical schemas for each tool.
  EXECUTION, however, is ours: 2026-07-28 requests carry per-request
  ``_meta`` and MRTR memos that FastMCP's session-era plumbing knows
  nothing about, so we validate arguments (JSON Schema structural check +
  pydantic coercion from the signature's type hints) and call the function
  with a :class:`~modern.context.ModernContext` injected where the
  signature asks for a ``ctx``.

- **Deterministic ordering (spec SHOULD).**  Every list is name-sorted.
  Stable ordering is what makes list results cacheable in practice — same
  bytes -> same intermediary cache entry -> LLM prompt-cache hits.

- **Visibility.**  ``disable(names)`` / ``reset_visibility()`` implement
  maintenance mode (see tools/catalog_maintenance.py): hidden components
  vanish from list results, and ``on_list_changed`` fires so the broker can
  push ``notifications/*/list_changed`` to subscribed listen streams.
  NOTE the statelessness rule this respects: lists MUST NOT vary
  per-connection — visibility here is global server state (one library,
  one maintenance mode), not a session veneer.

- **Providers and method extensions.**  ``add_resource_provider`` lets the
  skills package (SEP-2640) contribute ``skill://`` resources without this
  module knowing what a skill is; ``add_method`` lets the tasks extension
  (SEP-2663) add ``tasks/*`` RPCs the dispatcher consults before declaring
  -32601.  Both feed capability fragments into ``ServerCapabilities.
  extensions`` — the modern, namespaced way to advertise non-core features.

- **Completions.**  ``completion/complete`` for prompt arguments and
  resource-template variables, hand-wired to real data: genres come from a
  live DISTINCT query, patron statuses from the domain enum, ISBNs from
  prefix search.  Completion results are ranked, capped at 100 (spec), and
  deterministic.

Spec: MCP 2026-07-28 server/{tools,resources,prompts}, server/utilities/
completion, SEP-2549 (caching -> the ListCachePolicy knobs live here),
SEP-2106 (full JSON Schema 2020-12 tool schemas).
"""

import inspect
import json
import logging
import re
import typing
import urllib.parse
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

import jsonschema
from fastmcp.exceptions import ResourceError, ToolError
from fastmcp.tools import Tool as FastMCPTool
from fastmcp.tools import ToolResult as FastMCPToolResult
from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy import select

from database.schema import Book as BookDB
from database.session import session_scope
from models.patron import PatronStatus
from modern.context import ModernContext
from modern.errors import InvalidParamsError, McpError
from modern.meta import RequestMeta
from modern.types import (
    BlobResourceContents,
    Prompt,
    PromptArgument,
    PromptsCapability,
    Resource,
    ResourcesCapability,
    ResourceTemplate,
    ServerCapabilities,
    TextResourceContents,
    Tool,
    ToolsCapability,
)

logger = logging.getLogger(__name__)

#: Handler signature for method extensions (tasks/get etc.): raw params in,
#: parsed RequestMeta in (for per-request capability gating), result dict out.
MethodHandler = Callable[[dict[str, Any], RequestMeta], Awaitable[dict[str, Any]]]

#: Completion values are capped by the spec: "values ... max 100".
_MAX_COMPLETION_VALUES = 100


@dataclass(frozen=True)
class ListCachePolicy:
    """The SEP-2549 caching knobs for list/read results.

    ``ttl_ms`` is the freshness hint (Cache-Control max-age analog);
    ``cache_scope`` MUST be "private" whenever results could differ per
    authorization context — the integrator passes "private" when auth is
    enabled and "public" otherwise.
    """

    ttl_ms: int = 300_000
    cache_scope: Literal["public", "private"] = "public"


@runtime_checkable
class ResourceProvider(Protocol):
    """The pluggable resource namespace contract (used by modern/skills.py).

    ``directory_read`` returns None for URIs outside the provider's
    namespace so the registry can consult the next provider.
    """

    def matches(self, uri: str) -> bool: ...

    async def read(self, uri: str) -> list[TextResourceContents | BlobResourceContents]: ...

    async def directory_read(self, uri: str) -> list[Resource] | None: ...

    def list_entries(self) -> list[Resource]: ...

    def capability_fragment(self) -> dict[str, dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# Internal entries — the registry's compiled view of the declarative specs
# ---------------------------------------------------------------------------


@dataclass
class _ToolEntry:
    definition: Tool
    fn: Callable[..., Awaitable[Any]]
    ctx_param: str | None
    validator: jsonschema.protocols.Validator
    coercers: dict[str, TypeAdapter[Any]]
    wrap_result: bool


@dataclass
class _ResourceEntry:
    definition: Resource
    handler: Callable[..., Awaitable[dict[str, Any]]]
    mime_type: str


@dataclass
class _TemplateEntry:
    definition: ResourceTemplate
    handler: Callable[..., Awaitable[dict[str, Any]]]
    mime_type: str
    pattern: re.Pattern[str]
    variables: tuple[str, ...]


@dataclass
class _PromptEntry:
    definition: Prompt
    fn: Callable[..., Awaitable[str]]
    coercers: dict[str, TypeAdapter[Any]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# {var} template matching — RFC 6570 level 1, which is all our URIs use
# ---------------------------------------------------------------------------

_TEMPLATE_VAR = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def compile_uri_template(template: str) -> tuple[re.Pattern[str], tuple[str, ...]]:
    """Turn ``library://books/{isbn}`` into a regex + variable names.

    RFC 6570 level 1: simple string expansion only.  Each ``{var}`` matches
    one path segment (no ``/``), everything else matches literally.  This
    replaces the dead resources/uri_utils.py with the minimal thing the
    catalog actually needs.
    """
    names: list[str] = []
    parts: list[str] = []
    last = 0
    for match in _TEMPLATE_VAR.finditer(template):
        parts.append(re.escape(template[last : match.start()]))
        names.append(match.group(1))
        parts.append(r"([^/]+)")
        last = match.end()
    parts.append(re.escape(template[last:]))
    return re.compile("^" + "".join(parts) + "$"), tuple(names)


# ---------------------------------------------------------------------------
# Conversion helpers (fastmcp metadata objects -> modern wire models)
# ---------------------------------------------------------------------------


def _dump(model: Any) -> dict[str, Any]:
    """model_dump with wire aliases — works for mcp.types and fastmcp models."""
    return model.model_dump(by_alias=True, exclude_none=True, mode="json")


def _param_coercers(fn: Callable[..., Any], *, skip: set[str]) -> dict[str, TypeAdapter[Any]]:
    """One pydantic TypeAdapter per parameter, from the signature's hints.

    JSON gives us strings/numbers; the functions want ``date``, ``Literal``,
    constrained ints...  In the legacy era FastMCP validates arguments
    through a synthesized pydantic model; we reproduce that with per-param
    adapters so e.g. ``"2026-08-01"`` really becomes a ``datetime.date``
    before the handler compares it to ``date.today()``.
    """
    coercers: dict[str, TypeAdapter[Any]] = {}
    try:
        hints = typing.get_type_hints(fn, include_extras=True)
    except Exception:
        return coercers
    for name in inspect.signature(fn).parameters:
        if name in skip:
            continue
        hint = hints.get(name)
        if hint is not None:
            coercers[name] = TypeAdapter(hint)
    return coercers


def _find_ctx_param(fn: Callable[..., Any]) -> str | None:
    """Which parameter (if any) receives the context object?

    Convention in this codebase: the parameter is named ``ctx`` and
    annotated with FastMCP's Context.  We match on the name — annotations
    may be strings under future imports, and the modern context is a duck
    type, not a subclass.
    """
    for name in inspect.signature(fn).parameters:
        if name == "ctx":
            return name
    return None


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


class ModernRegistry:
    """Builds once at startup; serves every list/call/read/get thereafter."""

    def __init__(
        self,
        *,
        tool_specs: Iterable[Any] | None = None,
        resource_groups: Iterable[tuple[Any, Any, Any]] | None = None,
        prompt_specs: Iterable[Any] | None = None,
    ) -> None:
        # Default to the shared declarative tables.  Imported lazily so a
        # test can hand in tiny synthetic spec lists without touching the
        # real database-backed handlers.
        if tool_specs is None or resource_groups is None or prompt_specs is None:
            from prompts import PROMPT_SPECS
            from resources import _RESOURCE_GROUPS
            from tools import TOOL_SPECS

            tool_specs = TOOL_SPECS if tool_specs is None else tool_specs
            resource_groups = _RESOURCE_GROUPS if resource_groups is None else resource_groups
            prompt_specs = PROMPT_SPECS if prompt_specs is None else prompt_specs

        self._tools: dict[str, _ToolEntry] = {}
        for spec in tool_specs:
            entry = self._compile_tool(spec)
            self._tools[entry.definition.name] = entry

        self._resources: dict[str, _ResourceEntry] = {}
        self._templates: list[_TemplateEntry] = []
        for definitions, icon, _tags in resource_groups:
            for definition in definitions:
                self._compile_resource(definition, icon)

        self._prompts: dict[str, _PromptEntry] = {}
        for spec in prompt_specs:
            entry = self._compile_prompt(spec)
            self._prompts[entry.definition.name] = entry

        #: Pluggable resource namespaces (skills).  Consulted by uri prefix.
        self.resource_providers: list[ResourceProvider] = []
        #: Extension RPCs (tasks/*) the dispatcher consults before -32601.
        self.extension_methods: dict[str, MethodHandler] = {}
        #: Extra ServerCapabilities.extensions fragments (e.g. from the
        #: tasks extension, whose methods carry no provider object).
        self._extension_capabilities: dict[str, dict[str, Any]] = {}

        #: Hidden component names, per kind ("tool"/"resource"/"template"/
        #: "prompt").  Names are DISPLAY names — matching what FastMCP's
        #: disable_components(names=...) selector uses.
        self._disabled: dict[str, set[str]] = {}
        #: Wired by the integrator to broker.publish_list_changed; called
        #: with the protocol list kind ("tools" | "resources" | "prompts").
        self.on_list_changed: Callable[[str], None] | None = None

    # -- compilation --------------------------------------------------------

    def _compile_tool(self, spec: Any) -> _ToolEntry:
        # Same derivation the legacy era uses -> byte-identical schemas.
        derived = FastMCPTool.from_function(spec.fn, name=spec.name)
        input_schema: dict[str, Any] = derived.parameters
        output_schema: dict[str, Any] | None = derived.output_schema
        wrap_result = bool(output_schema and output_schema.get("x-fastmcp-wrap-result"))
        definition = Tool(
            name=spec.name,
            title=getattr(spec.annotations, "title", None),
            description=derived.description,
            input_schema=input_schema,
            output_schema=output_schema,
            annotations=_dump(spec.annotations) if spec.annotations is not None else None,
            icons=[_dump(icon) for icon in spec.icons] or None,
        )
        ctx_param = _find_ctx_param(spec.fn)
        skip = {ctx_param} if ctx_param else set()
        return _ToolEntry(
            definition=definition,
            fn=spec.fn,
            ctx_param=ctx_param,
            # 2020-12 is the default dialect when $schema is absent (SEP-2106).
            validator=jsonschema.Draft202012Validator(input_schema),
            coercers=_param_coercers(spec.fn, skip=skip),
            wrap_result=wrap_result,
        )

    def _compile_resource(self, definition: dict[str, Any], icon: Any) -> None:
        mime_type = definition["mime_type"]
        common = {
            "name": definition["name"],
            "description": definition["description"],
            "mime_type": mime_type,
            "icons": [_dump(icon)],
        }
        if "uri_template" in definition and definition.get("uri_template"):
            template = definition["uri_template"]
            pattern, variables = compile_uri_template(template)
            self._templates.append(
                _TemplateEntry(
                    definition=ResourceTemplate(uri_template=template, **common),
                    handler=definition["handler"],
                    mime_type=mime_type,
                    pattern=pattern,
                    variables=variables,
                )
            )
        else:
            uri = definition["uri"]
            self._resources[uri] = _ResourceEntry(
                definition=Resource(uri=uri, **common),
                handler=definition["handler"],
                mime_type=mime_type,
            )

    def _compile_prompt(self, spec: Any) -> _PromptEntry:
        arguments = [
            PromptArgument(name=a.name, description=a.description, required=a.required)
            for a in spec.arguments
        ]
        definition = Prompt(
            name=spec.name,
            description=spec.description,
            arguments=arguments or None,
            icons=[_dump(icon) for icon in spec.icons] or None,
        )
        declared = {a.name for a in spec.arguments}
        coercers = {
            name: adapter
            for name, adapter in _param_coercers(spec.fn, skip=set()).items()
            if name in declared
        }
        return _PromptEntry(definition=definition, fn=spec.fn, coercers=coercers)

    # -- visibility ----------------------------------------------------------

    #: FastMCP component kind -> which protocol list it affects.
    _KIND_TO_LIST = {
        "tool": "tools",
        "resource": "resources",
        "template": "resources",
        "prompt": "prompts",
    }

    def disable(self, names: Iterable[str], kinds: Iterable[str] | None = None) -> None:
        """Hide components by display name (maintenance mode).

        ``kinds`` narrows to component kinds ("tool"/"resource"/"template"/
        "prompt"); None hides matching names of every kind.  Fires
        ``on_list_changed`` once per affected protocol list so subscribed
        clients can drop their caches (SEP-2549: a relevant notification
        invalidates a fresh cache immediately).
        """
        names = set(names)
        selected = set(kinds) if kinds is not None else set(self._KIND_TO_LIST)
        changed: set[str] = set()
        for kind in selected:
            existing = self._names_of_kind(kind)
            hits = names & existing
            if hits:
                self._disabled.setdefault(kind, set()).update(hits)
                changed.add(self._KIND_TO_LIST[kind])
        for list_kind in sorted(changed):
            self._fire_list_changed(list_kind)

    def reset_visibility(self) -> None:
        """Re-show everything; fires list_changed for lists that recover."""
        changed = {self._KIND_TO_LIST[kind] for kind, names in self._disabled.items() if names}
        self._disabled.clear()
        for list_kind in sorted(changed):
            self._fire_list_changed(list_kind)

    def _names_of_kind(self, kind: str) -> set[str]:
        if kind == "tool":
            return {e.definition.name for e in self._tools.values()}
        if kind == "resource":
            return {e.definition.name for e in self._resources.values()}
        if kind == "template":
            return {e.definition.name for e in self._templates}
        if kind == "prompt":
            return {e.definition.name for e in self._prompts.values()}
        return set()

    def _is_disabled(self, kind: str, name: str) -> bool:
        return name in self._disabled.get(kind, set())

    def _fire_list_changed(self, list_kind: str) -> None:
        if self.on_list_changed is not None:
            self.on_list_changed(list_kind)

    # -- extension hooks -----------------------------------------------------

    def add_resource_provider(self, provider: ResourceProvider) -> None:
        self.resource_providers.append(provider)

    def add_method(
        self,
        name: str,
        handler: MethodHandler,
        capability_fragment: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Register an extension RPC (consulted by the dispatcher pre-404)."""
        self.extension_methods[name] = handler
        if capability_fragment:
            self._extension_capabilities.update(capability_fragment)

    def add_extension_capabilities(self, fragment: dict[str, dict[str, Any]]) -> None:
        """Merge a capability fragment into ServerCapabilities.extensions."""
        self._extension_capabilities.update(fragment)

    # -- capabilities --------------------------------------------------------

    def capabilities(self) -> ServerCapabilities:
        """What server/discover advertises.

        ``listChanged``/``subscribe`` survive from the legacy shape but now
        describe what a ``subscriptions/listen`` stream can carry.
        ``logging`` is declared because we still emit notifications/message
        for requests that opt in via ``_meta`` logLevel — deprecated
        (SEP-2577) but functional through the migration window.
        """
        extensions: dict[str, dict[str, Any]] = {}
        for provider in self.resource_providers:
            extensions.update(provider.capability_fragment())
        extensions.update(self._extension_capabilities)
        return ServerCapabilities(
            tools=ToolsCapability(list_changed=True),
            resources=ResourcesCapability(subscribe=True, list_changed=True),
            prompts=PromptsCapability(list_changed=True),
            completions={},
            logging={},
            extensions=extensions or None,
        )

    # -- lists (deterministic name-sorted order, spec SHOULD) ----------------

    def list_tools(self) -> list[Tool]:
        return sorted(
            (
                e.definition
                for e in self._tools.values()
                if not self._is_disabled("tool", e.definition.name)
            ),
            key=lambda t: t.name,
        )

    def list_resources(self) -> list[Resource]:
        own = (
            e.definition
            for e in self._resources.values()
            if not self._is_disabled("resource", e.definition.name)
        )
        contributed = (r for p in self.resource_providers for r in p.list_entries())
        return sorted([*own, *contributed], key=lambda r: r.name)

    def list_resource_templates(self) -> list[ResourceTemplate]:
        return sorted(
            (
                e.definition
                for e in self._templates
                if not self._is_disabled("template", e.definition.name)
            ),
            key=lambda t: t.name,
        )

    def list_prompts(self) -> list[Prompt]:
        return sorted(
            (
                e.definition
                for e in self._prompts.values()
                if not self._is_disabled("prompt", e.definition.name)
            ),
            key=lambda p: p.name,
        )

    def has_tool(self, name: str) -> bool:
        return name in self._tools and not self._is_disabled("tool", name)

    def tool_input_schema(self, name: str) -> dict[str, Any] | None:
        """Published inputSchema for a tool, or None if unknown.

        The HTTP layer needs this to recognize x-mcp-header annotations
        (SEP-2243) when validating Mcp-Param-* request headers, without
        importing registry internals.
        """
        entry = self._tools.get(name)
        return entry.definition.input_schema if entry else None

    # -- tools/call execution -------------------------------------------------

    async def call_tool(
        self, name: str, arguments: dict[str, Any], ctx: ModernContext
    ) -> dict[str, Any]:
        """Validate, execute, convert — the modern tools/call body.

        Error taxonomy (spec server/tools):
        - unknown tool / invalid arguments -> JSON-RPC ``-32602`` (protocol
          error; raised, handled by the dispatcher);
        - tool EXECUTION failures -> ``isError: true`` INSIDE a complete
          result, so the calling LLM can read the message and self-correct;
        - InputRequiredInterrupt (BaseException) passes through untouched —
          it belongs to the MRTR engine, not to error handling.
        """
        entry = self._tools.get(name)
        if entry is None or self._is_disabled("tool", name):
            raise InvalidParamsError(f"Unknown tool: {name}")

        # Structural validation against the published inputSchema: unknown
        # properties, missing required fields, wrong JSON types.
        errors = sorted(entry.validator.iter_errors(arguments), key=lambda e: str(e.path))
        if errors:
            first = errors[0]
            location = "/".join(str(p) for p in first.path) or "(root)"
            raise InvalidParamsError(
                f"Invalid arguments for tool '{name}': {first.message} at {location}"
            )

        # Type coercion from the signature (JSON string -> date, etc.),
        # mirroring the legacy era's pydantic conversion.
        kwargs: dict[str, Any] = {}
        for key, value in arguments.items():
            adapter = entry.coercers.get(key)
            if adapter is None:
                kwargs[key] = value
                continue
            try:
                kwargs[key] = adapter.validate_python(value)
            except ValidationError as exc:
                raise InvalidParamsError(
                    f"Invalid arguments for tool '{name}': parameter {key!r} — "
                    f"{exc.errors()[0].get('msg', 'validation failed')}"
                ) from exc
        if entry.ctx_param is not None:
            kwargs[entry.ctx_param] = ctx

        try:
            value = await entry.fn(**kwargs)
        except McpError:
            # Protocol errors raised from the context (e.g. -32021 missing
            # client capability) belong on the wire as JSON-RPC errors, not
            # wrapped into tool results.
            raise
        except ToolError as exc:
            # SEP-1303 semantics carried forward: business-rule violations
            # are results the model can see, not opaque protocol errors.
            return {
                "resultType": "complete",
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True,
            }
        except Exception:
            # Unexpected failure: masked message (never leak internals to
            # the wire — spec security guideline), full details to the log.
            logger.exception("Unhandled error executing tool %s", name)
            return {
                "resultType": "complete",
                "content": [{"type": "text", "text": f"Error executing tool {name!r}"}],
                "isError": True,
            }

        return self._convert_tool_result(entry, value)

    def _convert_tool_result(self, entry: _ToolEntry, value: Any) -> dict[str, Any]:
        """Handler return value -> CallToolResult wire dict.

        Structured results double-serialize on purpose (spec SHOULD): the
        JSON rides in ``structuredContent`` for machines AND in a text block
        for clients that only render content.
        """
        structured: Any = None
        is_error = False

        if isinstance(value, FastMCPToolResult):
            content = [_dump(block) for block in value.content]
            structured = value.structured_content
            is_error = value.is_error
        elif isinstance(value, BaseModel):
            structured = value.model_dump(mode="json")
            content = [{"type": "text", "text": json.dumps(structured, indent=2, default=str)}]
        elif isinstance(value, str):
            content = [{"type": "text", "text": value}]
            if entry.wrap_result:
                # FastMCP derives {"result": <T>} outputSchemas for scalar
                # returns; structuredContent must match the published schema.
                structured = {"result": value}
        else:
            jsonable = json.loads(json.dumps(value, default=str))
            structured = {"result": jsonable} if entry.wrap_result else jsonable
            content = [{"type": "text", "text": json.dumps(jsonable, indent=2, default=str)}]

        result: dict[str, Any] = {"resultType": "complete", "content": content}
        if structured is not None:
            result["structuredContent"] = structured
        if is_error:
            result["isError"] = True
        return result

    # -- resources/read ------------------------------------------------------

    async def read_resource(self, uri: str, ctx: ModernContext) -> list[dict[str, Any]]:
        """Resolve a URI to contents: static -> template -> providers.

        ``ctx`` is accepted for parity (resource handlers COULD elicit via
        MRTR — the method supports it) though the current catalog handlers
        take only URI variables.
        """
        del ctx  # current handlers take no context; kept for MRTR parity
        entry = self._resources.get(uri)
        if entry is not None and not self._is_disabled("resource", entry.definition.name):
            return await self._invoke_resource(uri, entry.mime_type, entry.handler)

        for template in self._templates:
            if self._is_disabled("template", template.definition.name):
                continue
            match = template.pattern.match(uri)
            if match is None:
                continue
            # Percent-decoding: URI variables arrive percent-encoded per
            # RFC 6570 expansion; the handlers expect the decoded value.
            variables = {
                name: urllib.parse.unquote(value)
                for name, value in zip(template.variables, match.groups(), strict=True)
            }
            return await self._invoke_resource(uri, template.mime_type, template.handler, variables)

        for provider in self.resource_providers:
            if provider.matches(uri):
                return [contents.to_wire() for contents in await provider.read(uri)]

        # Modern error mapping: resource-not-found is -32602 (the legacy
        # -32002 is retired and MUST NOT be emitted).
        raise InvalidParamsError("Resource not found", data={"uri": uri})

    async def _invoke_resource(
        self,
        uri: str,
        mime_type: str,
        handler: Callable[..., Awaitable[dict[str, Any]]],
        variables: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            value = await handler(**(variables or {}))
        except ResourceError as exc:
            # The shared handlers signal both not-found and internal trouble
            # via ResourceError; the modern taxonomy folds resource failures
            # into -32602 with the message intact.
            raise InvalidParamsError(str(exc), data={"uri": uri}) from exc
        text = value if isinstance(value, str) else json.dumps(value, indent=2, default=str)
        return [TextResourceContents(uri=uri, mime_type=mime_type, text=text).to_wire()]

    async def directory_read(self, uri: str) -> list[Resource]:
        """``resources/directory/read`` (SEP-2640) across providers."""
        for provider in self.resource_providers:
            listing = await provider.directory_read(uri)
            if listing is not None:
                return listing
        raise InvalidParamsError(f"Not a directory resource: {uri}", data={"uri": uri})

    # -- prompts/get -----------------------------------------------------------

    async def get_prompt(
        self, name: str, arguments: dict[str, Any], ctx: ModernContext
    ) -> dict[str, Any]:
        """Render a prompt to the wire GetPromptResult shape.

        Prompt argument values are strings on the wire (every revision);
        the per-parameter TypeAdapters coerce them to what the function
        signature wants (int patron ids, Literal durations, ...).
        """
        del ctx  # prompt functions take no context today; kept for parity
        entry = self._prompts.get(name)
        if entry is None or self._is_disabled("prompt", name):
            raise InvalidParamsError(f"Unknown prompt: {name}")

        declared = {a.name for a in entry.definition.arguments or []}
        required = {a.name for a in entry.definition.arguments or [] if a.required}
        missing = required - set(arguments)
        if missing:
            raise InvalidParamsError(
                f"Missing required arguments for prompt '{name}': {', '.join(sorted(missing))}"
            )

        kwargs: dict[str, Any] = {}
        for key, value in arguments.items():
            if key not in declared:
                continue  # unrecognized extras are ignored (spec SHOULD)
            adapter = entry.coercers.get(key)
            if adapter is None:
                kwargs[key] = value
                continue
            try:
                kwargs[key] = adapter.validate_python(value)
            except ValidationError as exc:
                raise InvalidParamsError(
                    f"Invalid argument {key!r} for prompt '{name}': "
                    f"{exc.errors()[0].get('msg', 'validation failed')}"
                ) from exc

        rendered = await entry.fn(**kwargs)
        # A prompt renders to messages priming the LLM; a single user text
        # message is the canonical minimal shape.
        return {
            "resultType": "complete",
            "description": entry.definition.description,
            "messages": [
                {"role": "user", "content": {"type": "text", "text": rendered}},
            ],
        }

    # -- completion/complete ----------------------------------------------------

    def completion(
        self,
        ref: dict[str, Any],
        arg_name: str,
        value: str,
        context: dict[str, Any] | None = None,
    ) -> list[str]:
        """Hand-wired completables backed by live data.

        - prompt args: genre (DB DISTINCT), experience_level / review_type
          (their Literal option sets), target_audience (curated list);
        - resource template vars: genre (DB), status (PatronStatus enum),
          isbn (prefix match against the catalog).

        Unknown ref names are ``-32602`` (spec: invalid prompt name).
        Unknown ARGUMENT names return no suggestions — absence of
        completions is not an error.
        """
        del context  # accepted per spec (context.arguments); unused so far
        ref_type = ref.get("type")
        if ref_type == "ref/prompt":
            name = ref.get("name")
            if name not in self._prompts:
                raise InvalidParamsError(f"Unknown prompt: {name}")
            completer = self._PROMPT_COMPLETIONS.get((str(name), arg_name))
        elif ref_type == "ref/resource":
            uri = ref.get("uri")
            known = {t.definition.uri_template for t in self._templates}
            if uri not in known:
                raise InvalidParamsError(f"Unknown resource template: {uri}")
            completer = self._TEMPLATE_COMPLETIONS.get((str(uri), arg_name))
        else:
            raise InvalidParamsError(
                f"Invalid completion ref type: {ref_type!r} (expected 'ref/prompt' or 'ref/resource')"
            )

        if completer is None:
            return []
        values = completer(self, value)
        # Return up to ONE past the cap so the caller can tell "exactly the
        # cap" from "the cap plus more" and set completion.hasMore honestly
        # (research-serverFeat.md §4). The dispatcher truncates to the cap.
        return values[: _MAX_COMPLETION_VALUES + 1]

    def _complete_genres(self, prefix: str) -> list[str]:
        with session_scope() as session:
            rows = session.execute(select(BookDB.genre).distinct()).scalars().all()
        lowered = prefix.lower()
        return sorted(g for g in rows if g and g.lower().startswith(lowered))

    def _complete_isbns(self, prefix: str) -> list[str]:
        with session_scope() as session:
            rows = session.execute(
                select(BookDB.isbn).where(BookDB.isbn.startswith(prefix)).order_by(BookDB.isbn)
            ).scalars()
            # One past the cap so the dispatcher can detect "more available".
            return list(rows.fetchmany(_MAX_COMPLETION_VALUES + 1))

    @staticmethod
    def _complete_static(options: Iterable[str]) -> Callable[["ModernRegistry", str], list[str]]:
        values = sorted(options)

        def completer(_registry: "ModernRegistry", prefix: str) -> list[str]:
            lowered = prefix.lower()
            return [v for v in values if v.lower().startswith(lowered)]

        return completer

    #: (prompt name, argument) -> completer
    _PROMPT_COMPLETIONS: dict[tuple[str, str], Callable[["ModernRegistry", str], list[str]]] = {
        ("recommend_books", "genre"): lambda registry, prefix: registry._complete_genres(prefix),
        ("generate_reading_plan", "experience_level"): _complete_static(
            ["beginner", "intermediate", "advanced", "expert"]
        ),
        ("generate_book_review", "review_type"): _complete_static(
            ["summary", "critical", "recommendation"]
        ),
        ("generate_book_review", "target_audience"): _complete_static(
            [
                "adult readers",
                "book club members",
                "casual readers",
                "students",
                "teenagers",
                "young adults",
            ]
        ),
    }

    #: (uriTemplate, variable) -> completer
    _TEMPLATE_COMPLETIONS: dict[tuple[str, str], Callable[["ModernRegistry", str], list[str]]] = {
        ("library://books/by-genre/{genre}", "genre"): lambda registry, prefix: (
            registry._complete_genres(prefix)
        ),
        ("library://patrons/by-status/{status}", "status"): _complete_static(
            [status.value for status in PatronStatus]
        ),
        ("library://books/{isbn}", "isbn"): lambda registry, prefix: registry._complete_isbns(
            prefix
        ),
    }
