"""Virtual Library MCP Resources Package

This package contains all MCP resource implementations for the Virtual Library server.

MCP RESOURCES EXPLAINED:
Resources in the Model Context Protocol are read-only data endpoints that provide
access to server-side information. Think of them as the "GET" endpoints in REST,
but with a more structured approach:

1. **URI-Based**: Each resource has a unique URI (e.g., library://books/list)
2. **Read-Only**: Resources cannot modify data (use Tools for that)
3. **Paginated**: Large collections support cursor-based pagination
4. **Subscribable**: Clients can watch resources for changes (optional)
5. **Metadata-Rich**: Resources include descriptions and MIME types

RESOURCE VS TOOL:
- Resource: "Show me the list of books" (read operation)
- Tool: "Check out this book" (write operation)

This separation follows the Command Query Responsibility Segregation (CQRS)
pattern, making the protocol more predictable and secure.
"""

from .advanced_books import advanced_book_resources
from .books import book_resources
from .patrons import patron_resources
from .recommendations import recommendation_resources
from .stats import stats_resources

# Combine all resources
all_resources = (
    book_resources
    + advanced_book_resources
    + patron_resources
    + stats_resources
    + recommendation_resources
)

__all__ = [
    "advanced_book_resources",
    "all_resources",
    "book_resources",
    "patron_resources",
    "recommendation_resources",
    "stats_resources",
]
