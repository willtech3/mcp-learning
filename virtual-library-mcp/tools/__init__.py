"""
MCP Tools for the Virtual Library Server.

This module implements MCP tools - actions with side effects that allow
LLMs to interact with the library system. Unlike resources (read-only),
tools can modify state, perform searches, and execute operations.

MCP TOOLS ARCHITECTURE:
Tools in the Model Context Protocol are:
1. Actions that can have side effects (create, update, delete)
2. Defined with JSON Schema for input validation
3. Invoked by clients via tools/call requests
4. Return results or errors in a structured format

The tools module follows MCP best practices:
- Clear separation between read (resources) and write (tools) operations
- Comprehensive input validation using Pydantic schemas
- Proper error handling with meaningful messages
- Atomic operations with rollback on failure
"""

from .book_insights import generate_book_insights
from .bulk_import import bulk_import_books
from .catalog_maintenance import regenerate_catalog_tool
from .circulation import checkout_book, reserve_book, return_book
from .search import search_catalog

# Export all tools for server registration
# WHY: The server needs a single list of all available tools
# HOW: Each tool is a dictionary with metadata and handler
# WHAT: This list is used during server initialization
all_tools = [
    search_catalog,
    checkout_book,
    return_book,
    reserve_book,
    bulk_import_books,
    regenerate_catalog_tool,
    generate_book_insights,
]

__all__ = [
    "all_tools",
    "bulk_import_books",
    "checkout_book",
    "generate_book_insights",
    "regenerate_catalog_tool",
    "reserve_book",
    "return_book",
    "search_catalog",
]
