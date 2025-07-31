# Virtual Library MCP Server

A comprehensive MCP (Model Context Protocol) server implementation that simulates a complete library management system. This server serves as both a learning tool and a reference implementation for MCP concepts.

## 🚀 Quick Start

```bash
# Install dependencies
just install

# Initialize database with sample data
just db-init

# Run the MCP server
just dev
```

## 📋 Current Status

### ✅ Implemented

- **Phase 1**: Project setup and configuration ✅
- **Phase 2**: Data models and database layer ✅
  - Author, Book, Patron, and Circulation models
  - Repository pattern with pagination
  - 1200+ books, 120+ authors, 60+ patrons in seed data
- **Phase 3**: Core MCP Implementation ✅ **COMPLETED**
  - FastMCP 2.0 server initialization
  - Basic Resources:
    - `/books/list` - Browse catalog with pagination
    - `/books/{isbn}` - Get book details by ISBN
  - Advanced Resources with URI templates:
    - `/books/by-author/{author_id}` - Books by specific author
    - `/books/by-genre/{genre}` - Books in a genre
    - `/patrons/{id}/history` - Patron borrowing history
    - `/stats/popular` - Most borrowed books
    - `/stats/genres` - Genre distribution
    - `/stats/circulation` - Current circulation stats
    - `/recommendations/{patron_id}` - Personalized recommendations
  - Tools with validation:
    - `search_catalog` - Full-text search with filters
    - `checkout_book` - Create loan transactions
    - `return_book` - Process returns with fine calculation
    - `reserve_book` - Queue management for unavailable books

### 🚧 Coming Next

- **Phase 4**: Advanced MCP Features
  - **Step 16**: Subscriptions (real-time availability updates)
  - **Step 18**: Prompts (AI-powered book recommendations)
  - **Step 20**: Progress notifications for long operations

## 🏗️ Architecture

```text
virtual-library-mcp/
├── src/virtual_library_mcp/
│   ├── server.py           # MCP server entry point (NEW!)
│   ├── config.py           # Configuration management
│   ├── models/             # Pydantic data models
│   │   ├── author.py       # Author model with validation
│   │   ├── book.py         # Book model with ISBN validation
│   │   ├── patron.py       # Library patron model
│   │   └── circulation.py  # Checkout/return/reservation models
│   └── database/           # Data access layer
│       ├── schema.py       # SQLAlchemy models
│       ├── session.py      # Database session management
│       └── *_repository.py # Repository implementations
├── tests/                  # Comprehensive test suite
├── docs/                   # Project documentation
└── justfile               # Task automation
```

## 🛠️ Development

### Prerequisites

- Python 3.12+
- uv (package manager)
- just (task runner)

### Common Tasks

```bash
just test         # Run test suite
just lint         # Check code style
just typecheck    # Run type checking
just format       # Format code
just dev-debug    # Run with debug logging
```

### Testing the Server

The server uses stdio transport and expects JSON-RPC messages:

```bash
# Send an initialization request
echo '{"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "1.0"}, "id": 1}' | just dev
```

## 📚 MCP Features Demonstrated

1. **Resources** ✅
   - Browse library catalog with pagination and filtering
   - View book details by ISBN  
   - Dynamic URI templates for author/genre filtering
   - Patron history and circulation statistics
   - Personalized book recommendations
   - Popular books and genre distribution stats

2. **Tools** ✅
   - `search_catalog` - Full-text search with genre/author filters
   - `checkout_book` - Create loans with validation
   - `return_book` - Process returns and calculate fines
   - `reserve_book` - Manage reservation queues

3. **Prompts** (Phase 4 - Coming Soon)
   - Get personalized recommendations
   - Generate reading plans

4. **Subscriptions** (Phase 4 - Coming Soon)
   - Real-time availability updates
   - Reservation notifications

## 🔍 Code Highlights

- **Type Safety**: Comprehensive type annotations with Pydantic
- **Error Handling**: MCP-compliant error responses
- **Testing**: 100+ tests with fixtures
- **Documentation**: Extensive inline documentation explaining MCP concepts

## 🔄 Async/Sync Architecture Pattern

### Understanding the Mixed Async/Sync Approach

This MCP server uses a specific pattern that might seem unusual at first: **async handlers with synchronous database operations**. This is intentional and correct for our use case.

#### Why Async Handlers?

MCP protocol and FastMCP require async handlers because:
- The protocol layer needs non-blocking I/O for handling multiple concurrent requests
- Long-running operations shouldn't block other requests
- Future operations might need async capabilities (external APIs, etc.)

#### Why Sync Database Operations?

We use synchronous SQLAlchemy with SQLite because:
- SQLite is a local, file-based database with fast operations
- Async SQLite provides no performance benefit (still single-threaded)
- Synchronous code is simpler to understand and debug
- SQLAlchemy's sync API is more mature and well-documented

#### The Pattern in Practice

```python
# MCP requires async handlers
async def list_books_handler(
    uri: str,
    context: Context,
    params: BookListParams | None = None,
) -> dict[str, Any]:
    # But we can use sync operations inside
    with session_scope() as session:  # Sync context manager
        repo = BookRepository(session)
        result = repo.search(...)     # Sync database query
        return result.model_dump()    # Return sync result from async function
```

#### Key Points

1. **This is not a mistake** - Async functions can contain sync code
2. **Performance is fine** - SQLite operations are fast enough to not block
3. **Future flexibility** - Easy to add async operations later if needed
4. **Best of both worlds** - Protocol compliance + implementation simplicity

#### When to Use Full Async

You would use async all the way down when:
- Using PostgreSQL/MySQL with async drivers (asyncpg, aiomysql)
- Making external HTTP API calls
- Dealing with slow I/O operations
- Handling many concurrent database connections

For a learning project with SQLite, the mixed approach provides the best balance of correctness and simplicity.

## 📖 Learning Resources

- See `src/virtual_library_mcp/server.py` for detailed MCP protocol explanations
- Check `docs/DEVELOPMENT.md` for development workflow
- Review test files for usage examples

## 🤝 Contributing

This is a learning project. Feel free to:

- Report issues
- Suggest improvements
- Add new MCP features
- Improve documentation

## 📄 License

Part of the MCP Learning Repository - see parent directory for license details.
