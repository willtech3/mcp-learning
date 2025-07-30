# Development Setup Guide

This guide explains the development tools configuration for the Virtual Library MCP Server.

## Tool Configuration Overview

### 1. Ruff (Linting & Formatting)

**Purpose**: Ensures consistent code style and catches common bugs before they reach production.

**MCP-Specific Configuration**:
- **Line length 100**: Accommodates longer MCP method names like `handle_resources_list_request`
- **Comprehensive rule sets**: Includes async-specific rules crucial for MCP servers
- **Double quotes**: Matches JSON protocol examples
- **Strict error handling**: Ensures proper exception handling for protocol errors

Key rules for MCP development:
- `ASYNC`: Catches async/await mistakes
- `LOG`: Ensures consistent protocol debugging
- `TRY`: Enforces proper error handling
- `ARG`: Catches unused protocol parameters

### 2. Pyright (Type Checking)

**Purpose**: Ensures type safety for JSON-RPC protocol compliance.

**MCP-Specific Configuration**:
- **Strict mode**: Maximum type safety for protocol messages
- **Full error reporting**: Catches all potential type issues
- **Async safety**: Prevents coroutine-related bugs
- **Optional handling**: Ensures proper handling of nullable JSON fields

Critical for MCP because:
- JSON-RPC 2.0 has strict message formats
- Type errors lead to protocol violations
- Async operations require careful type handling

### 3. Pre-commit Hooks

**Purpose**: Automated quality checks before every commit.

**Setup Instructions**:

```bash
# Install pre-commit
uv pip install pre-commit

# Install the git hooks
pre-commit install

# Run on all files (initial setup)
pre-commit run --all-files

# Update hooks to latest versions
pre-commit autoupdate
```

**MCP-Specific Hooks**:
- **Security scanning**: Prevents committing API keys or secrets
- **Type checking**: Catches protocol violations
- **Format validation**: Ensures JSON/YAML configs are valid
- **Large file prevention**: Avoids committing logs or data dumps

### 4. .gitignore Configuration

**Purpose**: Prevents committing sensitive or generated files.

**MCP-Specific Exclusions**:
- Environment files with secrets (`.env`)
- Runtime files (`mcp-server.pid`, `mcp-server.sock`)
- Generated protocol stubs
- SSL certificates and keys
- Database files (except schemas)

## Development Workflow

### 1. Before Starting Development

```bash
# Install dependencies
just install

# Initialize database with test data
just db-seed

# Verify tool configuration
just lint
just typecheck
```

### Database Setup

The Virtual Library MCP Server uses a SQLite database populated with realistic test data:

```bash
# Seed database with test data
just db-seed
```

This generates:
- **120+ authors** with biographical information
- **1200+ books** across 20 genres with valid ISBNs  
- **60+ patrons** with varying membership statuses
- **500+ circulation records** including checkouts, returns, and reservations

The seed script (`database/seed.py`) demonstrates:
- Progress reporting for long operations (MCP progress feature)
- Realistic data relationships for testing MCP resources and tools
- State management across multiple tables for subscriptions

### 2. Running the MCP Server

```bash
# Start the MCP server with stdio transport
just dev

# The server will output:
# - Startup banner with version info
# - "MCP Server ready and waiting for connections..."
# - JSON-RPC messages will flow via stdin/stdout
# - Logs appear on stderr

# To test the server, you'll need an MCP client
# The server expects JSON-RPC messages on stdin
```

### 3. During Development

```bash
# Run tests continuously
just test-watch

# Check types as you code
just typecheck

# View real-time logs (debug mode)
just dev-debug
```

### 3. Before Committing

```bash
# Run all quality checks
just check

# Or let pre-commit handle it automatically
git commit -m "feat: implement resource handler"
```

### 4. Common Issues and Solutions

#### Type Checking Errors

If you see type errors related to MCP protocol:
1. Ensure all handler parameters are typed
2. Use proper Optional[T] for nullable JSON fields
3. Add type annotations to all return values

Example:
```python
# Bad: Missing types
async def handle_request(request):
    return {"result": "ok"}

# Good: Fully typed
async def handle_request(request: JsonRpcRequest) -> JsonRpcResponse:
    return JsonRpcResponse(result={"status": "ok"})
```

#### Linting Errors

Common fixes:
- Use `async with` for context managers in async functions
- Always `await` coroutines
- Use proper logging instead of print statements

#### Pre-commit Failures

If pre-commit fails:
1. Read the specific error message
2. Fix the issue (hooks often auto-fix)
3. Stage the fixes: `git add -u`
4. Retry the commit

## Best Practices

1. **Type Everything**: Every function parameter and return value
2. **Handle Errors**: Use proper MCP error codes
3. **Log Appropriately**: Use structured logging for debugging
4. **Test Thoroughly**: Write tests for all protocol handlers
5. **Document Code**: Especially protocol-specific logic

## Getting Help

- Run `just help` for available commands
- Check hook output for specific error fixes
- Consult MCP documentation in `docs/mcp/`
- Review examples in `docs/mcp/09-examples.md`