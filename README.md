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
├── docs/mcp/                    # Comprehensive MCP documentation
│   ├── 01-overview.md          # Introduction to MCP
│   ├── 02-architecture.md      # Technical architecture
│   ├── 03-protocol-specification.md  # Protocol details
│   ├── 04-transport-layer.md   # Transport mechanisms
│   ├── 05-server-development.md # Server development guide
│   ├── 06-client-development.md # Client development guide
│   ├── 07-sdk-reference.md     # SDK documentation
│   ├── 08-security.md          # Security considerations
│   └── 09-examples.md          # Example implementations
├── virtual-library-mcp/         # Virtual Library MCP Server
│   ├── src/                    # Source code
│   ├── tests/                  # Test suite with fixtures
│   ├── docs/                   # Project documentation
│   ├── pyproject.toml          # Project configuration
│   └── justfile                # Task automation
├── .claude/                     # Claude Code configuration
│   ├── agents/                  # Custom agents
│   │   └── mcp-protocol-mentor.md  # MCP implementation guidance
│   ├── commands/                # Custom commands
│   │   └── review_prs.md       # PR review command
│   └── settings.local.json     # Local settings
├── CLAUDE.md                    # Claude Code guidance file
└── README.md                    # This file
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

4. **Follow the implementation roadmap**:
   The project is organized into 5 epic phases with 25 total implementation steps tracked as GitHub issues:
   - **[Epic #1](https://github.com/willtech3/mcp-learning/issues/1)**: Phase 1 - Foundation (Project Setup) ✅ COMPLETE
   - **[Epic #2](https://github.com/willtech3/mcp-learning/issues/2)**: Phase 2 - Data Layer (Models & Database) ✅ COMPLETE
   - **[Epic #3](https://github.com/willtech3/mcp-learning/issues/3)**: Phase 3 - Core MCP (Basic Server)
   - **[Epic #4](https://github.com/willtech3/mcp-learning/issues/4)**: Phase 4 - Advanced MCP (Subscriptions, Progress, Prompts)
   - **[Epic #5](https://github.com/willtech3/mcp-learning/issues/5)**: Phase 5 - Production Ready (Testing & Documentation)

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

## 📖 Learning Path

1. **Understand MCP**: Read the documentation in `docs/mcp/`
2. **Follow the Issues**: Work through each GitHub issue in order, starting with [Issue #6](https://github.com/willtech3/mcp-learning/issues/6)
3. **Test Everything**: Write tests as you implement features
4. **Experiment**: Use the server to explore MCP capabilities
5. **Extend**: Add your own features once comfortable

## 🤝 Contributing

This is a learning repository. Feel free to:

- Report issues or suggestions
- Share your learning experiences
- Contribute improvements to documentation
- Add example use cases
- Pick up any open issue and submit a PR

## 📝 Important Notes

- This is a learning project - code clarity is prioritized over performance
- Tests focus on critical paths rather than exhaustive coverage
- The MCP Protocol Mentor agent (`.claude/agents/mcp-protocol-mentor.md`) provides implementation guidance
- Never commit secrets or sensitive data

## 🎓 Educational Value

This project teaches:

- Model Context Protocol architecture and concepts
- Building production-ready Python applications
- Type-safe programming with Pydantic and pyright
- Test-driven development practices
- Database design and ORM usage
- Real-time systems with subscriptions
- AI/LLM integration patterns

## 📚 Additional Resources

- [Official MCP Documentation](https://modelcontextprotocol.io)
- [MCP GitHub Organization](https://github.com/modelcontextprotocol)
- [FastMCP Framework](https://github.com/jlowin/fastmcp)
- [MCP Community Servers](https://github.com/modelcontextprotocol/servers)

## 📄 License

This educational project is open source. Check LICENSE file for details.
