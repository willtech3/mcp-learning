# Model Context Protocol (MCP) - Server Development

## Table of Contents
- [Overview](#overview)
- [Getting Started](#getting-started)
- [Server Architecture](#server-architecture)
- [Core Concepts](#core-concepts)
- [Resources](#resources)
- [Tools](#tools)
- [Prompts](#prompts)
- [Server Lifecycle](#server-lifecycle)
- [Error Handling](#error-handling)
- [Testing](#testing)
- [Deployment](#deployment)
- [Best Practices](#best-practices)

## Overview

MCP servers are programs that expose data (resources) and functionality (tools) to AI applications through the Model Context Protocol. This guide covers everything you need to know to build robust, scalable MCP servers.

## Getting Started

### Prerequisites
- Python 3.12+ 
- Basic understanding of JSON-RPC 2.0
- Familiarity with async programming
- uv package manager (recommended)

### Quick Start

```bash
# Install MCP Python SDK with CLI tools using uv
uv add "mcp[cli]"

# Or using pip
pip install "mcp[cli]"

# Create a new server file
touch server.py
```

### Minimal Server Example

```python
from mcp.server.fastmcp import FastMCP

# Create server instance
mcp = FastMCP(
    name="my-first-server",
    version="1.0.0"
)

# Add a simple resource
@mcp.resource("greeting://hello")
async def hello_resource():
    """A friendly greeting resource"""
    return "Hello from MCP!"

# List all resources
@mcp.list_resources()
async def list_resources():
    """List available resources"""
    return [
        {
            "uri": "greeting://hello",
            "name": "Hello Message",
            "description": "A friendly greeting",
            "mimeType": "text/plain"
        }
    ]

# Start the server
if __name__ == "__main__":
    mcp.run()
```

## Server Architecture

### Component Overview
```
┌─────────────────────────────────────────┐
│            MCP Server                    │
├─────────────────────────────────────────┤
│  ┌─────────────────────────────────┐    │
│  │      Request Handlers            │    │
│  │  ┌──────────┐  ┌──────────┐    │    │
│  │  │Resources │  │  Tools   │    │    │
│  │  └──────────┘  └──────────┘    │    │
│  │  ┌──────────┐  ┌──────────┐    │    │
│  │  │ Prompts  │  │ Sampling │    │    │
│  │  └──────────┘  └──────────┘    │    │
│  └─────────────────────────────────┘    │
│                                          │
│  ┌─────────────────────────────────┐    │
│  │     Transport Layer              │    │
│  │  (stdio, HTTP, WebSocket)       │    │
│  └─────────────────────────────────┘    │
│                                          │
│  ┌─────────────────────────────────┐    │
│  │     Business Logic               │    │
│  │  (Database, APIs, Files, etc)   │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

### Request Flow
1. **Transport receives message** → JSON-RPC decoding
2. **Router identifies handler** → Method dispatch
3. **Handler processes request** → Business logic
4. **Response formatting** → JSON-RPC encoding
5. **Transport sends response** → Client receives

## Core Concepts

### Server Configuration
```python
from typing import Dict, Optional
from pydantic import BaseModel

class ServerCapabilities(BaseModel):
    """Server capability configuration"""
    resources: Optional[Dict] = {}
    tools: Optional[Dict] = {}
    prompts: Optional[Dict] = {}
    logging: Optional[Dict] = {}
    experimental: Optional[Dict] = {}

class ServerConfig(BaseModel):
    """Server configuration"""
    name: str  # Server identifier
    version: str  # Server version
    capabilities: ServerCapabilities = ServerCapabilities()
```

### Request Handlers
Request handlers are the core of your server implementation:

```python
from mcp.server.fastmcp import FastMCP
from typing import Dict, Any

mcp = FastMCP()

# FastMCP handles initialization automatically
# You can customize it by overriding the handler
@mcp.handler("initialize")
async def custom_initialize(request: Dict[str, Any]) -> Dict[str, Any]:
    """Custom initialization handler"""
    return {
        "protocolVersion": "2025-06-18",
        "capabilities": mcp.get_capabilities(),
        "serverInfo": {
            "name": mcp.name,
            "version": mcp.version,
        },
    }
```

## Resources

Resources expose data that clients can read. Think of them as GET endpoints in a REST API.

### Basic Resource Implementation
```python
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP()

# Expose multiple resources
@mcp.resource("file:///data/config.json")
async def config_resource():
    """Server configuration file"""
    config = await read_config_file()
    return json.dumps(config, indent=2)

@mcp.resource("db://users")
async def users_resource():
    """All user records"""
    users = await query_database("SELECT * FROM users")
    return json.dumps(users)

# List all available resources
@mcp.list_resources()
async def list_all_resources():
    """List available resources"""
    return [
        {
            "uri": "file:///data/config.json",
            "name": "Configuration",
            "description": "Server configuration file",
            "mimeType": "application/json",
        },
        {
            "uri": "db://users",
            "name": "User Database",
            "description": "All user records",
            "mimeType": "application/json",
        },
    ]
```

### Dynamic Resources with Templates
```python
import re
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP()

# Handle dynamic resource URIs
@mcp.resource_handler()
async def handle_dynamic_resources(uri: str) -> str:
    """Handle templated resource URIs"""
    
    # Parse URI template for users
    user_match = re.match(r"^db://users/(\d+)$", uri)
    if user_match:
        user_id = user_match.group(1)
        user = await query_database(
            "SELECT * FROM users WHERE id = ?",
            [user_id]
        )
        return json.dumps(user)
    
    # Add more patterns as needed
    raise ValueError(f"Resource not found: {uri}")

# Advertise templated resources
@mcp.list_resources()
async def list_templated_resources():
    """Include templated resources in listing"""
    return [
        {
            "uri": "db://users/{userId}",
            "name": "User Details",
            "description": "Get specific user information",
            "mimeType": "application/json",
        }
    ]
```

### Resource Subscriptions
```python
import uuid
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP

mcp = FastMCP()

# Track subscriptions
subscriptions: Dict[str, Any] = {}

@mcp.subscription_handler("resources/subscribe")
async def subscribe_to_resource(uri: str) -> Dict[str, str]:
    """Subscribe to resource changes"""
    subscription_id = str(uuid.uuid4())
    
    # Set up file watcher, database trigger, etc.
    async def on_change(change: Dict[str, Any]):
        # Send notification on change
        await mcp.send_notification(
            "notifications/resources/updated",
            {
                "uri": uri,
                "subscriptionId": subscription_id,
                "change": change,
            }
        )
    
    watcher = await watch_resource(uri, on_change)
    subscriptions[subscription_id] = watcher
    
    return {"subscriptionId": subscription_id}

@mcp.subscription_handler("resources/unsubscribe")
async def unsubscribe_from_resource(subscription_id: str) -> Dict:
    """Unsubscribe from resource changes"""
    if subscription_id in subscriptions:
        watcher = subscriptions[subscription_id]
        await watcher.stop()
        del subscriptions[subscription_id]
    return {}
```

## Tools

Tools provide executable functionality with potential side effects. Think of them as POST endpoints in a REST API.

### Basic Tool Implementation
```python
from mcp.server.fastmcp import FastMCP
from typing import Dict, Any
import aiofiles

mcp = FastMCP()

@mcp.tool(
    name="create_file",
    description="Create a new file with content",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path",
            },
            "content": {
                "type": "string",
                "description": "File content",
            },
        },
        "required": ["path", "content"],
    }
)
async def create_file(path: str, content: str) -> str:
    """Create a new file with content"""
    async with aiofiles.open(path, 'w') as f:
        await f.write(content)
    return f"File created at {path}"

@mcp.tool(
    name="send_email",
    description="Send an email",
    parameters={
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "format": "email",
            },
            "subject": {
                "type": "string",
            },
            "body": {
                "type": "string",
            },
        },
        "required": ["to", "subject", "body"],
    }
)
async def send_email(to: str, subject: str, body: str) -> str:
    """Send an email"""
    result = await send_email_async(to, subject, body)
    return f"Email sent to {to}"
```

### Advanced Tool Features

#### Progress Reporting
```python
from mcp.server.fastmcp import FastMCP
from typing import List, Any

mcp = FastMCP()

@mcp.tool(
    name="process_large_dataset",
    description="Process a large dataset with progress updates"
)
async def process_large_dataset(items: List[Any]) -> str:
    """Process dataset with progress notifications"""
    total_items = len(items)
    
    for i, item in enumerate(items):
        # Process item
        await process_item(item)
        
        # Send progress notification
        progress = round((i + 1) / total_items * 100)
        await mcp.send_progress(
            progress=progress,
            message=f"Processing item {i + 1} of {total_items}"
        )
    
    return f"Processed {total_items} items successfully"
```

#### Streaming Results
```python
from mcp.server.fastmcp import FastMCP
from typing import AsyncIterator

mcp = FastMCP()

@mcp.tool(
    name="stream_logs",
    description="Stream log entries matching filter"
)
async def stream_logs(filter: str) -> str:
    """Stream logs with intermediate results"""
    results = []
    
    async for log in create_log_stream(filter):
        results.append(log)
        
        # Send intermediate results
        await mcp.send_notification(
            "notifications/tools/output",
            {
                "toolName": "stream_logs",
                "output": {
                    "type": "text",
                    "text": log,
                },
            }
        )
    
    return "\n".join(results)
```

## Prompts

Prompts provide reusable templates for LLM interactions, allowing servers to guide AI behavior.

### Basic Prompt Implementation
```python
from mcp.server.fastmcp import FastMCP
from typing import Dict, Any, Optional
import json

mcp = FastMCP()

@mcp.prompt(
    name="analyze_code",
    description="Analyze code for issues and improvements",
    parameters=[
        {
            "name": "code",
            "description": "The code to analyze",
            "required": True,
        },
        {
            "name": "language",
            "description": "Programming language",
            "required": False,
        },
    ]
)
async def analyze_code_prompt(code: str, language: Optional[str] = None) -> str:
    """Generate code analysis prompt"""
    lang = language or "code"
    return f"""Please analyze the following {lang} and provide:
1. Potential bugs or issues
2. Performance improvements
3. Code style suggestions
4. Security considerations

Code:
```{language or ""}
{code}
```"""

@mcp.prompt(
    name="generate_report",
    description="Generate a report from data",
    parameters=[
        {
            "name": "data",
            "description": "The data to analyze",
            "required": True,
        },
        {
            "name": "format",
            "description": "Report format (pdf, html, markdown)",
            "required": False,
        },
    ]
)
async def generate_report_prompt(data: Dict[str, Any], format: Optional[str] = None) -> str:
    """Generate report generation prompt"""
    analysis_result = await analyze_data(data)
    fmt = format or "markdown"
    
    return f"""Generate a comprehensive report in {fmt} format based on the following data analysis:

{json.dumps(analysis_result, indent=2)}

Include:
- Executive summary
- Key findings
- Detailed analysis
- Recommendations"""
```

## Server Lifecycle

### Initialization Phase
```python
from mcp.server.fastmcp import FastMCP
from typing import Dict, Any

class MyMCPServer:
    def __init__(self):
        self.mcp = FastMCP(
            name="my-mcp-server",
            version="1.0.0"
        )
        self.setup_handlers()
    
    def setup_handlers(self):
        @self.mcp.initialization_handler()
        async def handle_initialize(request: Dict[str, Any]) -> Dict[str, Any]:
            """Custom initialization handler"""
            # Validate client capabilities
            client_version = request["params"].get("protocolVersion")
            if not self.is_version_supported(client_version):
                raise ValueError(f"Unsupported protocol version: {client_version}")
            
            # Initialize server resources
            await self.connect_database()
            await self.load_configuration()
            
            # Return server capabilities
            return {
                "protocolVersion": "2025-06-18",
                "capabilities": {
                    "resources": {
                        "subscribe": True,
                        "templates": True,
                    },
                    "tools": {
                        "streaming": True,
                    },
                    "prompts": {},
                    "logging": {
                        "levels": ["debug", "info", "warn", "error"],
                    },
                },
                "serverInfo": {
                    "name": self.mcp.name,
                    "version": self.mcp.version,
                },
            }
    
    def is_version_supported(self, version: str) -> bool:
        """Check if protocol version is supported"""
        return version in ["2025-06-18", "2025-01-01"]
    
    async def connect_database(self):
        """Connect to database"""
        pass
    
    async def load_configuration(self):
        """Load server configuration"""
        pass
```

### Shutdown Handling
```python
import signal
import asyncio
from mcp.server.fastmcp import FastMCP

mcp = FastMCP()

@mcp.shutdown_handler()
async def handle_shutdown():
    """Clean shutdown handler"""
    # Clean up resources
    await close_database()
    await save_state()
    
    # Stop background tasks
    await cancel_all_subscriptions()
    await stop_background_jobs()

# Handle process termination
def setup_signal_handlers():
    """Setup graceful shutdown on signals"""
    async def shutdown_handler(sig):
        print(f"Received signal {sig}, shutting down...")
        await mcp.shutdown()
        asyncio.get_event_loop().stop()
    
    for sig in [signal.SIGINT, signal.SIGTERM]:
        signal.signal(
            sig,
            lambda s, f: asyncio.create_task(shutdown_handler(s))
        )

if __name__ == "__main__":
    setup_signal_handlers()
    mcp.run()
```

## Error Handling

### Error Response Format
```python
from enum import IntEnum
from typing import Optional, Any

class ErrorCode(IntEnum):
    """Standard JSON-RPC and MCP error codes"""
    # Standard JSON-RPC errors
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    
    # MCP-specific errors
    RESOURCE_NOT_FOUND = -32001
    RESOURCE_ACCESS_DENIED = -32002
    TOOL_EXECUTION_FAILED = -32003
    INVALID_TOOL_ARGUMENTS = -32004
    PROMPT_NOT_FOUND = -32005

class MCPError(Exception):
    """MCP-specific error with code and data"""
    def __init__(self, message: str, code: ErrorCode, data: Optional[Any] = None):
        super().__init__(message)
        self.code = code
        self.data = data
```

### Error Handling Best Practices
```python
import asyncio
import logging
from mcp.server.fastmcp import FastMCP
from typing import Dict, Any

mcp = FastMCP()
logger = logging.getLogger(__name__)

@mcp.tool("example_tool")
async def example_tool_with_error_handling(**kwargs) -> str:
    """Example tool with comprehensive error handling"""
    tool_name = "example_tool"
    
    try:
        # Validate tool exists (in real implementation)
        tool_def = await get_tool_definition(tool_name)
        if not tool_def:
            raise MCPError(
                f"Tool not found: {tool_name}",
                ErrorCode.METHOD_NOT_FOUND
            )
        
        # Validate arguments
        validation = validate_arguments(kwargs, tool_def.input_schema)
        if not validation.valid:
            raise MCPError(
                "Invalid tool arguments",
                ErrorCode.INVALID_TOOL_ARGUMENTS,
                {"errors": validation.errors}
            )
        
        # Execute tool with timeout
        result = await asyncio.wait_for(
            execute_tool(tool_name, kwargs),
            timeout=30.0
        )
        
        return result
        
    except asyncio.TimeoutError:
        logger.error(f"Tool execution timeout: {tool_name}")
        raise MCPError(
            f"Tool execution timeout: {tool_name}",
            ErrorCode.TOOL_EXECUTION_FAILED
        )
    
    except MCPError:
        # Re-raise MCP errors
        raise
    
    except Exception as error:
        # Log error for debugging
        logger.error(f"Tool execution failed: {tool_name}", exc_info=True)
        
        # Wrap unexpected errors
        raise MCPError(
            "Internal server error",
            ErrorCode.INTERNAL_ERROR,
            {
                "tool": tool_name,
                "message": str(error)
            }
        )
```

## Testing

### Unit Testing
```python
import pytest
import pytest_asyncio
from mcp.server.fastmcp.testing import TestClient
from typing import AsyncGenerator
import json

@pytest_asyncio.fixture
async def test_client() -> AsyncGenerator[TestClient, None]:
    """Create test client for MCP server"""
    from myserver import mcp  # Import your server instance
    
    async with TestClient(mcp) as client:
        yield client

class TestMCPServer:
    """Test suite for MCP server"""
    
    async def test_list_resources(self, test_client: TestClient):
        """Test listing available resources"""
        response = await test_client.request("resources/list")
        
        assert len(response["resources"]) == 2
        assert response["resources"][0]["uri"] == "file:///config.json"
    
    async def test_read_resource(self, test_client: TestClient):
        """Test reading resource content"""
        response = await test_client.request(
            "resources/read",
            {"uri": "file:///config.json"}
        )
        
        assert response["contents"][0]["mimeType"] == "application/json"
        content = json.loads(response["contents"][0]["text"])
        assert "version" in content
    
    async def test_execute_tool(self, test_client: TestClient):
        """Test tool execution"""
        response = await test_client.request(
            "tools/call",
            {
                "name": "create_file",
                "arguments": {
                    "path": "/tmp/test.txt",
                    "content": "Hello, MCP!",
                }
            }
        )
        
        assert "File created" in response["content"][0]["text"]
    
    async def test_validate_tool_arguments(self, test_client: TestClient):
        """Test tool argument validation"""
        with pytest.raises(Exception, match="Invalid tool arguments"):
            await test_client.request(
                "tools/call",
                {
                    "name": "create_file",
                    "arguments": {
                        # Missing required 'content' field
                        "path": "/tmp/test.txt",
                    }
                }
            )
```

### Integration Testing
```python
import asyncio
import json
import pytest
from mcp.server.fastmcp.testing import TestClient

class TestMCPServerIntegration:
    """Integration tests for MCP server"""
    
    async def test_handle_concurrent_requests(self, test_client: TestClient):
        """Test handling concurrent requests"""
        # Create 10 concurrent requests
        tasks = [
            test_client.request(
                "tools/call",
                {
                    "name": "process_data",
                    "arguments": {"id": i}
                }
            )
            for i in range(10)
        ]
        
        results = await asyncio.gather(*tasks)
        assert len(results) == 10
        
        for i, result in enumerate(results):
            assert f"Processed: {i}" in result["content"][0]["text"]
    
    async def test_maintain_state_across_requests(self, test_client: TestClient):
        """Test state persistence across requests"""
        # Create a session
        create_response = await test_client.request(
            "tools/call",
            {
                "name": "create_session",
                "arguments": {"userId": "test-user"}
            }
        )
        
        session_data = json.loads(create_response["content"][0]["text"])
        session_id = session_data["sessionId"]
        
        # Use the session
        use_response = await test_client.request(
            "tools/call",
            {
                "name": "use_session",
                "arguments": {"sessionId": session_id}
            }
        )
        
        assert "test-user" in use_response["content"][0]["text"]
```

## Deployment

### Docker Deployment
```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Security: Run as non-root user
RUN addgroup --gid 1001 mcp && \
    adduser --uid 1001 --gid 1001 --disabled-password --gecos "" mcp
USER mcp

EXPOSE 3000

CMD ["python", "server.py"]
```

### Docker Compose
```yaml
version: '3.8'

services:
  mcp-server:
    build: .
    environment:
      - NODE_ENV=production
      - DATABASE_URL=postgresql://postgres:password@db:5432/mcp
    ports:
      - "3000:3000"
    depends_on:
      - db
    restart: unless-stopped
    
  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=mcp
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data
      
volumes:
  postgres_data:
```

### Production Considerations

#### Health Checks
```python
import psutil
import time
from mcp.server.fastmcp import FastMCP

mcp = FastMCP()

@mcp.tool(
    name="health",
    description="Check server health status"
)
async def health_check() -> dict:
    """Health check endpoint"""
    # Check database connection
    db_status = await check_database_connection()
    
    # Check memory usage
    memory = psutil.Process().memory_info()
    memory_status = "healthy" if memory.rss < 500 * 1024 * 1024 else "warning"
    
    checks = {
        "server": "healthy",
        "database": db_status,
        "memory": memory_status,
        "uptime": time.time() - SERVER_START_TIME,
    }
    
    # Determine overall health
    is_healthy = all(
        status == "healthy" or isinstance(status, (int, float))
        for status in checks.values()
    )
    
    return {
        "status": "healthy" if is_healthy else "degraded",
        "checks": checks,
    }
```

#### Monitoring
```python
import time
from typing import Dict, Any, Callable
from prometheus_client import Counter, Histogram, generate_latest
from mcp.server.fastmcp import FastMCP

# Define metrics
request_counter = Counter(
    'mcp_requests_total',
    'Total MCP requests',
    ['method', 'status']
)

request_duration = Histogram(
    'mcp_request_duration_seconds',
    'MCP request duration',
    ['method']
)

mcp = FastMCP()

# Middleware for tracking metrics
@mcp.middleware
async def track_metrics(request: Dict[str, Any], handler: Callable) -> Any:
    """Track request metrics"""
    start_time = time.time()
    method = request.get('method', 'unknown')
    
    try:
        response = await handler(request)
        request_counter.labels(method=method, status='success').inc()
        return response
    except Exception as error:
        request_counter.labels(method=method, status='error').inc()
        raise error
    finally:
        duration = time.time() - start_time
        request_duration.labels(method=method).observe(duration)

# Expose metrics endpoint
@mcp.tool(
    name="metrics",
    description="Get server metrics"
)
async def get_metrics() -> str:
    """Return Prometheus metrics"""
    return generate_latest().decode('utf-8')
```

## Best Practices

### 1. **Resource Design**
- Use clear, consistent URI schemes
- Provide meaningful descriptions
- Include appropriate MIME types
- Support pagination for large datasets

### 2. **Tool Design**
- Keep tools focused and single-purpose
- Validate all inputs thoroughly
- Provide clear error messages
- Include progress for long operations

### 3. **Performance**
- Implement caching where appropriate
- Use streaming for large responses
- Optimize database queries
- Monitor resource usage

### 4. **Security**
- Validate all inputs
- Implement rate limiting
- Use least privilege principle
- Audit sensitive operations

### 5. **Reliability**
- Implement graceful error handling
- Add retry logic for external services
- Use circuit breakers
- Provide health endpoints

### 6. **Documentation**
- Document all resources and tools
- Provide clear examples
- Keep schemas up to date
- Version your API

### Example: Well-Designed Tool
```python
from mcp.server.fastmcp import FastMCP
from typing import Optional, Dict, Any

mcp = FastMCP()

@mcp.tool(
    name="query_database",
    description="Execute a safe database query with pagination",
    parameters={
        "type": "object",
        "properties": {
            "table": {
                "type": "string",
                "enum": ["users", "orders", "products"],
                "description": "Table to query",
            },
            "filters": {
                "type": "object",
                "description": "Filter conditions",
                "additionalProperties": {
                    "type": "string",
                },
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "default": 10,
                "description": "Number of results to return",
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "default": 0,
                "description": "Number of results to skip",
            },
        },
        "required": ["table"],
    }
)
async def query_database(
    table: str,
    filters: Optional[Dict[str, Any]] = None,
    limit: int = 10,
    offset: int = 0
) -> Dict[str, Any]:
    """Execute a safe database query with pagination"""
    # Implementation would go here
    pass
```

## Next Steps

- **Client Development**: Learn to build MCP clients
- **SDK Reference**: Explore SDK capabilities
- **Examples**: See complete server implementations
- **Security**: Implement secure MCP servers