# Model Context Protocol (MCP) - Client Development

## Table of Contents
- [Overview](#overview)
- [Getting Started](#getting-started)
- [Client Architecture](#client-architecture)
- [Connection Management](#connection-management)
- [Making Requests](#making-requests)
- [Handling Responses](#handling-responses)
- [Resource Operations](#resource-operations)
- [Tool Execution](#tool-execution)
- [Prompt Management](#prompt-management)
- [Error Handling](#error-handling)
- [Advanced Features](#advanced-features)
- [Testing Clients](#testing-clients)
- [Best Practices](#best-practices)

## Overview

MCP clients are applications that connect to MCP servers to access resources and execute tools. This guide covers building robust MCP clients that can effectively integrate with AI systems and provide seamless access to external data and functionality.

## Getting Started

### Prerequisites
- Understanding of MCP protocol basics
- Familiarity with async programming
- Knowledge of your chosen SDK language

### Quick Start

```bash
# Install MCP Python SDK
pip install mcp
```

```python
import asyncio
from mcp import Client, StdioTransport

async def main():
    # Create and connect a client
    client = Client(
        name="my-mcp-client",
        version="1.0.0"
    )
    
    transport = StdioTransport(
        command="python",
        args=["path/to/server.py"]
    )
    
    await client.connect(transport)
    
    # Use the client
    resources = await client.request("resources/list")
    print("Available resources:", resources)

asyncio.run(main())
```

## Client Architecture

### Component Overview
```
┌─────────────────────────────────────────┐
│            MCP Client                    │
├─────────────────────────────────────────┤
│  ┌─────────────────────────────────┐    │
│  │    Request/Response Handler      │    │
│  │  ┌──────────┐  ┌──────────┐    │    │
│  │  │ Request  │  │Response  │    │    │
│  │  │ Queue    │  │ Router   │    │    │
│  │  └──────────┘  └──────────┘    │    │
│  └─────────────────────────────────┘    │
│                                          │
│  ┌─────────────────────────────────┐    │
│  │    Connection Manager            │    │
│  │  ┌──────────┐  ┌──────────┐    │    │
│  │  │Transport │  │Protocol  │    │    │
│  │  │ Layer    │  │ Handler  │    │    │
│  │  └──────────┘  └──────────┘    │    │
│  └─────────────────────────────────┘    │
│                                          │
│  ┌─────────────────────────────────┐    │
│  │    State Management             │    │
│  │  ┌──────────┐  ┌──────────┐    │    │
│  │  │  Server  │  │ Request  │    │    │
│  │  │   Info   │  │ Tracking │    │    │
│  │  └──────────┘  └──────────┘    │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

### Core Client Class
```python
import asyncio
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass, field

@dataclass
class PendingRequest:
    """Tracks a pending request"""
    future: asyncio.Future
    method: str
    timeout_handle: Optional[asyncio.TimerHandle] = None

class MCPClient:
    """Core MCP client implementation"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.transport: Optional[Transport] = None
        self.request_id: int = 0
        self.pending_requests: Dict[int, PendingRequest] = {}
        self.server_capabilities: Optional[Dict[str, Any]] = None
        self._message_handler_task: Optional[asyncio.Task] = None
    
    async def connect(self, transport: Transport) -> None:
        """Connect to MCP server"""
        self.transport = transport
        
        # Start transport
        await self.transport.start()
        
        # Start message handler
        self._message_handler_task = asyncio.create_task(
            self._handle_messages()
        )
        
        # Initialize protocol
        await self.initialize()
    
    async def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Send request to server"""
        request_id = self._next_id()
        
        # Create future for response
        future = asyncio.Future()
        pending = PendingRequest(future=future, method=method)
        self.pending_requests[request_id] = pending
        
        # Send request
        await self.transport.send({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {}
        })
        
        # Set timeout
        pending.timeout_handle = asyncio.get_event_loop().call_later(
            30.0,
            lambda: self._timeout_request(request_id)
        )
        
        try:
            return await future
        finally:
            # Clean up timeout
            if pending.timeout_handle:
                pending.timeout_handle.cancel()
    
    def _next_id(self) -> int:
        """Generate next request ID"""
        self.request_id += 1
        return self.request_id
    
    def _timeout_request(self, request_id: int) -> None:
        """Handle request timeout"""
        if request_id in self.pending_requests:
            pending = self.pending_requests.pop(request_id)
            pending.future.set_exception(
                TimeoutError(f"Request timeout: {pending.method}")
            )
```

## Connection Management

### Transport Selection
```python
import os
from mcp import StdioTransport, HttpTransport, SseTransport

# stdio transport for local servers
stdio_transport = StdioTransport(
    command="python",
    args=["./server.py"],
    env={
        **os.environ,
        "PYTHONPATH": ".",
    }
)

# HTTP transport for remote servers
http_transport = HttpTransport(
    url="https://api.example.com/mcp",
    headers={
        "Authorization": "Bearer token",
    }
)

# SSE transport for streaming
sse_transport = SseTransport(
    url="https://api.example.com/mcp/stream"
)
```

### Connection Lifecycle
```python
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class ConnectionManager:
    """Manages MCP client connections with reconnection logic"""
    
    def __init__(self, client: MCPClient, transport: Transport):
        self.client = client
        self.transport = transport
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
    
    async def connect(self) -> None:
        """Connect with automatic retry"""
        try:
            await self.client.connect(self.transport)
            self.reconnect_attempts = 0
            logger.info("Connected successfully")
        except Exception as error:
            logger.error(f"Connection failed: {error}")
            await self.handle_connection_error()
    
    async def handle_connection_error(self) -> None:
        """Handle connection errors with exponential backoff"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            raise Exception("Max reconnection attempts reached")
        
        self.reconnect_attempts += 1
        delay = min(1.0 * (2 ** self.reconnect_attempts), 30.0)
        
        logger.info(f"Reconnecting in {delay}s (attempt {self.reconnect_attempts})")
        await asyncio.sleep(delay)
        
        return await self.connect()
    
    async def disconnect(self) -> None:
        """Gracefully disconnect"""
        try:
            # Send shutdown request
            await self.client.request("shutdown")
        except Exception as e:
            logger.warning(f"Shutdown request failed: {e}")
        
        # Close transport
        await self.transport.close()
```

### Health Monitoring
```python
import asyncio
import time
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass

@dataclass
class HealthStatus:
    """Health check status"""
    healthy: bool
    latency: Optional[float] = None
    error: Optional[Exception] = None

class HealthMonitor:
    """Monitor MCP client health"""
    
    def __init__(self, health_callback: Optional[Callable[[HealthStatus], None]] = None):
        self.ping_task: Optional[asyncio.Task] = None
        self.last_pong: float = 0
        self.health_callback = health_callback
    
    async def start_monitoring(self, client: MCPClient, interval: float = 30.0) -> None:
        """Start health monitoring"""
        self.ping_task = asyncio.create_task(
            self._monitor_loop(client, interval)
        )
    
    async def stop_monitoring(self) -> None:
        """Stop health monitoring"""
        if self.ping_task:
            self.ping_task.cancel()
            try:
                await self.ping_task
            except asyncio.CancelledError:
                pass
    
    async def _monitor_loop(self, client: MCPClient, interval: float) -> None:
        """Health check loop"""
        while True:
            try:
                start = time.time()
                await client.request("ping")
                latency = (time.time() - start) * 1000  # ms
                
                self.last_pong = time.time()
                self._on_health_check(HealthStatus(
                    healthy=True,
                    latency=latency
                ))
            except Exception as error:
                self._on_health_check(HealthStatus(
                    healthy=False,
                    error=error
                ))
            
            await asyncio.sleep(interval)
    
    def _on_health_check(self, status: HealthStatus) -> None:
        """Handle health check result"""
        if self.health_callback:
            self.health_callback(status)
```

## Making Requests

### Basic Request Pattern
```python
# Simple request without parameters
result = await client.request("tools/list")

# Request with parameters
resource = await client.request("resources/read", {
    "uri": "file:///data/config.json"
})

# Request with timeout
async def request_with_timeout(client, method, params, timeout=60.0):
    """Make request with custom timeout"""
    try:
        return await asyncio.wait_for(
            client.request(method, params),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        raise TimeoutError(f"Request timeout: {method}")

# Usage
result_with_timeout = await request_with_timeout(
    client,
    "tools/call",
    {
        "name": "long_running_tool",
        "arguments": {"data": "..."}
    },
    timeout=60.0
)
```

### Batch Requests
```python
import time
from typing import List, Dict, Any, Optional

class BatchRequestClient:
    """Client with batch request support"""
    
    def __init__(self, client: MCPClient):
        self.client = client
    
    async def batch_request(self, requests: List[Dict[str, Any]]) -> List[Any]:
        """Send multiple requests as a batch"""
        # Create batch with unique IDs
        timestamp = int(time.time() * 1000)
        batch = [
            {
                "jsonrpc": "2.0",
                "id": f"batch-{timestamp}-{index}",
                "method": req["method"],
                "params": req.get("params", {})
            }
            for index, req in enumerate(requests)
        ]
        
        # Send batch
        responses = await self.client.send_batch(batch)
        
        # Sort responses back to original order
        def get_index(response):
            return int(response["id"].split('-')[2])
        
        return sorted(responses, key=get_index)

# Usage
batch_client = BatchRequestClient(client)
results = await batch_client.batch_request([
    {"method": "resources/list"},
    {"method": "tools/list"},
    {"method": "prompts/list"},
])
```

### Request Queuing
```python
import asyncio
from typing import Any, Optional, List
from dataclasses import dataclass
from collections import deque

@dataclass
class QueuedRequest:
    """Queued request with future"""
    method: str
    params: Optional[Dict[str, Any]]
    future: asyncio.Future

class QueuedClient:
    """Client with request queuing and concurrency control"""
    
    def __init__(self, client: MCPClient, concurrency: int = 3):
        self.client = client
        self.queue: deque[QueuedRequest] = deque()
        self.concurrency = concurrency
        self.processing = False
        self._process_task: Optional[asyncio.Task] = None
    
    async def queue_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Queue a request for execution"""
        future = asyncio.Future()
        request = QueuedRequest(method=method, params=params, future=future)
        self.queue.append(request)
        
        # Start processing if not already running
        if not self.processing:
            self._process_task = asyncio.create_task(self._process_queue())
        
        return await future
    
    async def _process_queue(self) -> None:
        """Process queued requests with concurrency limit"""
        self.processing = True
        active_tasks: set[asyncio.Task] = set()
        
        try:
            while self.queue or active_tasks:
                # Start new requests up to concurrency limit
                while self.queue and len(active_tasks) < self.concurrency:
                    request = self.queue.popleft()
                    task = asyncio.create_task(
                        self._execute_request(request)
                    )
                    active_tasks.add(task)
                
                # Wait for at least one to complete
                if active_tasks:
                    done, pending = await asyncio.wait(
                        active_tasks,
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    active_tasks = pending
        finally:
            self.processing = False
    
    async def _execute_request(self, request: QueuedRequest) -> None:
        """Execute a single request"""
        try:
            result = await self.client.request(request.method, request.params)
            request.future.set_result(result)
        except Exception as error:
            request.future.set_exception(error)
```

## Handling Responses

### Response Processing
```python
from typing import Dict, Any, Optional, Callable
import logging

logger = logging.getLogger(__name__)

class MCPError(Exception):
    """MCP protocol error"""
    def __init__(self, message: str, code: int, data: Optional[Any] = None):
        super().__init__(message)
        self.code = code
        self.data = data

class ResponseHandler:
    """Handle MCP protocol messages"""
    
    def __init__(self):
        self.pending_requests: Dict[int, PendingRequest] = {}
        self.notification_handlers: Dict[str, List[Callable]] = {}
    
    def handle_message(self, message: Dict[str, Any]) -> None:
        """Process incoming message"""
        # Handle responses
        if "id" in message and message["id"] is not None:
            self.handle_response(message)
        # Handle notifications
        elif "method" in message:
            self.handle_notification(message)
    
    def handle_response(self, message: Dict[str, Any]) -> None:
        """Handle response message"""
        request_id = message["id"]
        pending = self.pending_requests.get(request_id)
        if not pending:
            return
        
        del self.pending_requests[request_id]
        
        if "error" in message:
            error = message["error"]
            pending.future.set_exception(MCPError(
                error["message"],
                error["code"],
                error.get("data")
            ))
        else:
            pending.future.set_result(message.get("result"))
    
    def handle_notification(self, message: Dict[str, Any]) -> None:
        """Handle notification message"""
        method = message["method"]
        params = message.get("params", {})
        
        # Call registered handlers
        if method in self.notification_handlers:
            for handler in self.notification_handlers[method]:
                try:
                    handler(params)
                except Exception as e:
                    logger.error(f"Notification handler error: {e}")
        else:
            logger.warning(f"Unknown notification: {method}")
    
    def on(self, method: str, handler: Callable) -> None:
        """Register notification handler"""
        if method not in self.notification_handlers:
            self.notification_handlers[method] = []
        self.notification_handlers[method].append(handler)
```

### Streaming Responses
```python
from typing import AsyncIterator, Dict, Any
import asyncio

class StreamingClient:
    """Client with streaming support"""
    
    def __init__(self, client: MCPClient):
        self.client = client
        self.active_streams: Dict[str, asyncio.Queue] = {}
    
    async def stream_request(self, method: str, params: Dict[str, Any]) -> AsyncIterator[Any]:
        """Stream response data"""
        # Start stream
        response = await self.client.request("stream/start", {
            "method": method,
            "params": params
        })
        stream_id = response["streamId"]
        
        # Create queue for stream data
        queue = asyncio.Queue()
        self.active_streams[stream_id] = queue
        
        try:
            while True:
                chunk = await self.wait_for_chunk(stream_id)
                if chunk.get("done", False):
                    break
                yield chunk["data"]
        finally:
            # Clean up stream
            del self.active_streams[stream_id]
            await self.client.request("stream/end", {"streamId": stream_id})
    
    async def wait_for_chunk(self, stream_id: str) -> Dict[str, Any]:
        """Wait for next chunk from stream"""
        queue = self.active_streams.get(stream_id)
        if not queue:
            raise ValueError(f"Unknown stream: {stream_id}")
        return await queue.get()
    
    # Usage example
    async def process_stream(self):
        """Example of processing streamed data"""
        async for log in self.stream_request("tools/call", {
            "name": "stream_logs",
            "arguments": {"follow": True}
        }):
            print(f"Log: {log}")
```

## Resource Operations

### Resource Discovery
```python
import re
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class Resource:
    """MCP resource"""
    uri: str
    name: str
    description: Optional[str] = None
    mimeType: Optional[str] = None

class ResourceManager:
    """Manage MCP resources"""
    
    def __init__(self, client: MCPClient):
        self.client = client
        self.resource_cache: Dict[str, Resource] = {}
    
    async def list_resources(self) -> List[Resource]:
        """List available resources"""
        response = await self.client.request("resources/list")
        
        # Cache resources
        resources = []
        for res_data in response["resources"]:
            resource = Resource(**res_data)
            self.resource_cache[resource.uri] = resource
            resources.append(resource)
        
        return resources
    
    async def get_resource_by_pattern(self, pattern: str) -> List[Resource]:
        """Find resources matching pattern"""
        resources = await self.list_resources()
        regex = re.compile(pattern)
        
        return [
            resource for resource in resources
            if regex.search(resource.uri) or regex.search(resource.name)
        ]
```

### Reading Resources
```python
import json
import base64
from typing import Dict, Any, Optional
from collections import OrderedDict

class LRUCache:
    """Simple LRU cache implementation"""
    def __init__(self, max_size: int = 100):
        self.cache = OrderedDict()
        self.max_size = max_size
    
    def get(self, key: str) -> Optional[Any]:
        if key in self.cache:
            # Move to end (most recently used)
            self.cache.move_to_end(key)
            return self.cache[key]
        return None
    
    def set(self, key: str, value: Any) -> None:
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.max_size:
            # Remove least recently used
            self.cache.popitem(last=False)
    
    def has(self, key: str) -> bool:
        return key in self.cache

class ResourceReader:
    """Read and cache MCP resources"""
    
    def __init__(self, client: MCPClient, cache_size: int = 100):
        self.client = client
        self.cache = LRUCache(max_size=cache_size)
    
    async def read_resource(self, uri: str, options: Optional[Dict[str, Any]] = None) -> Any:
        """Read resource with caching"""
        options = options or {}
        
        # Check cache first
        cache_key = f"{uri}:{json.dumps(options, sort_keys=True)}"
        if not options.get("noCache", False) and self.cache.has(cache_key):
            return self.cache.get(cache_key)
        
        # Read from server
        response = await self.client.request("resources/read", {
            "uri": uri,
            **options
        })
        
        # Process content based on type
        content = self.process_content(response["contents"][0])
        
        # Cache result
        self.cache.set(cache_key, content)
        
        return content
    
    def process_content(self, content: Dict[str, Any]) -> Any:
        """Process content based on MIME type"""
        mime_type = content.get("mimeType", "text/plain")
        
        if mime_type == "application/json":
            return json.loads(content["text"])
        elif mime_type == "text/plain":
            return content["text"]
        elif mime_type == "application/octet-stream":
            return base64.b64decode(content["blob"])
        else:
            return content
```

### Resource Subscriptions
```python
from typing import Dict, Callable, Any
import asyncio
from dataclasses import dataclass

@dataclass
class Subscription:
    """Resource subscription info"""
    uri: str
    callback: Callable[[Any], None]

class ResourceSubscriber:
    """Manage resource subscriptions"""
    
    def __init__(self, client: MCPClient):
        self.client = client
        self.subscriptions: Dict[str, Subscription] = {}
        
        # Set up notification handler
        client.on("notifications/resources/updated", self._handle_update)
    
    async def subscribe(self, uri: str, callback: Callable[[Any], None]) -> str:
        """Subscribe to resource changes"""
        # Subscribe on server
        response = await self.client.request("resources/subscribe", {
            "uri": uri
        })
        subscription_id = response["subscriptionId"]
        
        # Track subscription
        self.subscriptions[subscription_id] = Subscription(
            uri=uri,
            callback=callback
        )
        
        return subscription_id
    
    async def unsubscribe(self, subscription_id: str) -> None:
        """Unsubscribe from resource"""
        await self.client.request("resources/unsubscribe", {
            "subscriptionId": subscription_id
        })
        
        self.subscriptions.pop(subscription_id, None)
    
    async def unsubscribe_all(self) -> None:
        """Unsubscribe from all resources"""
        tasks = [
            self.unsubscribe(sub_id)
            for sub_id in list(self.subscriptions.keys())
        ]
        await asyncio.gather(*tasks)
    
    def _handle_update(self, params: Dict[str, Any]) -> None:
        """Handle resource update notification"""
        subscription_id = params.get("subscriptionId")
        if subscription_id in self.subscriptions:
            subscription = self.subscriptions[subscription_id]
            try:
                subscription.callback(params.get("change"))
            except Exception as e:
                logger.error(f"Subscription callback error: {e}")
```

## Tool Execution

### Tool Discovery and Validation
```python
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import jsonschema

@dataclass
class Tool:
    """MCP tool definition"""
    name: str
    description: str
    inputSchema: Dict[str, Any]

@dataclass
class ValidationResult:
    """Schema validation result"""
    valid: bool
    errors: List[str]

class ToolManager:
    """Manage MCP tools"""
    
    def __init__(self, client: MCPClient):
        self.client = client
        self.tool_schemas: Dict[str, Tool] = {}
    
    async def list_tools(self) -> List[Tool]:
        """List available tools"""
        response = await self.client.request("tools/list")
        
        # Cache tool schemas
        tools = []
        for tool_data in response["tools"]:
            tool = Tool(**tool_data)
            self.tool_schemas[tool.name] = tool
            tools.append(tool)
        
        return tools
    
    def validate_arguments(self, tool_name: str, args: Any) -> ValidationResult:
        """Validate tool arguments against schema"""
        tool = self.tool_schemas.get(tool_name)
        if not tool:
            return ValidationResult(
                valid=False,
                errors=[f"Unknown tool: {tool_name}"]
            )
        
        # Validate against JSON schema
        try:
            jsonschema.validate(args, tool.inputSchema)
            return ValidationResult(valid=True, errors=[])
        except jsonschema.ValidationError as e:
            return ValidationResult(
                valid=False,
                errors=[str(e)]
            )
```

### Tool Execution with Progress
```python
from typing import Optional, Callable, Dict, Any

@dataclass
class Progress:
    """Progress notification"""
    progress: float
    message: Optional[str] = None

class ToolExecutor:
    """Execute MCP tools with progress tracking"""
    
    def __init__(self, client: MCPClient, tool_manager: ToolManager):
        self.client = client
        self.tool_manager = tool_manager
    
    async def execute_tool(
        self,
        name: str,
        args: Any,
        on_progress: Optional[Callable[[Progress], None]] = None
    ) -> Dict[str, Any]:
        """Execute tool with optional progress callback"""
        # Validate arguments
        validation = self.tool_manager.validate_arguments(name, args)
        if not validation.valid:
            raise ValueError(f"Invalid arguments: {', '.join(validation.errors)}")
        
        # Set up progress handler
        progress_handler_id = None
        if on_progress:
            def progress_handler(params: Dict[str, Any]) -> None:
                progress = Progress(
                    progress=params.get("progress", 0),
                    message=params.get("message")
                )
                on_progress(progress)
            
            # Register handler
            self.client.on("notifications/progress", progress_handler)
            progress_handler_id = id(progress_handler)
        
        try:
            # Execute tool
            result = await self.client.request("tools/call", {
                "name": name,
                "arguments": args
            })
            
            return result
        finally:
            # Clean up listener
            if progress_handler_id:
                # Remove the specific handler
                # (Implementation depends on how client.on is implemented)
                pass

# Usage
executor = ToolExecutor(client, tool_manager)
result = await executor.execute_tool(
    "process_data",
    {"input": "data.csv"},
    on_progress=lambda p: print(f"Progress: {p.progress}% - {p.message}")
)
```

### Tool Result Processing
```python
import base64
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass, field

@dataclass
class ProcessedResult:
    """Processed tool result"""
    text: List[str] = field(default_factory=list)
    images: List[Dict[str, Any]] = field(default_factory=list)
    resources: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

class ToolResultProcessor:
    """Process tool execution results"""
    
    def process_result(self, result: Dict[str, Any]) -> ProcessedResult:
        """Process raw tool result"""
        processed = ProcessedResult()
        
        for content in result.get("content", []):
            content_type = content.get("type")
            
            if content_type == "text":
                processed.text.append(content["text"])
            
            elif content_type == "image":
                processed.images.append({
                    "data": content["data"],
                    "mimeType": content.get("mimeType", "image/png")
                })
            
            elif content_type == "resource":
                processed.resources.append(content["uri"])
            
            else:
                logger.warning(f"Unknown content type: {content_type}")
        
        return processed
    
    async def save_results(self, result: ProcessedResult, output_dir: str) -> None:
        """Save processed results to disk"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Save text content
        if result.text:
            text_file = output_path / "output.txt"
            text_file.write_text("\n".join(result.text))
        
        # Save images
        for i, image in enumerate(result.images):
            mime_type = image["mimeType"]
            ext = mime_type.split("/")[1]
            image_file = output_path / f"image-{i}.{ext}"
            
            # Decode base64 and save
            image_data = base64.b64decode(image["data"])
            image_file.write_bytes(image_data)
```

## Prompt Management

### Prompt Discovery
```python
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

@dataclass
class PromptArgument:
    """Prompt argument definition"""
    name: str
    description: str
    required: bool = False

@dataclass 
class Prompt:
    """MCP prompt definition"""
    name: str
    description: str
    arguments: List[PromptArgument]

class PromptManager:
    """Manage MCP prompts"""
    
    def __init__(self, client: MCPClient):
        self.client = client
        self.prompt_cache: Dict[str, Prompt] = {}
    
    async def list_prompts(self) -> List[Prompt]:
        """List available prompts"""
        response = await self.client.request("prompts/list")
        
        prompts = []
        for prompt_data in response["prompts"]:
            # Convert arguments
            args = [
                PromptArgument(**arg) 
                for arg in prompt_data.get("arguments", [])
            ]
            prompt = Prompt(
                name=prompt_data["name"],
                description=prompt_data["description"],
                arguments=args
            )
            self.prompt_cache[prompt.name] = prompt
            prompts.append(prompt)
        
        return prompts
    
    async def get_prompt(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get prompt with arguments"""
        # Validate arguments
        prompt = self.prompt_cache.get(name)
        if not prompt:
            raise ValueError(f"Unknown prompt: {name}")
        
        # Check required arguments
        missing = [
            arg.name for arg in prompt.arguments
            if arg.required and arg.name not in args
        ]
        
        if missing:
            raise ValueError(f"Missing required arguments: {', '.join(missing)}")
        
        # Get prompt content
        return await self.client.request("prompts/get", {
            "name": name,
            "arguments": args
        })
```

### Prompt Integration with LLMs
```python
from typing import Dict, List, Any, Optional
import json

class LLMClient:
    """Mock LLM client interface"""
    async def complete(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, str]:
        # This would be your actual LLM implementation
        pass

class LLMIntegration:
    """Integrate MCP prompts with LLMs"""
    
    def __init__(self, mcp_client: MCPClient, llm_client: LLMClient):
        self.mcp_client = mcp_client
        self.llm_client = llm_client
    
    async def execute_prompt(
        self,
        prompt_name: str,
        args: Dict[str, Any],
        llm_options: Optional[Dict[str, Any]] = None
    ) -> str:
        """Execute MCP prompt through LLM"""
        # Get prompt from MCP server
        prompt_result = await self.mcp_client.request("prompts/get", {
            "name": prompt_name,
            "arguments": args
        })
        
        # Convert to LLM format
        messages = []
        for msg in prompt_result["messages"]:
            content = msg["content"]
            if isinstance(content, dict) and content.get("type") == "text":
                messages.append({
                    "role": msg["role"],
                    "content": content["text"]
                })
            else:
                messages.append({
                    "role": msg["role"],
                    "content": str(content)
                })
        
        # Send to LLM
        llm_options = llm_options or {}
        completion = await self.llm_client.complete(
            messages=messages,
            **llm_options
        )
        
        return completion["content"]
    
    async def chain_prompts(
        self,
        prompts: List[Dict[str, Any]]
    ) -> List[str]:
        """Execute a chain of prompts"""
        results: List[str] = []
        context: Dict[str, Any] = {}
        
        for prompt in prompts:
            # Include previous results in arguments
            enriched_args = {
                **prompt["args"],
                "previousResults": results,
                "context": context
            }
            
            result = await self.execute_prompt(
                prompt["name"],
                enriched_args
            )
            results.append(result)
            
            # Extract context for next prompt
            context = self.extract_context(result)
        
        return results
    
    def extract_context(self, result: str) -> Dict[str, Any]:
        """Extract context from result for chaining"""
        # Simple implementation - could be more sophisticated
        try:
            # Try to parse as JSON
            return json.loads(result)
        except json.JSONDecodeError:
            # Return as text context
            return {"text": result}
```

## Error Handling

### Comprehensive Error Handling
```python
from typing import TypeVar, Callable, Optional, Any, Dict
import asyncio
import logging

T = TypeVar('T')

class MCPError(Exception):
    """MCP protocol error"""
    def __init__(self, message: str, code: int, data: Optional[Any] = None):
        super().__init__(message)
        self.code = code
        self.data = data
        self.name = "MCPError"

@dataclass
class ErrorHandlingOptions:
    """Options for error handling"""
    retries: int = 3
    retry_delay: float = 1.0
    on_error: Optional[Callable[[Exception, int], None]] = None
    fallback: Optional[Callable[[Exception], Any]] = None

class ErrorHandler:
    """Comprehensive error handling for MCP operations"""
    
    async def handle_request(
        self,
        operation: Callable[[], Awaitable[T]],
        options: Optional[ErrorHandlingOptions] = None
    ) -> T:
        """Execute operation with error handling"""
        options = options or ErrorHandlingOptions()
        last_error: Optional[Exception] = None
        
        for attempt in range(options.retries + 1):
            try:
                return await operation()
            except Exception as error:
                last_error = error
                
                if options.on_error:
                    options.on_error(error, attempt)
                
                # Check if error is retryable
                if not self.is_retryable(error) or attempt == options.retries:
                    break
                
                # Wait before retry with exponential backoff
                delay = options.retry_delay * (2 ** attempt)
                await asyncio.sleep(delay)
        
        # Use fallback if provided
        if options.fallback and last_error:
            return options.fallback(last_error)
        
        if last_error:
            raise last_error
        raise RuntimeError("No error but operation failed")
    
    def is_retryable(self, error: Exception) -> bool:
        """Check if error is retryable"""
        if isinstance(error, MCPError):
            # Don't retry client errors
            return error.code < -32000 or error.code > -32099
        
        # Retry network errors
        error_code = getattr(error, 'errno', None)
        return error_code in [
            # Common network error codes
            104,  # ECONNRESET
            110,  # ETIMEDOUT
            -2,   # ENOTFOUND (DNS)
        ]
```

### Circuit Breaker Pattern
```python
import time
from typing import TypeVar, Callable, Awaitable
from enum import Enum

T = TypeVar('T')

class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"

class CircuitBreaker:
    """Circuit breaker for fault tolerance"""
    
    def __init__(self, threshold: int = 5, timeout: float = 60.0):
        self.threshold = threshold
        self.timeout = timeout
        self.failures = 0
        self.last_failure_time = 0.0
        self.state = CircuitState.CLOSED
    
    async def execute(self, operation: Callable[[], Awaitable[T]]) -> T:
        """Execute operation with circuit breaker protection"""
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.timeout:
                self.state = CircuitState.HALF_OPEN
            else:
                raise Exception("Circuit breaker is open")
        
        try:
            result = await operation()
            self.on_success()
            return result
        except Exception as error:
            self.on_failure()
            raise error
    
    def on_success(self) -> None:
        """Handle successful execution"""
        self.failures = 0
        self.state = CircuitState.CLOSED
    
    def on_failure(self) -> None:
        """Handle failed execution"""
        self.failures += 1
        self.last_failure_time = time.time()
        
        if self.failures >= self.threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit breaker opened after {self.failures} failures")
```

## Advanced Features

### Multi-Server Management
```python
from typing import Dict, Any, Optional
import asyncio

@dataclass
class ServerConfig:
    """Server configuration"""
    client_config: Dict[str, Any]
    transport_type: str
    transport_config: Dict[str, Any]

class MultiServerClient:
    """Manage multiple MCP server connections"""
    
    def __init__(self):
        self.clients: Dict[str, MCPClient] = {}
    
    async def add_server(self, server_id: str, config: ServerConfig) -> None:
        """Add a new server connection"""
        client = MCPClient(config.client_config)
        transport = self.create_transport(config.transport_type, config.transport_config)
        
        await client.connect(transport)
        self.clients[server_id] = client
    
    def create_transport(self, transport_type: str, config: Dict[str, Any]) -> Transport:
        """Create transport based on type"""
        if transport_type == "stdio":
            return StdioTransport(**config)
        elif transport_type == "http":
            return HttpTransport(**config)
        elif transport_type == "sse":
            return SseTransport(**config)
        else:
            raise ValueError(f"Unknown transport type: {transport_type}")
    
    async def request(self, server_id: str, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Send request to specific server"""
        client = self.clients.get(server_id)
        if not client:
            raise ValueError(f"Unknown server: {server_id}")
        
        return await client.request(method, params)
    
    async def broadcast(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Broadcast request to all servers"""
        results = {}
        
        async def request_with_id(server_id: str, client: MCPClient):
            try:
                result = await client.request(method, params)
                results[server_id] = {"success": True, "result": result}
            except Exception as error:
                results[server_id] = {"success": False, "error": str(error)}
        
        tasks = [
            request_with_id(server_id, client)
            for server_id, client in self.clients.items()
        ]
        
        await asyncio.gather(*tasks)
        return results
```

### Request Caching
```python
import time
import json
from typing import Dict, Any, Optional, TypeVar
from dataclasses import dataclass

T = TypeVar('T')

@dataclass
class CacheEntry:
    """Cache entry with TTL"""
    value: Any
    timestamp: float
    ttl: float

@dataclass
class CacheOptions:
    """Cache configuration"""
    use_cache: bool = True
    cache: bool = True
    ttl: Optional[float] = None

class CachedClient:
    """Client with request caching"""
    
    def __init__(self, client: MCPClient):
        self.client = client
        self.cache: Dict[str, CacheEntry] = {}
    
    async def request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        options: Optional[CacheOptions] = None
    ) -> Any:
        """Make request with caching"""
        options = options or CacheOptions()
        cache_key = self.get_cache_key(method, params)
        
        # Check cache
        if options.use_cache:
            cached = self.cache.get(cache_key)
            if cached and not self.is_expired(cached):
                return cached.value
        
        # Make request
        result = await self.client.request(method, params)
        
        # Cache result
        if options.cache and self.is_cacheable(method):
            ttl = options.ttl or self.get_default_ttl(method)
            self.cache[cache_key] = CacheEntry(
                value=result,
                timestamp=time.time(),
                ttl=ttl
            )
        
        return result
    
    def get_cache_key(self, method: str, params: Optional[Dict[str, Any]]) -> str:
        """Generate cache key"""
        params_str = json.dumps(params, sort_keys=True) if params else ""
        return f"{method}:{params_str}"
    
    def is_expired(self, entry: CacheEntry) -> bool:
        """Check if cache entry is expired"""
        return time.time() - entry.timestamp > entry.ttl
    
    def is_cacheable(self, method: str) -> bool:
        """Check if method result is cacheable"""
        # Only cache read operations
        return (
            method.startswith("resources/") or
            method == "tools/list" or
            method == "prompts/list"
        )
    
    def get_default_ttl(self, method: str) -> float:
        """Get default TTL for method"""
        # Different TTLs for different methods
        if method == "resources/list":
            return 300.0  # 5 minutes
        elif method.startswith("resources/"):
            return 60.0   # 1 minute
        else:
            return 600.0  # 10 minutes
```

### Request Middleware
```python
import time
from typing import List, Callable, Any, Optional, Dict, TypeVar
import logging

T = TypeVar('T')
logger = logging.getLogger(__name__)

# Middleware type
Middleware = Callable[
    [str, Optional[Dict[str, Any]], Callable[[], Awaitable[Any]]],
    Awaitable[Any]
]

class MiddlewareClient:
    """Client with middleware support"""
    
    def __init__(self, client: MCPClient):
        self.client = client
        self.middleware: List[Middleware] = []
    
    def use(self, middleware: Middleware) -> None:
        """Add middleware to the stack"""
        self.middleware.append(middleware)
    
    async def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Execute request through middleware stack"""
        index = 0
        
        async def next() -> Any:
            nonlocal index
            if index >= len(self.middleware):
                return await self.client.request(method, params)
            
            current_middleware = self.middleware[index]
            index += 1
            return await current_middleware(method, params, next)
        
        return await next()

# Example middleware implementations
async def logging_middleware(
    method: str,
    params: Optional[Dict[str, Any]],
    next: Callable[[], Awaitable[Any]]
) -> Any:
    """Log requests and responses"""
    logger.info(f"Request: {method}", extra={"params": params})
    start_time = time.time()
    
    try:
        result = await next()
        duration = (time.time() - start_time) * 1000
        logger.info(f"Response: {method} ({duration:.2f}ms)")
        return result
    except Exception as error:
        logger.error(f"Error: {method}", exc_info=error)
        raise

async def auth_middleware(
    method: str,
    params: Optional[Dict[str, Any]],
    next: Callable[[], Awaitable[Any]]
) -> Any:
    """Add authentication to requests"""
    # Get auth token (implementation specific)
    auth_token = await get_auth_token()
    
    # Enrich params with auth
    enriched_params = {
        **(params or {}),
        "auth": auth_token
    }
    
    # Update params for next middleware
    return await next()

async def retry_middleware(
    method: str,
    params: Optional[Dict[str, Any]],
    next: Callable[[], Awaitable[Any]]
) -> Any:
    """Retry failed requests"""
    max_retries = 3
    retry_delay = 1.0
    
    for attempt in range(max_retries):
        try:
            return await next()
        except Exception as error:
            if attempt == max_retries - 1:
                raise
            
            logger.warning(f"Request failed, retrying ({attempt + 1}/{max_retries})")
            await asyncio.sleep(retry_delay * (2 ** attempt))

# Helper function stub
async def get_auth_token() -> str:
    """Get authentication token"""
    # Implementation specific
    return "auth-token"
```

## Testing Clients

### Unit Testing
```python
import pytest
import pytest_asyncio
from unittest.mock import Mock, AsyncMock
from typing import Dict, Any

class MockTransport:
    """Mock transport for testing"""
    
    def __init__(self):
        self.responses: Dict[str, Any] = {}
        self.errors: Dict[str, Exception] = {}
        self._started = False
    
    def mock_response(self, method: str, response: Any) -> None:
        """Set mock response for method"""
        self.responses[method] = response
    
    def mock_error(self, method: str, error: Dict[str, Any]) -> None:
        """Set mock error for method"""
        self.errors[method] = MCPError(
            error["message"],
            error["code"],
            error.get("data")
        )
    
    async def start(self) -> None:
        self._started = True
    
    async def send(self, message: Dict[str, Any]) -> None:
        """Mock send - triggers response"""
        method = message.get("method")
        if method in self.errors:
            raise self.errors[method]

@pytest.mark.asyncio
class TestMCPClient:
    """Test MCP client functionality"""
    
    @pytest_asyncio.fixture
    async def setup(self):
        """Set up test fixtures"""
        self.transport = MockTransport()
        self.client = MCPClient({"name": "test", "version": "1.0.0"})
        return self.client, self.transport
    
    async def test_list_resources(self, setup):
        """Test listing resources"""
        client, transport = setup
        
        # Set up mock response
        transport.mock_response("resources/list", {
            "resources": [
                {
                    "uri": "test://resource",
                    "name": "Test Resource",
                    "mimeType": "text/plain"
                }
            ]
        })
        
        # Mock the request method to return the mocked response
        client.request = AsyncMock(return_value=transport.responses["resources/list"])
        
        await client.connect(transport)
        result = await client.request("resources/list")
        
        assert len(result["resources"]) == 1
        assert result["resources"][0]["uri"] == "test://resource"
    
    async def test_handle_errors(self, setup):
        """Test error handling"""
        client, transport = setup
        
        transport.mock_error("tools/call", {
            "code": -32003,
            "message": "Tool execution failed"
        })
        
        # Mock the request to raise the error
        client.request = AsyncMock(
            side_effect=transport.errors["tools/call"]
        )
        
        await client.connect(transport)
        
        with pytest.raises(MCPError, match="Tool execution failed"):
            await client.request("tools/call", {"name": "test"})
```

### Integration Testing
```python
import pytest
import pytest_asyncio
from mcp.server.fastmcp import FastMCP
from mcp import Client, HttpTransport
import asyncio

class TestServer:
    """Test MCP server"""
    
    def __init__(self):
        self.mcp = FastMCP(name="test-server", version="1.0.0")
        self.port = 8080
        self._setup_handlers()
    
    def _setup_handlers(self):
        @self.mcp.resource("test://data")
        async def test_data():
            return "Test data content"
        
        @self.mcp.tool(
            name="process_data",
            description="Process data",
            parameters={
                "type": "object",
                "properties": {
                    "data": {"type": "string"}
                },
                "required": ["data"]
            }
        )
        async def process_data(data: str) -> str:
            return f"Processed: {data}"
    
    async def start(self):
        """Start test server"""
        # This would start the actual server
        pass
    
    async def stop(self):
        """Stop test server"""
        # This would stop the actual server
        pass

@pytest.mark.asyncio
class TestMCPClientIntegration:
    """Integration tests for MCP client"""
    
    @pytest_asyncio.fixture
    async def setup(self):
        """Set up test environment"""
        # Start test server
        server = TestServer()
        await server.start()
        
        # Connect client
        client = Client(name="test", version="1.0.0")
        transport = HttpTransport(
            url=f"http://localhost:{server.port}/mcp"
        )
        await client.connect(transport)
        
        yield client, server
        
        # Cleanup
        await client.disconnect()
        await server.stop()
    
    async def test_full_workflow(self, setup):
        """Test complete client workflow"""
        client, server = setup
        
        # List resources
        resources = await client.request("resources/list")
        assert len(resources["resources"]) >= 1
        
        # Read resource
        content = await client.request("resources/read", {
            "uri": resources["resources"][0]["uri"]
        })
        assert len(content["contents"]) == 1
        
        # Execute tool
        tool_result = await client.request("tools/call", {
            "name": "process_data",
            "arguments": {
                "data": content["contents"][0]["text"]
            }
        })
        assert tool_result["content"][0]["type"] == "text"
        assert "Processed:" in tool_result["content"][0]["text"]
```

## Best Practices

### 1. **Connection Management**
- Implement automatic reconnection
- Use connection pooling for multiple servers
- Monitor connection health
- Handle graceful disconnection

### 2. **Error Handling**
- Use circuit breakers for failing servers
- Implement retry logic with backoff
- Provide meaningful error messages
- Log errors for debugging

### 3. **Performance**
- Cache frequently accessed resources
- Use request batching
- Implement request queuing
- Monitor response times

### 4. **Security**
- Validate server certificates
- Use secure transports (TLS)
- Implement authentication
- Sanitize server responses

### 5. **Observability**
- Log all requests and responses
- Track metrics (latency, errors)
- Implement distributed tracing
- Monitor resource usage

### Example: Production-Ready Client
```python
from typing import Dict, Any, Optional
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class ProductionConfig:
    """Production client configuration"""
    client: Dict[str, Any]
    circuit_breaker: Dict[str, Any]
    metrics: Dict[str, Any]
    cache: Dict[str, Any]

class MetricsCollector:
    """Collect client metrics"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.metrics: Dict[str, Any] = {}
    
    def record_success(self, method: str, duration_ms: float) -> None:
        """Record successful request"""
        if method not in self.metrics:
            self.metrics[method] = {"success": 0, "error": 0, "total_time": 0}
        self.metrics[method]["success"] += 1
        self.metrics[method]["total_time"] += duration_ms
    
    def record_error(self, method: str, error: Exception) -> None:
        """Record failed request"""
        if method not in self.metrics:
            self.metrics[method] = {"success": 0, "error": 0, "total_time": 0}
        self.metrics[method]["error"] += 1

class ProductionMCPClient:
    """Production-ready MCP client with all features"""
    
    def __init__(self, config: ProductionConfig):
        self.client = MCPClient(config.client)
        self.error_handler = ErrorHandler()
        self.circuit_breaker = CircuitBreaker(**config.circuit_breaker)
        self.metrics = MetricsCollector(config.metrics)
        self.cache = CachedClient(self.client)
        
        self.setup_middleware()
    
    def setup_middleware(self) -> None:
        """Configure middleware stack"""
        middleware_client = MiddlewareClient(self.client)
        
        # Metrics middleware
        async def metrics_middleware(method, params, next):
            start_time = time.time()
            try:
                result = await next()
                duration_ms = (time.time() - start_time) * 1000
                self.metrics.record_success(method, duration_ms)
                return result
            except Exception as error:
                self.metrics.record_error(method, error)
                raise
        
        middleware_client.use(metrics_middleware)
        
        # Circuit breaker middleware
        async def circuit_breaker_middleware(method, params, next):
            return await self.circuit_breaker.execute(next)
        
        middleware_client.use(circuit_breaker_middleware)
        
        # Replace client with middleware-enabled version
        self.client = middleware_client
    
    async def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Make request with all production features"""
        options = ErrorHandlingOptions(
            retries=3,
            on_error=lambda error, attempt: logger.error(
                f"Request failed (attempt {attempt}): {error}"
            )
        )
        
        return await self.error_handler.handle_request(
            lambda: self.cache.request(method, params),
            options
        )
    
    async def connect(self, transport: Transport) -> None:
        """Connect to MCP server"""
        await self.client.connect(transport)
    
    async def disconnect(self) -> None:
        """Disconnect from MCP server"""
        await self.client.disconnect()
```

## Next Steps

- **SDK Reference**: Detailed SDK API documentation
- **Examples**: Complete client implementations
- **Server Development**: Building servers for your clients
- **Best Practices**: Production deployment guide