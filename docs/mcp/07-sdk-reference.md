# Model Context Protocol (MCP) - SDK Reference

## Table of Contents
- [Overview](#overview)
- [Official SDKs](#official-sdks)
- [TypeScript/JavaScript SDK](#typescriptjavascript-sdk)
- [Python SDK](#python-sdk)
- [C# SDK](#c-sdk)
- [Ruby SDK](#ruby-sdk)
- [Java SDK](#java-sdk)
- [Go SDK](#go-sdk)
- [SDK Architecture](#sdk-architecture)
- [Common Patterns](#common-patterns)
- [SDK Comparison](#sdk-comparison)
- [Contributing to SDKs](#contributing-to-sdks)

## Overview

The Model Context Protocol provides official SDKs in multiple programming languages to simplify the development of MCP clients and servers. Each SDK implements the full MCP specification while providing idiomatic APIs for its respective language.

### SDK Goals
- **Simplicity**: Easy to get started with minimal boilerplate
- **Type Safety**: Leverage language features for compile-time safety
- **Performance**: Efficient implementation of the protocol
- **Flexibility**: Support all transport types and features
- **Compatibility**: Maintain protocol version compatibility

## Official SDKs

| Language | Repository | Package | Status |
|----------|------------|---------|---------|
| TypeScript/JavaScript | [modelcontextprotocol/typescript-sdk](https://github.com/modelcontextprotocol/typescript-sdk) | `@modelcontextprotocol/sdk` | Stable |
| Python | [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) | `mcp` | Stable |
| C# | [modelcontextprotocol/csharp-sdk](https://github.com/modelcontextprotocol/csharp-sdk) | `ModelContextProtocol` | Stable |
| Ruby | [modelcontextprotocol/ruby-sdk](https://github.com/modelcontextprotocol/ruby-sdk) | `mcp` | Beta |
| Java | [modelcontextprotocol/java-sdk](https://github.com/modelcontextprotocol/java-sdk) | `com.modelcontextprotocol` | Beta |
| Go | [modelcontextprotocol/go-sdk](https://github.com/modelcontextprotocol/go-sdk) | `github.com/modelcontextprotocol/go-sdk` | Alpha |

## Python SDK (Primary)

### Installation
```bash
# Install with CLI tools (recommended)
pip install "mcp[cli]"
# or
poetry add "mcp[cli]"
# or
pipenv install "mcp[cli]"
# or using uv
uv add "mcp[cli]"
```

### Core Components

#### Server API with FastMCP
```python
from mcp.server.fastmcp import FastMCP

# Server configuration
mcp = FastMCP(
    name="example-server",
    version="1.0.0"
)

# Resource handler
@mcp.resource("example://resource")
async def example_resource():
    """An example resource"""
    return "Example content"

# Tool handler
@mcp.tool(
    name="example_tool",
    description="An example tool",
    parameters={
        "type": "object",
        "properties": {
            "message": {"type": "string"}
        },
        "required": ["message"]
    }
)
async def example_tool(message: str) -> str:
    """Execute example tool"""
    return f"Processed: {message}"

# Start server
if __name__ == "__main__":
    mcp.run()
```

#### Client API
```python
from mcp import Client
from mcp.client.stdio import StdioClientTransport
import asyncio

# Client configuration
client = Client(
    name="example-client",
    version="1.0.0"
)

# Connect to server
async def main():
    transport = StdioClientTransport(
        command="python",
        args=["server.py"]
    )
    
    await client.connect(transport)
    
    # Make requests
    resources = await client.request("resources/list")
    print("Resources:", resources)

if __name__ == "__main__":
    asyncio.run(main())
```

#### Transport Options
```python
# stdio transport
from mcp.server.stdio import StdioServerTransport
from mcp.client.stdio import StdioClientTransport

# HTTP/SSE transport
from mcp.server.http import HttpServerTransport
from mcp.client.http import HttpClientTransport

# WebSocket transport (coming soon)
from mcp.server.websocket import WebSocketServerTransport
from mcp.client.websocket import WebSocketClientTransport
```

#### Type Definitions
```python
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass
from pydantic import BaseModel

# Resource types
@dataclass
class Resource:
    uri: str
    name: str
    description: Optional[str] = None
    mimeType: Optional[str] = None

@dataclass
class ResourceContent:
    uri: str
    mimeType: Optional[str] = None
    text: Optional[str] = None
    blob: Optional[bytes] = None

# Tool types
class Tool(BaseModel):
    name: str
    description: Optional[str] = None
    inputSchema: Dict[str, Any]

@dataclass
class ToolResult:
    content: List[Union['TextContent', 'ImageContent', 'ResourceContent']]
    isError: Optional[bool] = False

# Prompt types
@dataclass
class Prompt:
    name: str
    description: Optional[str] = None
    arguments: Optional[List['PromptArgument']] = None

@dataclass
class PromptMessage:
    role: Literal["user", "assistant", "system"]
    content: 'MessageContent'
```

### Advanced Features

#### Middleware Support
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP()

@mcp.middleware
async def logging_middleware(request, handler):
    """Log all requests"""
    print(f"Handling {request['method']}")
    result = await handler(request)
    print(f"Completed {request['method']}")
    return result
```

#### Error Handling
```python
from mcp.errors import McpError, ErrorCode

@mcp.tool("read_file")
async def read_file(path: str) -> str:
    """Read a file"""
    if not path:
        raise McpError(
            ErrorCode.INVALID_PARAMS,
            "Path parameter is required"
        )
    # ... handle request
```

#### Testing Utilities
```python
import pytest
from mcp.server.fastmcp.testing import TestClient

@pytest.fixture
async def test_client():
    """Create test client"""
    from myserver import mcp  # Import your server
    
    async with TestClient(mcp) as client:
        yield client

async def test_list_resources(test_client):
    """Test resource listing"""
    result = await test_client.request("resources/list")
    assert len(result["resources"]) > 0
```

## Python SDK (Detailed)

### Advanced Server Patterns

#### Resource Management
```python
from mcp.server.fastmcp import FastMCP
from typing import Dict, Any
import json

mcp = FastMCP()

# Dynamic resource listing
@mcp.list_resources()
async def list_resources() -> List[Dict[str, Any]]:
    """List all available resources"""
    return [
        {
            "uri": "config://app",
            "name": "Application Config",
            "mimeType": "application/json"
        },
        {
            "uri": "db://users/{userId}",
            "name": "User Details",
            "mimeType": "application/json"
        }
    ]

# Resource handler with pattern matching
@mcp.resource_handler()
async def handle_resources(uri: str) -> str:
    """Handle dynamic resource requests"""
    if uri == "config://app":
        config = await load_config()
        return json.dumps(config)
    
    # Handle templated URIs
    if uri.startswith("db://users/"):
        user_id = uri.split("/")[-1]
        user = await get_user(user_id)
        return json.dumps(user)
    
    raise ValueError(f"Unknown resource: {uri}")
```

#### Subscription Handling
```python
import asyncio
from typing import Set, Callable

# Track subscriptions
subscriptions: Dict[str, Set[str]] = {}

@mcp.subscription_handler("resources/subscribe")
async def subscribe_to_resource(uri: str) -> Dict[str, str]:
    """Subscribe to resource changes"""
    subscription_id = str(uuid.uuid4())
    
    if uri not in subscriptions:
        subscriptions[uri] = set()
        # Start watching resource
        asyncio.create_task(watch_resource(uri))
    
    subscriptions[uri].add(subscription_id)
    return {"subscriptionId": subscription_id}

async def watch_resource(uri: str):
    """Watch for resource changes"""
    while uri in subscriptions:
        # Check for changes
        if await has_changed(uri):
            # Notify subscribers
            for sub_id in subscriptions[uri]:
                await mcp.send_notification(
                    "notifications/resources/updated",
                    {
                        "uri": uri,
                        "subscriptionId": sub_id
                    }
                )
        await asyncio.sleep(1)
```

#### Progress Notifications
```python
@mcp.tool(
    name="process_large_file",
    description="Process a large file with progress updates"
)
async def process_large_file(file_path: str) -> str:
    """Process file with progress notifications"""
    file_size = await get_file_size(file_path)
    processed = 0
    
    async with aiofiles.open(file_path, 'r') as f:
        async for chunk in f:
            # Process chunk
            await process_chunk(chunk)
            
            # Update progress
            processed += len(chunk)
            progress = int((processed / file_size) * 100)
            
            await mcp.send_progress(
                progress=progress,
                message=f"Processing {file_path}: {progress}%"
            )
    
    return "File processed successfully"
```

### Client Patterns

#### Connection Management
```python
from mcp import Client
import asyncio
from typing import Optional

class ManagedClient:
    """Client with automatic reconnection"""
    
    def __init__(self, name: str, version: str):
        self.client = Client(name=name, version=version)
        self.connected = False
        self._reconnect_task: Optional[asyncio.Task] = None
    
    async def connect(self, transport):
        """Connect with automatic reconnection"""
        while True:
            try:
                await self.client.connect(transport)
                self.connected = True
                break
            except Exception as e:
                print(f"Connection failed: {e}")
                await asyncio.sleep(5)
    
    async def request(self, method: str, params: Dict[str, Any] = None):
        """Make request with connection check"""
        if not self.connected:
            raise RuntimeError("Not connected")
        
        try:
            return await self.client.request(method, params)
        except Exception as e:
            self.connected = False
            raise
```

#### Batch Operations
```python
class BatchClient:
    """Client with batch operation support"""
    
    def __init__(self, client: Client):
        self.client = client
    
    async def batch_read_resources(self, uris: List[str]) -> Dict[str, Any]:
        """Read multiple resources in parallel"""
        tasks = [
            self.client.request("resources/read", {"uri": uri})
            for uri in uris
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return {
            uri: result if not isinstance(result, Exception) else {"error": str(result)}
            for uri, result in zip(uris, results)
        }
```

### Testing Patterns

#### Mock Server for Testing
```python
import pytest
from mcp.server.fastmcp.testing import MockServer

class TestMyClient:
    @pytest.fixture
    def mock_server(self):
        """Create mock MCP server"""
        server = MockServer()
        
        # Mock resources
        server.add_resource(
            "test://data",
            {"value": 42}
        )
        
        # Mock tools
        server.add_tool(
            "calculate",
            lambda x, y: {"result": x + y}
        )
        
        return server
    
    async def test_resource_reading(self, mock_server):
        """Test reading resources"""
        client = Client("test-client", "1.0.0")
        await client.connect(mock_server.transport)
        
        result = await client.request("resources/read", {
            "uri": "test://data"
        })
        
        assert result["contents"][0]["text"] == '{"value": 42}'
```

## Alternative Language Examples (Python Equivalents)

### C#-Style Patterns in Python

#### Async Context Managers
```python
from contextlib import asynccontextmanager
from typing import AsyncIterator

@asynccontextmanager
async def mcp_client(name: str, version: str) -> AsyncIterator[Client]:
    """Context manager for MCP client"""
    client = Client(name=name, version=version)
    transport = StdioClientTransport(
        command="python",
        args=["server.py"]
    )
    
    try:
        await client.connect(transport)
        yield client
    finally:
        await client.disconnect()

# Usage
async def main():
    async with mcp_client("example-client", "1.0.0") as client:
        resources = await client.request("resources/list")
        print(resources)
```

#### LINQ-Style Queries in Python
```python
from typing import List, Callable, TypeVar

T = TypeVar('T')

class QueryableList(list):
    """LINQ-style queryable list"""
    
    def where(self, predicate: Callable[[T], bool]) -> 'QueryableList[T]':
        """Filter items"""
        return QueryableList(filter(predicate, self))
    
    def order_by(self, key_func: Callable[[T], Any]) -> 'QueryableList[T]':
        """Sort items"""
        return QueryableList(sorted(self, key=key_func))
    
    def select(self, selector: Callable[[T], Any]) -> 'QueryableList':
        """Project items"""
        return QueryableList(map(selector, self))

# Usage
resources = QueryableList(await client.request("resources/list"))
json_resources = (
    resources
    .where(lambda r: r.get("mimeType") == "application/json")
    .order_by(lambda r: r.get("name"))
)
```

#### Dependency Injection
```python
from typing import Protocol
import asyncio
from functools import lru_cache

class IMcpClient(Protocol):
    """MCP Client interface"""
    async def request(self, method: str, params: dict) -> Any: ...

class ServiceContainer:
    """Simple dependency injection container"""
    
    @lru_cache(maxsize=1)
    def get_mcp_server(self) -> FastMCP:
        """Get MCP server singleton"""
        return FastMCP(
            name="example-server",
            version="1.0.0"
        )
    
    @lru_cache(maxsize=1)
    def get_mcp_client(self) -> IMcpClient:
        """Get MCP client singleton"""
        return Client(
            name="example-client",
            version="1.0.0"
        )

# Usage in service
class MyService:
    def __init__(self, client: IMcpClient):
        self._client = client
    
    async def process_data(self):
        resources = await self._client.request("resources/list")
        return resources

# Wire up dependencies
container = ServiceContainer()
service = MyService(container.get_mcp_client())
```

#### Async Generators
```python
from typing import AsyncIterator

class StreamingClient:
    """Client with streaming support"""
    
    def __init__(self, client: Client):
        self.client = client
    
    async def stream_resources(self) -> AsyncIterator[Dict[str, Any]]:
        """Stream resources as they become available"""
        resources = await self.client.request("resources/list")
        
        for resource in resources.get("resources", []):
            # Simulate async processing
            await asyncio.sleep(0.1)
            yield resource
    
    async def call_tool_with_progress(
        self,
        name: str,
        arguments: dict,
        progress_callback: Callable[[int], None]
    ) -> Any:
        """Call tool with progress tracking"""
        # Set up progress handler
        def handle_progress(notification):
            if notification.get("method") == "notifications/progress":
                progress_callback(notification["params"]["progress"])
        
        self.client.on("notification", handle_progress)
        
        try:
            result = await self.client.request("tools/call", {
                "name": name,
                "arguments": arguments
            })
            return result
        finally:
            # Clean up handler
            self.client.off("notification", handle_progress)

# Usage
client = StreamingClient(mcp_client)

# Stream resources
async for resource in client.stream_resources():
    print(f"Resource: {resource['name']}")

# Track progress
def print_progress(percent: int):
    print(f"Progress: {percent}%")

result = await client.call_tool_with_progress(
    "long_running_tool",
    {"data": "input"},
    print_progress
)
```

## Ruby-Style Patterns in Python

### DSL-Style API
```python
from typing import Dict, Any, Callable
from contextlib import contextmanager

class MCPServerBuilder:
    """DSL-style server builder"""
    
    def __init__(self):
        self.server = None
        self.current_resource = None
        self.current_tool = None
    
    def name(self, name: str) -> 'MCPServerBuilder':
        """Set server name"""
        if not self.server:
            self.server = FastMCP(name=name, version="1.0.0")
        return self
    
    def version(self, version: str) -> 'MCPServerBuilder':
        """Set server version"""
        self.server.version = version
        return self
    
    @contextmanager
    def resource(self, uri: str):
        """Define a resource"""
        self.current_resource = {"uri": uri}
        yield self
        
        # Register resource
        @self.server.resource(uri)
        async def handler():
            return self.current_resource.get("content", "")
    
    def mime_type(self, mime_type: str) -> 'MCPServerBuilder':
        """Set resource MIME type"""
        if self.current_resource:
            self.current_resource["mimeType"] = mime_type
        return self
    
    def content(self, content_func: Callable[[], str]) -> 'MCPServerBuilder':
        """Set resource content"""
        if self.current_resource:
            self.current_resource["content"] = content_func()
        return self
    
    @contextmanager
    def tool(self, name: str):
        """Define a tool"""
        self.current_tool = {"name": name}
        yield self
        
        # Register tool
        @self.server.tool(
            name=name,
            description=self.current_tool.get("description", ""),
            parameters=self.current_tool.get("schema", {})
        )
        async def handler(**kwargs):
            return self.current_tool["handler"](kwargs)
    
    def description(self, desc: str) -> 'MCPServerBuilder':
        """Set tool description"""
        if self.current_tool:
            self.current_tool["description"] = desc
        return self
    
    def execute(self, handler: Callable) -> 'MCPServerBuilder':
        """Set tool handler"""
        if self.current_tool:
            self.current_tool["handler"] = handler
        return self

# Usage - Ruby-style DSL in Python
builder = MCPServerBuilder()
builder.name("example-server").version("1.0.0")

with builder.resource("example://config"):
    builder.mime_type("application/json")
    builder.content(lambda: json.dumps({"setting": "value"}))

with builder.tool("process_data"):
    builder.description("Process data with options")
    builder.execute(lambda args: f"Processed: {args['data']}")

# Run the server
if __name__ == "__main__":
    builder.server.run()
```

### Block-Style Handlers
```python
class MCPServer:
    """Ruby-style block handlers"""
    
    def __init__(self, name: str, version: str):
        self.mcp = FastMCP(name=name, version=version)
        self._resource_handlers = []
        self._tool_handlers = {}
    
    def on_list_resources(self, handler: Callable):
        """Register resource list handler"""
        @self.mcp.list_resources()
        async def list_handler():
            return handler()
    
    def on_call_tool(self, handler: Callable):
        """Register tool call handler"""
        @self.mcp.call_tool()
        async def tool_handler(name: str, arguments: dict):
            request = type('Request', (), {'name': name, 'arguments': arguments})
            result = handler(request)
            return result
    
    def run(self):
        """Start the server"""
        self.mcp.run()

# Usage - Ruby-style in Python
server = MCPServer(
    name='example-server',
    version='1.0.0'
)

# Resource handler
server.on_list_resources(lambda: [
    {
        'uri': 'example://resource',
        'name': 'Example Resource',
        'mimeType': 'text/plain'
    }
])

# Tool handler
def handle_tool(request):
    if request.name == 'example_tool':
        return {
            'content': [{
                'type': 'text',
                'text': 'Tool executed successfully'
            }]
        }
    else:
        raise McpError(
            ErrorCode.METHOD_NOT_FOUND,
            f"Unknown tool: {request.name}"
        )

server.on_call_tool(handle_tool)

# Start server
if __name__ == "__main__":
    server.run()
```

## Java-Style Patterns in Python

### Builder Pattern
```python
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

@dataclass
class ServerCapabilities:
    """Server capabilities configuration"""
    resources: Optional[Dict] = field(default_factory=dict)
    tools: Optional[Dict] = field(default_factory=dict)
    prompts: Optional[Dict] = field(default_factory=dict)

class McpServerBuilder:
    """Java-style builder for MCP server"""
    
    def __init__(self):
        self._name: Optional[str] = None
        self._version: Optional[str] = None
        self._capabilities: Optional[ServerCapabilities] = None
    
    def name(self, name: str) -> 'McpServerBuilder':
        """Set server name"""
        self._name = name
        return self
    
    def version(self, version: str) -> 'McpServerBuilder':
        """Set server version"""
        self._version = version
        return self
    
    def capabilities(self, capabilities: ServerCapabilities) -> 'McpServerBuilder':
        """Set server capabilities"""
        self._capabilities = capabilities
        return self
    
    def build(self) -> FastMCP:
        """Build the server"""
        if not self._name or not self._version:
            raise ValueError("Name and version are required")
        
        server = FastMCP(
            name=self._name,
            version=self._version
        )
        
        # Configure capabilities if provided
        if self._capabilities:
            # Apply capabilities configuration
            pass
        
        return server

# Usage - Java-style builder
server = (McpServerBuilder()
    .name("example-server")
    .version("1.0.0")
    .capabilities(ServerCapabilities(
        resources={"subscribe": True},
        tools={"streaming": True}
    ))
    .build())

# Handler registration
@server.list_resources()
async def list_resources():
    return [
        {
            "uri": "example://resource",
            "name": "Example Resource",
            "mimeType": "text/plain"
        }
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "example_tool":
        return {
            "content": [{
                "type": "text",
                "text": "Tool executed successfully"
            }]
        }
    raise McpError(
        ErrorCode.METHOD_NOT_FOUND,
        f"Unknown tool: {name}"
    )
```

### Annotation-Style Decorators
```python
import functools
from typing import Callable, Any

# Define decorators that mimic Java annotations
def McpServer(name: str, version: str):
    """Class decorator for MCP server"""
    def decorator(cls):
        # Create server instance
        cls._mcp_server = FastMCP(name=name, version=version)
        
        # Process method decorators
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name)
            if hasattr(attr, '_mcp_handler_type'):
                handler_type = attr._mcp_handler_type
                
                if handler_type == 'list_resources':
                    cls._mcp_server.list_resources()(attr)
                elif handler_type == 'call_tool':
                    cls._mcp_server.call_tool()(attr)
        
        # Add run method
        cls.run = lambda self: cls._mcp_server.run()
        
        return cls
    return decorator

def ListResources(func: Callable) -> Callable:
    """Method decorator for list resources handler"""
    func._mcp_handler_type = 'list_resources'
    return func

def CallTool(func: Callable) -> Callable:
    """Method decorator for tool handler"""
    func._mcp_handler_type = 'call_tool'
    return func

def ToolName(func: Callable) -> Callable:
    """Parameter decorator simulation"""
    @functools.wraps(func)
    async def wrapper(self, name: str, arguments: Dict[str, Any]):
        return await func(self, name, arguments)
    return wrapper

# Usage - Java annotation style
@McpServer(name="example-server", version="1.0.0")
class ExampleServer:
    
    @ListResources
    async def list_resources(self) -> List[Dict[str, Any]]:
        """List available resources"""
        return [
            {
                "uri": "example://resource",
                "name": "Example Resource",
                "mimeType": "text/plain"
            }
        ]
    
    @CallTool
    @ToolName
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tool calls"""
        if name == "example_tool":
            return {
                "content": [{
                    "type": "text",
                    "text": "Result"
                }]
            }
        raise ValueError(f"Unknown tool: {name}")

# Run the server
if __name__ == "__main__":
    server = ExampleServer()
    server.run()
```

## Go-Style Patterns in Python

### Channel-Style Communication
```python
import asyncio
from typing import TypeVar, Generic, Optional
from asyncio import Queue

T = TypeVar('T')

class Channel(Generic[T]):
    """Go-style channel implementation"""
    
    def __init__(self, size: int = 0):
        self._queue = Queue(maxsize=size)
        self._closed = False
    
    async def send(self, item: T) -> None:
        """Send item to channel"""
        if self._closed:
            raise RuntimeError("Cannot send on closed channel")
        await self._queue.put(item)
    
    async def receive(self) -> Optional[T]:
        """Receive item from channel"""
        if self._closed and self._queue.empty():
            return None
        return await self._queue.get()
    
    def close(self) -> None:
        """Close the channel"""
        self._closed = True
    
    def __aiter__(self):
        return self
    
    async def __anext__(self) -> T:
        item = await self.receive()
        if item is None:
            raise StopAsyncIteration
        return item

# Go-style concurrent requests
async def concurrent_tool_calls(client: Client):
    """Execute tools concurrently"""
    results = Channel[Dict[str, Any]](10)
    
    async def call_tool(tool_id: int):
        try:
            result = await client.request("tools/call", {
                "name": f"tool_{tool_id}",
                "arguments": {"id": tool_id}
            })
            await results.send(result)
        except Exception as e:
            print(f"Error calling tool_{tool_id}: {e}")
    
    # Start concurrent tasks
    tasks = [asyncio.create_task(call_tool(i)) for i in range(10)]
    
    # Close channel when all tasks complete
    async def wait_and_close():
        await asyncio.gather(*tasks)
        results.close()
    
    asyncio.create_task(wait_and_close())
    
    # Process results as they arrive
    async for result in results:
        print(f"Result: {result}")
```

### Error Handling with Multiple Returns
```python
from typing import Tuple, Optional, Union

class GoStyleError:
    """Go-style error handling"""
    
    @staticmethod
    def ok(value: T) -> Tuple[T, None]:
        """Return success value"""
        return value, None
    
    @staticmethod
    def error(err: Exception) -> Tuple[None, Exception]:
        """Return error"""
        return None, err

class McpClient:
    """Client with Go-style error handling"""
    
    async def list_resources(self) -> Tuple[Optional[List[Dict]], Optional[Exception]]:
        """List resources with error return"""
        try:
            result = await self.client.request("resources/list")
            return result.get("resources", []), None
        except Exception as e:
            return None, e
    
    async def read_resource(self, uri: str) -> Tuple[Optional[str], Optional[Exception]]:
        """Read resource with error return"""
        try:
            result = await self.client.request("resources/read", {"uri": uri})
            content = result.get("contents", [{}])[0]
            return content.get("text"), None
        except Exception as e:
            return None, e

# Usage - Go-style error handling
client = McpClient()

# List resources
resources, err = await client.list_resources()
if err:
    print(f"Error listing resources: {err}")
    return

for resource in resources:
    print(f"Resource: {resource['name']} ({resource['uri']})")

# Read resource
content, err = await client.read_resource("example://resource")
if err:
    print(f"Error reading resource: {err}")
    return

print(f"Content: {content}")
```

### Functional Options Pattern
```python
from typing import Callable, Optional
from dataclasses import dataclass, field

@dataclass
class ServerOptions:
    """Server configuration options"""
    name: str
    version: str
    capabilities: Dict[str, Any] = field(default_factory=dict)
    transport: Optional[Any] = None
    log_level: str = "info"

# Option function type
ServerOption = Callable[[ServerOptions], None]

def with_capabilities(capabilities: Dict[str, Any]) -> ServerOption:
    """Set server capabilities"""
    def option(opts: ServerOptions) -> None:
        opts.capabilities = capabilities
    return option

def with_transport(transport: Any) -> ServerOption:
    """Set server transport"""
    def option(opts: ServerOptions) -> None:
        opts.transport = transport
    return option

def with_log_level(level: str) -> ServerOption:
    """Set log level"""
    def option(opts: ServerOptions) -> None:
        opts.log_level = level
    return option

def new_server(name: str, version: str, *options: ServerOption) -> FastMCP:
    """Create server with functional options"""
    # Default options
    opts = ServerOptions(name=name, version=version)
    
    # Apply options
    for option in options:
        option(opts)
    
    # Create server
    server = FastMCP(name=opts.name, version=opts.version)
    
    # Configure based on options
    if opts.log_level:
        logging.getLogger("mcp").setLevel(opts.log_level.upper())
    
    return server

# Usage - Functional options pattern
server = new_server(
    "example-server",
    "1.0.0",
    with_capabilities({
        "resources": {"subscribe": True},
        "tools": {"streaming": True}
    }),
    with_log_level("debug")
)
```

## SDK Architecture

### Common Patterns

#### Transport Abstraction
All SDKs implement a transport abstraction layer:
```
Transport Interface
├── stdio Transport
├── HTTP Transport
├── SSE Transport
└── WebSocket Transport (future)
```

#### Message Handling Pipeline
```
Incoming Message → Deserialize → Validate → Route → Handle → Serialize → Response
```

#### Error Hierarchy
```
McpError
├── ParseError (-32700)
├── InvalidRequest (-32600)
├── MethodNotFound (-32601)
├── InvalidParams (-32602)
├── InternalError (-32603)
└── Custom Errors (-32000 to -32099)
```

### Cross-SDK Features

#### Protocol Versioning
All SDK implementations support protocol version negotiation:
```python
# Python - Primary implementation
client.protocol_version  # "2025-06-18"

# Python property style
@property
def protocol_version(self) -> str:
    """Get protocol version"""
    return self._protocol_version

# Python method style
def get_protocol_version(self) -> str:
    """Get protocol version"""
    return self.protocol_version

# Async version check
async def check_protocol_compatibility(client: Client) -> bool:
    """Check if server protocol is compatible"""
    server_info = await client.get_server_info()
    server_version = server_info.get("protocolVersion")
    return server_version in SUPPORTED_VERSIONS
```

#### Capability Discovery
```python
# Python - All implementations provide capability discovery
capabilities = await client.get_server_capabilities()
if capabilities.get("tools"):
    # Server supports tools
    tool_capabilities = capabilities["tools"]
    if tool_capabilities.get("streaming"):
        # Server supports streaming tool results
        pass

# Capability checking utility
def check_capabilities(capabilities: Dict[str, Any], *required: str) -> bool:
    """Check if server has required capabilities"""
    for cap in required:
        parts = cap.split(".")
        current = capabilities
        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]
    return True

# Usage
if check_capabilities(capabilities, "tools.streaming", "resources.subscribe"):
    # Server has all required capabilities
    pass
```

#### Logging
All SDK implementations support configurable logging:
```python
# Python - Standard logging configuration
import logging

# Configure MCP logging
logging.getLogger("mcp").setLevel(logging.DEBUG)

# Configure with custom handler
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
logger = logging.getLogger("mcp")
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

# Structured logging
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

# Use structured logger
log = structlog.get_logger("mcp")
log.info("server_started", name="example-server", version="1.0.0")
```

## SDK Comparison

### Feature Matrix

| Feature | TypeScript | Python | C# | Ruby | Java | Go |
|---------|------------|--------|----|------|------|----|
| Full Protocol Support | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Type Safety | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ |
| Async/Await | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Streaming | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Middleware | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |
| Testing Utils | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| DI Support | ✗ | ✗ | ✓ | ✗ | ✓ | ✗ |

### Performance Characteristics

| SDK | Startup Time | Memory Usage | Throughput |
|-----|--------------|--------------|------------|
| Go | Fastest | Lowest | Highest |
| TypeScript | Fast | Medium | High |
| Java | Medium | High | High |
| C# | Medium | Medium | High |
| Python | Slow | Medium | Medium |
| Ruby | Slowest | High | Low |

### Ecosystem Integration

| SDK | Package Manager | Testing | Linting | Docs |
|-----|-----------------|---------|---------|------|
| TypeScript | npm/yarn/pnpm | Jest/Vitest | ESLint | TypeDoc |
| Python | pip/poetry | pytest | flake8/black | Sphinx |
| C# | NuGet | xUnit/NUnit | Roslyn | XML Docs |
| Ruby | gem/bundler | RSpec | RuboCop | YARD |
| Java | Maven/Gradle | JUnit | SpotBugs | Javadoc |
| Go | go modules | testing | golint | godoc |

## Contributing to SDKs

### Development Setup
```bash
# Clone SDK repository
git clone https://github.com/modelcontextprotocol/[language]-sdk
cd [language]-sdk

# Install dependencies
npm install  # TypeScript
pip install -e ".[dev]"  # Python
dotnet restore  # C#
bundle install  # Ruby
mvn install  # Java
go mod download  # Go

# Run tests
npm test  # TypeScript
pytest  # Python
dotnet test  # C#
rspec  # Ruby
mvn test  # Java
go test ./...  # Go
```

### Contributing Guidelines
1. **Follow Python conventions**: PEP 8, type hints, async/await patterns
2. **Maintain type safety**: Use mypy/pyright for static type checking
3. **Write tests**: Use pytest for comprehensive test coverage
4. **Document thoroughly**: Include docstrings and examples
5. **Ensure compatibility**: Test against multiple protocol versions

### Testing Protocol Compliance
Python SDK compliance testing:
```bash
# Run compliance tests
python -m pytest tests/compliance/

# Run with coverage
python -m pytest --cov=mcp tests/compliance/

# Run type checking
pyright
mypy mcp/

# Run linting
ruff check .
black --check .

# Full test suite
just test  # If using justfile
# or
tox  # Run all environments
```

### Python Testing Patterns
```python
import pytest
import pytest_asyncio
from mcp.tests.compliance import ComplianceTestSuite

class TestProtocolCompliance(ComplianceTestSuite):
    """MCP protocol compliance tests"""
    
    @pytest_asyncio.fixture
    async def server(self):
        """Create test server"""
        from myserver import mcp
        return mcp
    
    async def test_initialization_compliance(self, server, client):
        """Test protocol initialization compliance"""
        result = await client.request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {
                "name": "test-client",
                "version": "1.0.0"
            }
        })
        
        assert result["protocolVersion"] == "2025-06-18"
        assert "capabilities" in result
        assert "serverInfo" in result
    
    async def test_resource_compliance(self, server, client):
        """Test resource handling compliance"""
        # List resources
        list_result = await client.request("resources/list")
        assert "resources" in list_result
        
        # Read resource
        if list_result["resources"]:
            uri = list_result["resources"][0]["uri"]
            read_result = await client.request("resources/read", {"uri": uri})
            assert "contents" in read_result
```

## Next Steps

- **Examples**: See complete implementations using each SDK
- **Server Development**: Build servers with your preferred SDK
- **Client Development**: Create clients with your preferred SDK
- **Protocol Specification**: Understand the underlying protocol