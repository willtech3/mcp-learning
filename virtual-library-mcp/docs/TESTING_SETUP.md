# Testing Framework Setup

## Overview

This guide covers the testing framework configuration for the Virtual Library MCP Server, including fixtures and utilities for testing MCP server implementations.

## Key Components

### 1. pytest Configuration (pyproject.toml)

- Test discovery configured with proper paths
- Coverage reporting enabled with HTML output
- Async testing support enabled
- Custom markers for MCP-specific tests

### 2. Test Fixtures (conftest.py)

#### Database Fixtures

- `test_db_path`: Provides isolated temporary database path
- `test_database_url`: SQLAlchemy URL for test database
- `test_db_session`: Database session with automatic cleanup

#### Configuration Fixtures

- `test_config`: Test-specific MCP server configuration
- `minimal_config`: Minimal configuration for basic tests
- `production_like_config`: Production-like settings for integration tests
- `async_test_config`: Async-compatible configuration

#### Environment Fixtures

- `clean_env`: Removes all VIRTUAL_LIBRARY_* environment variables
- `test_env`: Sets up common test environment variables

#### MCP Protocol Testing Fixtures

- `json_rpc_request`: Sample JSON-RPC request
- `mcp_initialization_request`: MCP initialization message
- `sample_book_data`: Test data for book resources
- `sample_patron_data`: Test data for patron resources

#### Utility Functions

- `assert_json_rpc_response()`: Validates JSON-RPC response format
- `assert_mcp_error()`: Validates MCP error responses

### 3. Custom pytest Markers

- `@pytest.mark.mcp_protocol`: For protocol compliance tests
- `@pytest.mark.mcp_transport`: For transport layer tests
- `@pytest.mark.mcp_capabilities`: For capability tests

## MCP-Specific Testing Considerations

### 1. Protocol Compliance

- All fixtures support JSON-RPC 2.0 message validation
- Error responses follow MCP error code standards
- Initialization handshake testing supported

### 2. Resource Isolation

- Each test gets its own database file
- Configuration changes don't affect other tests
- Automatic cleanup prevents test interference

### 3. Async Support

- Full async/await testing capability
- Event loop fixture for complex async scenarios
- Async configuration fixtures available

### 4. Transport Layer Testing

- Fixtures support testing stdio transport
- Extensible for future Streamable HTTP testing
- Mock transport utilities included

## Usage Examples

### Basic Test with Database

```python
def test_with_database(test_db_session):
    # Use test_db_session for database operations
    result = test_db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1
```

### MCP Protocol Test

```python
@pytest.mark.mcp_protocol
def test_json_rpc_format(json_rpc_request):
    # Test with pre-configured JSON-RPC request
    assert json_rpc_request["jsonrpc"] == "2.0"
```

### Async MCP Test

```python
@pytest.mark.asyncio
async def test_async_operation(async_test_config):
    # Test async MCP operations
    await some_async_function(async_test_config)
```

## Running Tests

```bash
# Run all tests
just test

# Run with verbose output
just test-verbose

# Run with coverage report
just test-coverage

# Run only fast tests
just test-fast
```
