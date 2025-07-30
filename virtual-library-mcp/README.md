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

- **Phase 1**: Project setup and configuration
- **Phase 2**: Data models and database layer
  - Author, Book, Patron, and Circulation models
  - Repository pattern with pagination
  - 1200+ books, 120+ authors, 60+ patrons in seed data
- **Phase 3** (In Progress): MCP Server initialization
  - FastMCP 2.0 integration
  - Three-phase initialization handshake
  - Stdio transport configuration
  - Comprehensive logging

### 🚧 Coming Next

- **Step 12**: Resources (`/books/list`, `/books/{isbn}`, `/authors/{id}`)
- **Step 14**: Tools (`search_catalog`, `checkout_book`, `return_book`)
- **Step 16**: Subscriptions (real-time availability updates)
- **Step 18**: Prompts (AI-powered book recommendations)

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

1. **Resources** (Coming Soon)
   - Browse library catalog
   - View book details
   - Check patron history

2. **Tools** (Coming Soon)
   - Search for books
   - Check out/return books
   - Manage reservations

3. **Prompts** (Coming Soon)
   - Get personalized recommendations
   - Generate reading plans

4. **Subscriptions** (Coming Soon)
   - Real-time availability updates
   - Reservation notifications

## 🔍 Code Highlights

- **Type Safety**: Comprehensive type annotations with Pydantic
- **Error Handling**: MCP-compliant error responses
- **Testing**: 100+ tests with fixtures
- **Documentation**: Extensive inline documentation explaining MCP concepts

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
