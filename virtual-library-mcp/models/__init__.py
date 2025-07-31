"""
Virtual Library MCP Server Models.

This package contains Pydantic models for all core entities in the
Virtual Library MCP Server. These models provide:

1. Data validation using Pydantic v2
2. Serialization to/from JSON for MCP protocol compliance
3. Type hints for all fields
4. Rich documentation for API usage

The models represent:
- Book: Library catalog items
- Author: Book authors with bibliographic information
- Patron: Library members who can borrow books
- Circulation: Checkout, return, and reservation records
"""

from .author import Author
from .book import Book
from .circulation import CheckoutRecord, ReservationRecord, ReturnRecord
from .patron import Patron

__all__ = [
    "Author",
    "Book",
    "CheckoutRecord",
    "Patron",
    "ReservationRecord",
    "ReturnRecord",
]
