# MCP Tools - Complete Guide

Tools are the **Command** side of CQRS in the Model Context Protocol, enabling clients to perform actions that modify server state through validated, atomic operations.

## Core Concepts

Tools fundamentally differ from Resources in their ability to cause **side effects**. While Resources answer "what is?", Tools answer "what if?" and then make it reality. Every tool represents a discrete action: checking out a book, processing a return, creating a reservation.

The MCP protocol ensures tools are:
- **Validated**: Input schemas enforce type safety and business rules
- **Atomic**: Operations complete fully or roll back entirely  
- **Descriptive**: Rich metadata explains purpose and parameters
- **Discoverable**: Clients list available tools via `tools/list`
- **Traceable**: Operations can be logged for audit trails

Tools flow through JSON-RPC 2.0: clients send `tools/call` requests with tool name and arguments, servers validate input, execute operations, and return structured results or errors. This RPC approach provides clear contracts while maintaining protocol flexibility.

## Implementation Patterns

### Pydantic Schema Design

Input validation is mandatory and automatic:
```python
# From search.py - Comprehensive input validation
class SearchCatalogInput(BaseModel):
    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Search term"
    )
    page: int = Field(default=1, ge=1, le=1000)
    page_size: int = Field(default=10, ge=1, le=50)
    
    @field_validator("query")
    @classmethod
    def clean_query(cls, v):
        if v:
            return v.strip()
        return v
```

Pydantic models generate JSON Schema automatically, enabling:
- Client-side validation
- API documentation
- Type hints in handlers

### Multi-Step Operations

Complex tools orchestrate multiple actions:
```python
# From circulation.py - Checkout process
async def checkout_book_handler(arguments: dict[str, Any]):
    # Step 1: Validate input
    params = CheckoutBookInput.model_validate(arguments)
    
    # Step 2: Check patron eligibility
    patron = validate_patron_status(params.patron_id)
    
    # Step 3: Verify book availability  
    book = check_book_available(params.book_isbn)
    
    # Step 4: Create checkout record
    checkout = create_checkout(patron, book, params.due_date)
    
    # Step 5: Update book inventory
    decrease_available_copies(book)
    
    # Step 6: Return success response
    return format_checkout_response(checkout)
```

Each step can fail independently with specific error messages.

### Error Handling Layers

Tools implement defense in depth:
```python
# Layer 1: Input validation
try:
    params = InputModel.model_validate(arguments)
except ValidationError as e:
    return {"isError": True, "content": [{"type": "text", "text": str(e)}]}

# Layer 2: Business logic validation  
if not patron.can_checkout():
    return {"isError": True, "content": [{"type": "text", "text": "Patron has overdue books"}]}

# Layer 3: Database operations
try:
    result = repo.execute_operation()
except IntegrityError:
    return {"isError": True, "content": [{"type": "text", "text": "Operation would violate constraints"}]}

# Layer 4: Unexpected errors
except Exception as e:
    logger.exception("Tool execution failed")
    return {"isError": True, "content": [{"type": "text", "text": "An unexpected error occurred"}]}
```

### Business Rule Enforcement

Tools encapsulate domain logic:
```python
# From circulation.py - Return book with fines
def calculate_fine(checkout: Checkout) -> float:
    if checkout.return_date <= checkout.due_date:
        return 0.0
    
    days_late = (checkout.return_date - checkout.due_date).days
    
    # Business rules embedded in tool
    DAILY_FINE = 0.50
    MAX_FINE = 25.00
    
    return min(days_late * DAILY_FINE, MAX_FINE)
```

## Technical Deep Dive

### JSON Schema Generation

Pydantic models automatically generate OpenAPI-compatible schemas:
```python
# Input model
class ReserveBookInput(BaseModel):
    patron_id: str = Field(..., pattern=r"^patron_[a-zA-Z0-9_]{6,}$")
    book_isbn: str = Field(..., pattern=r"^\d{13}$")
    expiration_date: date | None = None

# Generated schema (simplified)
{
    "type": "object",
    "required": ["patron_id", "book_isbn"],
    "properties": {
        "patron_id": {
            "type": "string",
            "pattern": "^patron_[a-zA-Z0-9_]{6,}$"
        },
        "book_isbn": {
            "type": "string", 
            "pattern": "^\\d{13}$"
        },
        "expiration_date": {
            "type": "string",
            "format": "date"
        }
    }
}
```

### Handler Async Patterns

All tool handlers are async for concurrent execution:
```python
async def tool_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    # Async database operations
    async with get_async_session() as session:
        result = await session.execute(query)
    
    # Parallel external calls
    results = await asyncio.gather(
        check_inventory(isbn),
        validate_patron(patron_id),
        get_recommendations(genre)
    )
    
    # Non-blocking I/O
    await notify_patron(patron_id, message)
```

### Database Transaction Management

Tools ensure data consistency:
```python
# Automatic rollback on failure
with get_session() as session:
    try:
        # Multiple related operations
        checkout = create_checkout_record(session)
        update_book_availability(session, -1)
        add_to_patron_history(session)
        
        # Commit all or nothing
        session.commit()
    except Exception:
        session.rollback()
        raise
```

For long operations:
```python
# Savepoints for partial rollback
with session.begin_nested():
    process_batch_operation()
    session.commit()  # Commits savepoint
```

### Response Format Standards

Consistent success responses:
```python
# Success with data
{
    "content": [{
        "type": "text",
        "text": "Successfully checked out book"
    }],
    "data": {
        "checkout": {
            "id": "checkout_123",
            "due_date": "2024-02-01",
            "renewable": true
        }
    }
}

# Error response
{
    "isError": true,
    "content": [{
        "type": "text", 
        "text": "Book is not available"
    }]
}
```

### Progress Notifications (Future)

Long-running tools will support progress:
```python
async def batch_import_handler(arguments):
    total = len(arguments["books"])
    
    for i, book in enumerate(arguments["books"]):
        # Process book
        await import_book(book)
        
        # Send progress notification
        await send_progress({
            "progress": i + 1,
            "total": total,
            "message": f"Imported {book['title']}"
        })
```

## Best Practices

### Idempotency Considerations

Design tools to be safely retryable:
```python
# Use unique identifiers
checkout_id = f"checkout_{patron_id}_{isbn}_{date.today()}"

# Check if operation already completed
existing = session.query(Checkout).filter_by(id=checkout_id).first()
if existing:
    return format_checkout_response(existing)  # Return existing result

# Proceed with operation
```

### Validation Strategies

Layer validation for better errors:
```python
# 1. Type validation (automatic via Pydantic)
# 2. Format validation
if not isbn.isdigit() or len(isbn) != 13:
    raise ValueError("ISBN must be 13 digits")

# 3. Business validation
if patron.books_checked_out >= patron.checkout_limit:
    raise ValueError("Checkout limit exceeded")

# 4. State validation  
if book.available_copies <= 0:
    raise ValueError("No copies available")
```

### Audit Logging Patterns

Track all state changes:
```python
def log_operation(operation: str, **kwargs):
    logger.info(
        "Operation: %s | User: %s | Details: %s",
        operation,
        kwargs.get("user_id", "system"),
        json.dumps(kwargs)
    )

# In handler
log_operation(
    "checkout_book",
    patron_id=params.patron_id,
    isbn=params.book_isbn,
    due_date=checkout.due_date
)
```

### Rollback Mechanisms

Implement compensating transactions:
```python
# Track actions for rollback
actions_taken = []

try:
    # Action 1
    decrease_inventory(book)
    actions_taken.append(("increase_inventory", book))
    
    # Action 2  
    create_checkout(patron, book)
    actions_taken.append(("delete_checkout", checkout_id))
    
    # Action 3 fails
    send_notification()  # Raises exception
    
except Exception:
    # Rollback in reverse order
    for action, param in reversed(actions_taken):
        compensate(action, param)
    raise
```

## Tool Permissions and Security

Tools should verify permissions:
```python
# Role-based access
def requires_role(role: str):
    def decorator(func):
        async def wrapper(arguments):
            user = get_current_user()
            if role not in user.roles:
                return {"isError": True, "content": [{"type": "text", "text": "Insufficient permissions"}]}
            return await func(arguments)
        return wrapper
    return decorator

@requires_role("librarian")
async def delete_patron_handler(arguments):
    # Only librarians can delete patrons
```

## Examples in This Repository

| Pattern | File | Description |
|---------|------|-------------|
| Comprehensive search | `search.py` | Multi-parameter search with pagination |
| State modifications | `circulation.py` | Checkout, return, reserve operations |
| Input validation | Both files | Pydantic models with constraints |
| Error handling | Both files | Layered error responses |
| Transaction management | `circulation.py` | Atomic operations with rollback |
| Business logic | `circulation.py` | Fine calculation, eligibility checks |

## Common Tool Patterns

### CRUD Operations
```python
# Create
@mcp.tool("create_patron")
async def create_patron(name: str, email: str):
    # Validation, creation, return new ID

# Update  
@mcp.tool("update_patron")
async def update_patron(id: str, updates: dict):
    # Partial updates with validation

# Delete (soft)
@mcp.tool("deactivate_patron")  
async def deactivate_patron(id: str, reason: str):
    # Mark as inactive rather than hard delete
```

### Batch Operations
```python
@mcp.tool("batch_checkout")
async def batch_checkout(checkouts: list[CheckoutRequest]):
    results = []
    for checkout in checkouts:
        try:
            result = await process_checkout(checkout)
            results.append({"success": True, "data": result})
        except Exception as e:
            results.append({"success": False, "error": str(e)})
    return results
```

### Workflow Tools
```python
@mcp.tool("process_return_workflow")
async def process_return_workflow(checkout_id: str):
    # Step 1: Process return
    return_record = await process_return(checkout_id)
    
    # Step 2: Calculate fines
    fine = await calculate_fines(return_record)
    
    # Step 3: Update patron record
    await update_patron_fines(patron_id, fine)
    
    # Step 4: Check reservations
    await process_next_reservation(book_isbn)
    
    return workflow_summary
```

## Related Documentation

- [Resources README](../resources/README.md) - Read-only data access
- [Prompts README](../prompts/README.md) - LLM interaction templates  
- [MCP Specification](https://modelcontextprotocol.io/docs/specification)
- [Pydantic Documentation](https://docs.pydantic.dev/)