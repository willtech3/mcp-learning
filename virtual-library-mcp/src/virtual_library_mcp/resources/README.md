# MCP Resources - Complete Guide

Resources are read-only data endpoints in the Model Context Protocol, providing structured access to server-side information through URI-based addressing.

## Core Concepts

Resources embody the **Query** side of CQRS (Command Query Responsibility Segregation), strictly separating data retrieval from modification. Every resource is identified by a URI following the pattern `scheme://path`, like `library://books/list` or `library://patrons/{id}`. 

The MCP protocol ensures resources are:
- **Immutable**: Resources never modify server state
- **Addressable**: Each resource has a unique, stable URI
- **Discoverable**: Clients can list available resources via `resources/list`
- **Typed**: Resources declare MIME types for content negotiation
- **Describable**: Each resource includes human-readable descriptions

Resources flow through the JSON-RPC 2.0 protocol: clients send `resources/read` requests with URIs, servers respond with content or errors. This RESTful approach provides familiarity while maintaining protocol benefits like subscriptions and progress notifications.

## Implementation Patterns

### URI Template Design

**Static URIs** provide fixed endpoints:
```python
# From books.py - Simple list endpoint
@mcp.resource("library://books/list")
async def list_books_handler() -> dict[str, Any]:
    # Returns paginated book list
```

**URI Templates** enable dynamic routing with parameters:
```python
# From advanced_books.py - Author filtering
@mcp.resource("library://books/by-author/{author_id}")
async def get_books_by_author_handler(author_id: str) -> dict[str, Any]:
    # FastMCP 2.0 automatically extracts 'author_id' parameter
```

Templates follow RFC 6570 patterns. Parameters are extracted and passed to handlers automatically. Design hierarchically: `/resource/{id}/sub-resource` shows clear ownership.

### Pagination Patterns

Large collections require pagination for performance:
```python
# From books.py - Paginated response structure
class BookListParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

# Response includes navigation metadata
return {
    "books": [...],
    "pagination": {
        "page": 1,
        "page_size": 20,
        "total": 150,
        "total_pages": 8,
        "has_next": True,
        "has_previous": False
    }
}
```

### Aggregation Patterns

Resources can provide computed views without modifying data:
```python
# From stats.py - Time-based aggregations
@mcp.resource("library://stats/popular/{days}/{limit}")
async def get_popular_books_handler(days: str, limit: str):
    # Aggregate checkout data over time period
    # Return ranked list with metrics
```

Aggregations leverage database capabilities for efficiency. Parameters control scope and granularity.

### Nested Resources

Express relationships through URI hierarchy:
```python
# From patrons.py - Patron's borrowing history
@mcp.resource("library://patrons/{id}/history")
async def get_patron_history_handler(id: str):
    # Returns checkout records for specific patron
    # Clear parent-child relationship in URI
```

### Dynamic Personalization

Resources can adapt based on context:
```python
# From recommendations.py - Personalized suggestions
@mcp.resource("library://recommendations/for-patron/{patron_id}")
async def get_patron_recommendations_handler(patron_id: str):
    # Analyzes patron history
    # Returns tailored book suggestions
```

## Technical Deep Dive

### FastMCP Handler Architecture

FastMCP 2.0 simplifies resource implementation:
```python
# Decorator pattern for resource registration
@mcp.resource(
    uri="library://books/{isbn}",
    name="Book Details",
    description="Get detailed information about a specific book",
    mime_type="application/json"
)
async def handler(isbn: str) -> dict[str, Any]:
    # FastMCP handles:
    # - Parameter extraction from URI
    # - JSON serialization
    # - Error wrapping
    # - Schema validation
```

### Error Handling Strategies

Resources use `ResourceError` for protocol-compliant error responses:
```python
from fastmcp.exceptions import ResourceError

# Validation errors
if not isbn.isdigit():
    raise ResourceError("Invalid ISBN format")

# Not found errors  
book = repo.get_by_isbn(isbn)
if not book:
    raise ResourceError(f"Book {isbn} not found", code="NOT_FOUND")

# Database errors
try:
    result = expensive_operation()
except DatabaseError as e:
    logger.exception("Database query failed")
    raise ResourceError("Failed to retrieve data") from e
```

### Database Session Management

Use context managers for proper cleanup:
```python
# From session.py - Shared session utilities
from ..database.session import session_scope

async def resource_handler():
    with session_scope() as session:
        # Session automatically closed after block
        repo = BookRepository(session)
        return repo.get_all()
```

Alternative patterns for testing:
```python
async def handler(_session=None):
    session = _session or next(get_session())
    should_close = _session is None
    try:
        # Use session
    finally:
        if should_close:
            session.close()
```

### Performance Optimization

**Query Optimization**:
```python
# Eager loading relationships
query = select(Book).options(joinedload(Book.author))

# Limit fields selected
query = select(Book.isbn, Book.title, Book.available_copies)

# Push filtering to database
query = query.where(Book.genre == genre)
```

**Response Limiting**:
```python
# Enforce maximum page sizes
page_size: int = Field(default=20, le=100)

# Truncate large text fields
description = book.description[:200] + "..." if len(book.description) > 200 else book.description
```

**Caching Opportunities**:
- Static resources (genres, categories)
- Expensive aggregations (popular books)
- Personalized content with TTL

### Response Format Standards

Consistent structure across all resources:
```python
# List responses
{
    "items": [...],
    "total": 50,
    "metadata": {
        "generated_at": "2024-01-15T10:30:00Z",
        "cache_ttl": 300
    }
}

# Single item responses
{
    "data": { ... },
    "metadata": { ... }
}

# Error responses (handled by FastMCP)
{
    "error": {
        "code": "NOT_FOUND",
        "message": "Resource not found"
    }
}
```

## Best Practices

### URI Design Conventions

1. **Use nouns, not verbs**: `library://books` not `library://getBooks`
2. **Hierarchical relationships**: `library://patrons/{id}/history`
3. **Consistent pluralization**: Always plural for collections
4. **Lowercase with hyphens**: `library://new-releases` not `library://NewReleases`
5. **Version in path if needed**: `library://v2/books`

### Parameter Validation

Always validate extracted parameters:
```python
# Type validation
days_int = int(days)
if not 1 <= days_int <= 365:
    raise ResourceError("Days must be between 1 and 365")

# Format validation  
if not patron_id.startswith("patron_"):
    raise ResourceError("Invalid patron ID format")

# Business rule validation
if status not in ["active", "suspended", "expired"]:
    raise ResourceError(f"Unknown status: {status}")
```

### Security Considerations

1. **Never expose sensitive data**: Hash or mask PII
2. **Validate access rights**: Check if patron can view their own data
3. **Rate limiting**: Implement for expensive resources
4. **Input sanitization**: Prevent injection attacks
5. **Audit logging**: Track access to sensitive resources

### Caching Strategies

Define cache behavior explicitly:
```python
return {
    "data": books,
    "cache_control": {
        "max_age": 300,  # 5 minutes
        "etag": compute_etag(books),
        "varies": ["Authorization"]  # Cache per user
    }
}
```

## Examples in This Repository

| Pattern | File | Description |
|---------|------|-------------|
| Basic list with pagination | `books.py` | Standard paginated collection |
| URI templates | `advanced_books.py` | Dynamic filtering by author/genre |
| Aggregations | `stats.py` | Popular books, circulation metrics |
| Nested resources | `patrons.py` | Patron history, status filtering |
| Personalization | `recommendations.py` | ML-style recommendations |
| Error handling | All files | Consistent error patterns |

## Related Documentation

- [Tools README](../tools/README.md) - State-modifying operations
- [Prompts README](../prompts/README.md) - LLM interaction templates
- [MCP Specification](https://modelcontextprotocol.io/docs/specification)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)