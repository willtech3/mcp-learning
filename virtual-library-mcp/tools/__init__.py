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
"""

from fastmcp import FastMCP
from fastmcp.server.tasks import TaskConfig
from mcp.types import ToolAnnotations

from icons import BOOK_ICON, CARD_ICON, MAINTENANCE_ICON, SEARCH_ICON, SPARKLE_ICON

from .book_insights import generate_book_insights
from .bulk_import import bulk_import_books
from .catalog_maintenance import regenerate_catalog
from .circulation import checkout_book, reserve_book, return_book
from .membership import renew_membership
from .search import search_catalog


def register(mcp: FastMCP) -> None:
    """Register every library tool with protocol metadata."""
    mcp.tool(
        search_catalog,
        annotations=ToolAnnotations(
            title="Search Catalog",
            readOnlyHint=True,  # never mutates state -> clients may skip confirmation
            idempotentHint=True,
            openWorldHint=False,  # operates only on this library's data
        ),
        icons=[SEARCH_ICON],
        tags={"catalog"},
    )

    mcp.tool(
        checkout_book,
        annotations=ToolAnnotations(
            title="Check Out Book",
            readOnlyHint=False,
            destructiveHint=False,  # additive: creates a loan, destroys nothing
            idempotentHint=False,  # same call twice = two loans
            openWorldHint=False,
        ),
        icons=[CARD_ICON],
        tags={"circulation"},
    )

    mcp.tool(
        return_book,
        annotations=ToolAnnotations(
            title="Return Book",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        icons=[CARD_ICON],
        tags={"circulation"},
    )

    mcp.tool(
        reserve_book,
        annotations=ToolAnnotations(
            title="Reserve Book",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        icons=[CARD_ICON],
        tags={"circulation"},
    )

    mcp.tool(
        renew_membership,
        annotations=ToolAnnotations(
            title="Renew Membership",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        icons=[CARD_ICON],
        tags={"membership", "elicitation-demo"},
    )

    mcp.tool(
        bulk_import_books,
        annotations=ToolAnnotations(
            title="Bulk Import Books",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        icons=[BOOK_ICON],
        tags={"catalog", "admin"},
    )

    mcp.tool(
        regenerate_catalog,
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
        tags={"admin"},
    )

    mcp.tool(
        generate_book_insights,
        annotations=ToolAnnotations(
            title="Generate Book Insights",
            readOnlyHint=True,
            idempotentHint=False,  # sampling output varies run to run
            openWorldHint=False,
        ),
        icons=[SPARKLE_ICON],
        tags={"ai", "sampling-demo"},
    )


__all__ = [
    "bulk_import_books",
    "checkout_book",
    "generate_book_insights",
    "regenerate_catalog",
    "register",
    "renew_membership",
    "reserve_book",
    "return_book",
    "search_catalog",
]
