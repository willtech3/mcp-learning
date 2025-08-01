# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Critical Rules

1. **Always use defined `just` commands** - Never bypass the justfile commands. Use `just <command>` for all operations.
2. **Never use `git add .`** - Always add files specifically by name to avoid accidentally committing unwanted files.
3. **Never commit secrets** - Double-check that no API keys, tokens, passwords, or sensitive data are included in any commits.
4. **Read protocol specs before implementing** - Always use Context7 to read the latest MCP protocol specification from `/modelcontextprotocol/specification` before implementing any MCP features. This ensures compliance with the current protocol version.
5. **Read the latest FastMCP documentation before implementing** - Always use Context7 to read the latest documentation on the FastMCP library for the version defined in pyproject.toml before implementing any MCP features. This ensures correct library usage. 
6. **Always use feature branches and PRs** - All implementation changes MUST be committed to a feature branch and pushed to a PR for review. Only when a PR is merged can we resolve an issue as complete. Never commit directly to main.
7. **All tests must pass and code must be lint-free** - Before committing to a feature branch and creating a PR, ALL tests MUST pass (`just test`) and ALL linting errors MUST be resolved (`just lint`). No exceptions. This ensures code quality and prevents broken code from entering the codebase.
8. **Virtual environment MUST be active** - The virtual environment MUST ALWAYS be active when working in the virtual-library-mcp directory (non-negotiable). Use `just activate` to get the activation command. This ensures correct Python version (3.12+) and dependencies are used.
9. **Type annotations only where valuable** - Only add type annotations where they provide meaningful value. Keep them for: Pydantic models (required), public API methods, functions that can return None, and complex data structures. Remove them from: obvious local variables (e.g., `x: int = 0`), simple internal functions with obvious returns, and overly complex generics.

## Repository Overview

This is an MCP (Model Context Protocol) learning repository focused on building educational MCP servers. The repository contains protocol documentation as well as implementation specific documentation in the virtual-library-mcp subdirectories.

## Current Project: Virtual Library MCP Server

The repository is developing a Virtual Library MCP Server that demonstrates all MCP concepts through a simulated library management system. Implementation is tracked through GitHub Issues organized into 5 epic phases.

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
- `08-security.md`: MCP Security documentation
- `09-examples.md`: Example implementations

## Key MCP Concepts to Implement

1. **Resources**: Read-only data endpoints ✅ IMPLEMENTED
   - Basic resources: `/books/list`, `/books/{isbn}`, `/patrons/{id}`
   - URI template resources: `/books/by-author/{author_id}`, `/books/by-genre/{genre}`
2. **Tools**: Actions with side effects (e.g., `checkout_book`, `search_catalog`)
3. **Prompts**: LLM interaction templates (e.g., `recommend_book`)
4. **Subscriptions**: Real-time updates for resource changes
5. **Progress Notifications**: Updates for long-running operations
6. **Error Handling**: Proper JSON-RPC error responses
7. **Sampling**: Server-initiated LLM completions (e.g., `sampling/createMessage` for AI-generated content)
8. **Elicitation**: Server-initiated request for more specific information from the client (if available and if any major clients support it).

## Testing Approach

- Follow TDD principles (but not necessarily strict Red-Green-Refactor)
- Test behavior, not implementation
- Test public interfaces, not implementation details
- Use pytest fixtures over mocks
- Keep tests simple and straightforward
- Focus on critical paths rather than exhaustive edge cases
- This is a learning project - no specific coverage requirement

## Date/Time Handling

- **Use local timezone throughout** - Since this is a learning project for MCP concepts, we'll use local timezone (datetime.now() without timezone) for simplicity
- This avoids timezone complexity while focusing on MCP protocol implementation
- All datetime operations should use local time consistently
