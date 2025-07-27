# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Critical Rules

1. **Always use defined `just` commands** - Never bypass the justfile commands. Use `just <command>` for all operations.
2. **Never use `git add .`** - Always add files specifically by name to avoid accidentally committing unwanted files.
3. **Never commit secrets** - Double-check that no API keys, tokens, passwords, or sensitive data are included in any commits.
4. **Use MCP Protocol Mentor for MCP implementations** - When implementing MCP features, use the mcp-protocol-mentor agent defined in `.claude/agents/mcp-protocol-mentor.md` (non-negotiable). This ensures proper understanding and implementation of MCP concepts.
5. **Read protocol specs before implementing** - Always use Context7 to read the latest MCP protocol specification from `/modelcontextprotocol/specification` before implementing any MCP features. This ensures compliance with the current protocol version.

## Repository Overview

This is an MCP (Model Context Protocol) learning repository focused on building educational MCP servers. The repository contains comprehensive MCP documentation and implementation plans.

## Current Project: Virtual Library MCP Server

The repository is currently developing a Virtual Library MCP Server as outlined in `virtual-library-implementation-plan.md`. This server demonstrates all MCP concepts through a simulated library management system.

### Technology Stack

- Python 3.12+
- FastMCP 2.0
- Pyright (type checking)
- Pydantic v2 (data validation)
- uv (package manager)
- pytest (testing)
- ruff (linting/formatting)
- just (task runner)
- SQLite with SQLAlchemy

### Development Commands

Since the project uses a justfile for task automation, common commands will be:

```bash
just install      # Install dependencies
just dev          # Run development server
just test         # Run tests
just lint         # Run ruff
just typecheck    # Run pyright
just format       # Format code
```

## MCP Documentation Structure

The `docs/mcp/` directory contains comprehensive MCP documentation:

- `01-overview.md`: Introduction to MCP, key features, industry adoption
- `02-architecture.md`: Technical architecture details
- `03-protocol-specification.md`: JSON-RPC 2.0 protocol details
- `04-transport-layer.md`: Transport options (stdio, Streamable HTTP)
- `05-server-development.md`: Comprehensive server development guide
- `06-client-development.md`: Client implementation guide
- `07-sdk-reference.md`: SDK documentation for all languages
- `09-examples.md`: Example implementations

## Implementation Approach

Follow the 25-step implementation plan in `virtual-library-implementation-plan.md`:

- Phase 1: Project Setup (Steps 1-5)
- Phase 2: Data Models and Database (Steps 6-10)
- Phase 3: MCP Server Core (Steps 11-15)
- Phase 4: Advanced Features (Steps 16-20)
- Phase 5: Testing and Documentation (Steps 21-25)

Each step includes specific tasks and verification criteria.

## Key MCP Concepts to Implement

1. **Resources**: Read-only data endpoints (e.g., `/books/list`, `/authors/{id}`)
2. **Tools**: Actions with side effects (e.g., `checkout_book`, `search_catalog`)
3. **Prompts**: LLM interaction templates (e.g., `recommend_book`)
4. **Subscriptions**: Real-time updates for resource changes
5. **Progress Notifications**: Updates for long-running operations
6. **Error Handling**: Proper JSON-RPC error responses
7. **Sampling**: Server-initiated LLM completions (e.g., `sampling/createMessage` for AI-generated content)

## Testing Approach

- Follow TDD principles (but not necessarily strict Red-Green-Refactor)
- Test behavior, not implementation
- Test public interfaces, not implementation details
- Use pytest fixtures over mocks
- Keep tests simple and straightforward
- Focus on critical paths rather than exhaustive edge cases
- This is a learning project - no specific coverage requirement