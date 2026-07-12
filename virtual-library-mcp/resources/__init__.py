"""Virtual Library MCP Resources Package

Resources are MCP's read-only data endpoints — the "GET" half of the
protocol (tools are the "POST" half). Each module in this package exposes
a declarative list of resource definitions; register() binds them to the
server with protocol metadata from the 2025-11-25 revision (icons, tags).

Resource kinds demonstrated:
- Static resources: fixed URIs like library://books/list
- Resource templates (RFC 6570): parameterized URIs like
  library://books/{isbn}, which clients expand per request

Clients are notified automatically (notifications/resources/list_changed)
when resources are enabled or disabled at runtime — see the maintenance
mode in tools/catalog_maintenance.py.
"""

from fastmcp import FastMCP

from icons import BOOK_ICON, CARD_ICON, SPARKLE_ICON, STATS_ICON

from .advanced_books import advanced_book_resources
from .books import book_resources
from .patrons import patron_resources
from .recommendations import recommendation_resources
from .stats import stats_resources

# Resource group -> (definitions, icon, tags); one row per module.
_RESOURCE_GROUPS = [
    (book_resources, BOOK_ICON, {"catalog"}),
    (advanced_book_resources, BOOK_ICON, {"catalog"}),
    (patron_resources, CARD_ICON, {"patrons"}),
    (stats_resources, STATS_ICON, {"stats"}),
    (recommendation_resources, SPARKLE_ICON, {"ai"}),
]


def register(mcp: FastMCP) -> None:
    """Register every resource and template with the server."""
    for definitions, icon, tags in _RESOURCE_GROUPS:
        for definition in definitions:
            uri = definition.get("uri_template") or definition["uri"]
            mcp.resource(
                uri,
                name=definition["name"],
                description=definition["description"],
                mime_type=definition["mime_type"],
                icons=[icon],
                tags=tags,
            )(definition["handler"])


__all__ = [
    "advanced_book_resources",
    "book_resources",
    "patron_resources",
    "recommendation_resources",
    "register",
    "stats_resources",
]
