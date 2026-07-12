"""
MCP Tools for the Virtual Library Server.

Tools are the MCP primitive for actions with side effects — the "POST"
half of the protocol, where resources are the "GET" half. Each tool here
is a plain typed Python function; FastMCP derives the JSON Schema the
client sees from the signature (names, types, constraints, docs).

Registration happens in register(), which attaches per-tool protocol
metadata from the MCP 2025-11-25 revision:

- ToolAnnotations: behavioral hints (readOnlyHint, destructiveHint,
  idempotentHint, openWorldHint) that let clients build better UX —
  e.g. skipping confirmation prompts for read-only tools
- Icons (SEP-973): visual identity for client UIs
- Tags: server-side grouping for visibility control
- Background tasks (SEP-1686): regenerate_catalog can run as a pollable
  task for clients that request it

TOOL_SPECS is the declarative source of truth for that metadata. It exists
so the SAME tool definitions can be served by BOTH protocol eras: register()
feeds them to FastMCP (legacy, 2025-11-25 and earlier), while the modern
package's ModernRegistry (MCP 2026-07-28) re-derives schemas from the same
functions and executes them with its own stateless-context machinery.
"""

from dataclasses import dataclass, field
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.tasks import TaskConfig
from mcp.types import Icon, ToolAnnotations

from icons import BOOK_ICON, CARD_ICON, MAINTENANCE_ICON, SEARCH_ICON, SPARKLE_ICON

from . import apps
from .apps import browse_catalog_app, library_dashboard_app
from .book_insights import generate_book_insights
from .bulk_import import bulk_import_books
from .catalog_maintenance import regenerate_catalog
from .circulation import checkout_book, reserve_book, return_book
from .membership import renew_membership
from .search import search_catalog


@dataclass(frozen=True)
class ToolSpec:
    """Era-agnostic description of one library tool.

    Deliberately framework-neutral: ``fn`` is a plain typed async function,
    and the metadata mirrors what both eras' wire Tool types carry. FastMCP
    consumes these in register(); modern/registry.py consumes them to build
    the 2026-07-28 tools/list entries and to execute calls itself.
    """

    fn: Any
    name: str
    annotations: ToolAnnotations
    icons: list[Icon] = field(default_factory=list)
    tags: frozenset[str] = frozenset()
    #: SEP-1686 (legacy era) background-task opt-in; the modern era's analog
    #: is the io.modelcontextprotocol/tasks extension (SEP-2663).
    task: TaskConfig | None = None


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        fn=search_catalog,
        name="search_catalog",
        annotations=ToolAnnotations(
            title="Search Catalog",
            readOnlyHint=True,  # never mutates state -> clients may skip confirmation
            idempotentHint=True,
            openWorldHint=False,  # operates only on this library's data
        ),
        icons=[SEARCH_ICON],
        tags=frozenset({"catalog"}),
    ),
    ToolSpec(
        fn=checkout_book,
        name="checkout_book",
        annotations=ToolAnnotations(
            title="Check Out Book",
            readOnlyHint=False,
            destructiveHint=False,  # additive: creates a loan, destroys nothing
            idempotentHint=False,  # same call twice = two loans
            openWorldHint=False,
        ),
        icons=[CARD_ICON],
        tags=frozenset({"circulation"}),
    ),
    ToolSpec(
        fn=return_book,
        name="return_book",
        annotations=ToolAnnotations(
            title="Return Book",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        icons=[CARD_ICON],
        tags=frozenset({"circulation"}),
    ),
    ToolSpec(
        fn=reserve_book,
        name="reserve_book",
        annotations=ToolAnnotations(
            title="Reserve Book",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        icons=[CARD_ICON],
        tags=frozenset({"circulation"}),
    ),
    ToolSpec(
        fn=renew_membership,
        name="renew_membership",
        annotations=ToolAnnotations(
            title="Renew Membership",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        icons=[CARD_ICON],
        tags=frozenset({"membership", "elicitation-demo"}),
    ),
    ToolSpec(
        fn=bulk_import_books,
        name="bulk_import_books",
        annotations=ToolAnnotations(
            title="Bulk Import Books",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        icons=[BOOK_ICON],
        tags=frozenset({"catalog", "admin"}),
    ),
    ToolSpec(
        fn=regenerate_catalog,
        name="regenerate_catalog",
        # SEP-1686: task-aware clients may run this in the background and
        # poll for completion; others get a normal (slow) synchronous call.
        task=TaskConfig(mode="optional"),
        annotations=ToolAnnotations(
            title="Regenerate Catalog",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,  # safe to re-run; rebuilds the same caches
            openWorldHint=False,
        ),
        icons=[MAINTENANCE_ICON],
        tags=frozenset({"admin"}),
    ),
    ToolSpec(
        fn=generate_book_insights,
        name="generate_book_insights",
        annotations=ToolAnnotations(
            title="Generate Book Insights",
            readOnlyHint=True,
            idempotentHint=False,  # sampling output varies run to run
            openWorldHint=False,
        ),
        icons=[SPARKLE_ICON],
        tags=frozenset({"ai", "sampling-demo"}),
    ),
]


def register(mcp: FastMCP) -> None:
    """Register every library tool with protocol metadata."""
    for spec in TOOL_SPECS:
        mcp.tool(
            spec.fn,
            annotations=spec.annotations,
            icons=spec.icons,
            tags=set(spec.tags),
            task=spec.task,
        )
    apps.register(mcp)


__all__ = [
    "TOOL_SPECS",
    "ToolSpec",
    "browse_catalog_app",
    "bulk_import_books",
    "checkout_book",
    "generate_book_insights",
    "library_dashboard_app",
    "regenerate_catalog",
    "register",
    "renew_membership",
    "reserve_book",
    "return_book",
    "search_catalog",
]
