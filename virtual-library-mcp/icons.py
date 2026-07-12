"""Icons for MCP components (SEP-973, MCP spec 2025-11-25).

The 2025-11-25 revision lets servers attach icons to tools, resources,
resource templates, and prompts so client UIs can render them visually.
Icons are standard ``mcp.types.Icon`` objects with a ``src`` URL.

We use self-contained ``data:`` URIs (inline SVG) rather than external
URLs: no network fetch, no tracking, works offline — the safest possible
icon source. Clients that don't render icons simply ignore them.
"""

from urllib.parse import quote

from mcp.types import Icon


def _svg_icon(svg_body: str) -> Icon:
    """Wrap an SVG fragment in a data-URI Icon (24x24 viewBox)."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="#4A5568" stroke-width="2">{svg_body}</svg>'
    )
    return Icon(
        src=f"data:image/svg+xml,{quote(svg)}",
        mimeType="image/svg+xml",
        sizes=["24x24"],
    )


BOOK_ICON = _svg_icon('<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V2H6.5A2.5 2.5 0 0 0 4 4.5z"/>')

SEARCH_ICON = _svg_icon('<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>')

CARD_ICON = _svg_icon('<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>')

STATS_ICON = _svg_icon('<path d="M3 3v18h18"/><path d="m7 13 4-4 4 4 5-6"/>')

SPARKLE_ICON = _svg_icon(
    '<path d="M12 3l1.9 5.7L19.6 10l-5.7 1.9L12 17.6l-1.9-5.7L4.4 10l5.7-1.9z"/>'
)

MAINTENANCE_ICON = _svg_icon(
    '<path d="M14.7 6.3a5 5 0 1 0-6.6 6.6L3 18v3h3l5.1-5.1a5 5 0 0 0 6.6-6.6l-3 3-2.8-.7-.7-2.8z"/>'
)
