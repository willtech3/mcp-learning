# MCP Learning Repository

A comprehensive educational repository for learning and implementing the Model Context Protocol (MCP). This project includes extensive MCP documentation and a hands-on Virtual Library MCP Server implementation that demonstrates all core MCP concepts.

## 🎯 Project Goals

- **Learn MCP by Building**: Implement a fully-featured MCP server while understanding the protocol deeply
- **Comprehensive Documentation**: Access detailed MCP documentation covering all aspects of the protocol
- **Hands-on Experience**: Build a realistic Virtual Library management system that showcases every MCP feature
- **Best Practices**: Follow modern Python development practices with type safety, testing, and automation

## 📚 Repository Structure

```text
mcp-learning/
├── docs/
│   └── mcp/
│       ├── 01-overview.md
│       ├── 02-architecture.md
│       ├── 03-protocol-specification.md
│       ├── 04-transport-layer.md
│       ├── 05-server-development.md
│       ├── 06-client-development.md
│       ├── 07-sdk-reference.md
│       ├── 08-security.md
│       ├── 09-examples.md
│       └── 10-additional-resources.md
├── virtual-library-mcp/
│   ├── config.py
│   ├── server.py
│   ├── pyproject.toml
│   ├── justfile
│   ├── data/
│   │   ├── library.db.old
│   │   └── README.txt
│   ├── database/
│   │   ├── author_repository.py
│   │   ├── book_repository.py
│   │   ├── circulation_repository.py
│   │   ├── patron_repository.py
│   │   ├── repository.py
│   │   ├── schema.py
│   │   ├── seed.py
│   │   └── session.py
│   ├── models/
│   │   ├── author.py
│   │   ├── book.py
│   │   ├── circulation.py
│   │   └── patron.py
│   ├── resources/
│   │   ├── books.py
│   │   ├── patrons.py
│   │   ├── recommendations.py
│   │   └── stats.py
│   ├── prompts/
│   │   ├── book_recommendations.py
│   │   ├── reading_plan.py
│   │   ├── review_generator.py
│   │   └── README.md
│   ├── tools/
│   │   ├── circulation.py
│   │   └── search.py
│   ├── tests/
│   │   └── ... (unit tests)
│   ├── docs/
│   │   ├── DEVELOPMENT.md
│   │   └── TESTING_SETUP.md
│   └── scripts/
│       └── init_database.py
├── CLAUDE.md
└── README.md
```

## 🚀 Virtual Library MCP Server

The main project is a Virtual Library MCP Server that simulates a complete library management system. This server demonstrates all MCP concepts through practical implementation.

### Key Features

- **1000+ Generated Books**: Realistic library catalog with full metadata
- **Author Management**: Track authors and their works
- **Patron System**: Library members with borrowing history
- **Circulation Tools**: Check out, return, and reserve books
- **Real-time Updates**: Subscriptions for availability notifications
- **AI Integration**: Book recommendations and reading plans
- **Progress Tracking**: Monitor long-running operations

### MCP Concepts Demonstrated

1. **Resources**: Browse catalog, view book details, check patron history
   - Basic resources: `/books/list`, `/books/{isbn}`, `/patrons/{id}`
   - URI template resources: `/books/by-author/{author_id}`, `/books/by-genre/{genre}`
2. **Tools**: Check out books, search catalog, manage reservations
3. **Prompts**: Get book recommendations, generate reading plans
4. **Subscriptions**: Real-time book availability updates
5. **Progress Notifications**: Track bulk import operations
6. **Error Handling**: Handle conflicts and validation errors
7. **Sampling**: AI-generated book summaries and reviews

## 🛠️ Technology Stack

- **Python 3.12+**: Latest Python features
- **FastMCP 2.0**: The fast, Pythonic MCP framework
- **Pydantic v2**: Data validation and settings
- **SQLAlchemy**: Database ORM
- **SQLite**: Embedded database
- **uv**: Fast Python package manager
- **pytest**: Testing framework
- **ruff**: Fast Python linter and formatter
- **pyright**: Type checking
- **just**: Command runner

## 📋 Prerequisites

- Python 3.12 or higher
- uv (Python package manager)
- just (command runner)
- Git

## 🚦 Getting Started

1. **Clone the repository**:

   ```bash
   git clone https://github.com/willtech3/mcp-learning.git
   cd mcp-learning
   ```

2. **Set up the development environment**:

   ```bash
   cd virtual-library-mcp
   just install  # Install dependencies
   just test     # Run tests to verify setup
   ```

3. **Review the documentation**:
   - Start with `docs/mcp/01-overview.md` for MCP introduction
   - Check `CLAUDE.md` for development guidelines
   - Review `virtual-library-mcp/docs/DEVELOPMENT.md` for project details

## 🧪 Development Workflow

Once the project is set up, use these commands:

```bash
just install      # Install dependencies
just dev          # Run development server
just test         # Run tests
just lint         # Run ruff linter
just typecheck    # Run pyright type checker
just format       # Format code
```


## 📝 Important Notes

- This is a learning project - code clarity is prioritized over performance
- Tests focus on critical paths rather than exhaustive coverage
- Never commit secrets or sensitive data

## 🎓 Educational Value

This project teaches:

- Model Context Protocol architecture and concepts
- Type-safe programming with Pydantic and pyright
- Database design and ORM usage
- AI/LLM integration patterns

## 📚 Additional Resources

- [Official MCP Documentation](https://modelcontextprotocol.io)
- [MCP GitHub Organization](https://github.com/modelcontextprotocol)
- [FastMCP Framework](https://github.com/jlowin/fastmcp)
- [MCP Community Servers](https://github.com/modelcontextprotocol/servers)

## 📄 License

This educational project is open source. Check LICENSE file for details.
