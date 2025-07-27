# Model Context Protocol (MCP) - Protocol Specification

## Table of Contents
- [Overview](#overview)
- [Protocol Basics](#protocol-basics)
- [Message Format](#message-format)
- [Protocol Methods](#protocol-methods)
- [Lifecycle Management](#lifecycle-management)
- [Resources](#resources)
- [Tools](#tools)
- [Prompts](#prompts)
- [Sampling](#sampling)
- [Error Handling](#error-handling)
- [Protocol Versioning](#protocol-versioning)

## Overview

The Model Context Protocol is built on JSON-RPC 2.0, providing a standardized communication protocol between AI applications and context providers. This specification defines the message formats, methods, and behaviors that all MCP implementations must support.

## Protocol Basics

### JSON-RPC 2.0 Foundation
MCP uses JSON-RPC 2.0 as its message format, with the following requirements:
- All messages MUST be valid JSON-RPC 2.0
- All messages MUST be UTF-8 encoded
- Request IDs MUST NOT be null
- Request IDs MUST be unique within a session
- Implementations MUST support receiving JSON-RPC batches

### Message Types

#### 1. Request
A message sent to initiate an operation:
```json
{
  "jsonrpc": "2.0",
  "id": "unique-request-id",
  "method": "method/name",
  "params": {
    "param1": "value1",
    "param2": "value2"
  }
}
```

#### 2. Response
A message sent in reply to a request:
```json
{
  "jsonrpc": "2.0",
  "id": "unique-request-id",
  "result": {
    "data": "response data"
  }
}
```

#### 3. Error Response
A response indicating an error occurred:
```json
{
  "jsonrpc": "2.0",
  "id": "unique-request-id",
  "error": {
    "code": -32600,
    "message": "Invalid Request",
    "data": "Additional error information"
  }
}
```

#### 4. Notification
A one-way message that doesn't expect a response:
```json
{
  "jsonrpc": "2.0",
  "method": "notification/type",
  "params": {
    "data": "notification data"
  }
}
```

## Message Format

### Base Message Structure
All MCP messages follow this base structure:
```python
from typing import Optional, Union, Any, TypedDict

class JsonRpcMessage(TypedDict, total=False):
    """Base structure for all JSON-RPC messages"""
    jsonrpc: str  # Always "2.0"
    id: Optional[Union[str, int]]  # Required for requests/responses
    method: Optional[str]  # Required for requests/notifications
    params: Optional[Any]  # Optional parameters
    result: Optional[Any]  # Only in responses
    error: Optional['JsonRpcError']  # Only in error responses
```

### Error Structure
```python
class JsonRpcError(TypedDict):
    """JSON-RPC error structure"""
    code: int
    message: str
    data: Optional[Any]
```

### Standard Error Codes
- `-32700`: Parse error
- `-32600`: Invalid Request
- `-32601`: Method not found
- `-32602`: Invalid params
- `-32603`: Internal error
- `-32000` to `-32099`: Server-defined errors

## Protocol Methods

### Method Naming Convention
Methods follow a namespace/action pattern:
- `initialize`: Protocol initialization
- `resources/list`: List available resources
- `resources/read`: Read a specific resource
- `tools/list`: List available tools
- `tools/call`: Execute a tool
- `prompts/list`: List available prompts
- `prompts/get`: Get a specific prompt
- `completion/complete`: Request completion

## Lifecycle Management

### 1. Initialization

#### Initialize Request (Client → Server)
```json
{
  "jsonrpc": "2.0",
  "id": "init-1",
  "method": "initialize",
  "params": {
    "protocolVersion": "2025-06-18",
    "capabilities": {
      "experimental": {},
      "sampling": {}
    },
    "clientInfo": {
      "name": "ExampleClient",
      "version": "1.0.0"
    }
  }
}
```

#### Initialize Response (Server → Client)
```json
{
  "jsonrpc": "2.0",
  "id": "init-1",
  "result": {
    "protocolVersion": "2025-06-18",
    "capabilities": {
      "resources": {},
      "tools": {},
      "prompts": {},
      "logging": {}
    },
    "serverInfo": {
      "name": "ExampleServer",
      "version": "1.0.0"
    }
  }
}
```

#### Initialized Notification (Client → Server)
```json
{
  "jsonrpc": "2.0",
  "method": "notifications/initialized"
}
```

### 2. Shutdown

#### Shutdown Request
```json
{
  "jsonrpc": "2.0",
  "id": "shutdown-1",
  "method": "shutdown"
}
```

#### Shutdown Response
```json
{
  "jsonrpc": "2.0",
  "id": "shutdown-1",
  "result": {}
}
```

## Resources

Resources represent data that servers expose to clients.

### List Resources
```json
{
  "jsonrpc": "2.0",
  "id": "res-list-1",
  "method": "resources/list"
}
```

Response:
```json
{
  "jsonrpc": "2.0",
  "id": "res-list-1",
  "result": {
    "resources": [
      {
        "uri": "file:///data/users.json",
        "name": "User Database",
        "description": "List of all users",
        "mimeType": "application/json"
      },
      {
        "uri": "db://inventory/products",
        "name": "Product Inventory",
        "description": "Current product inventory",
        "mimeType": "application/json"
      }
    ]
  }
}
```

### Read Resource
```json
{
  "jsonrpc": "2.0",
  "id": "res-read-1",
  "method": "resources/read",
  "params": {
    "uri": "file:///data/users.json"
  }
}
```

Response:
```json
{
  "jsonrpc": "2.0",
  "id": "res-read-1",
  "result": {
    "contents": [
      {
        "uri": "file:///data/users.json",
        "mimeType": "application/json",
        "text": "[{\"id\": 1, \"name\": \"Alice\"}, {\"id\": 2, \"name\": \"Bob\"}]"
      }
    ]
  }
}
```

### Resource Templates
Resources can include templates for dynamic URIs:
```json
{
  "uri": "db://users/{userId}",
  "name": "User Details",
  "description": "Get details for a specific user",
  "mimeType": "application/json"
}
```

### Resource Subscriptions
Subscribe to resource changes:
```json
{
  "jsonrpc": "2.0",
  "id": "res-sub-1",
  "method": "resources/subscribe",
  "params": {
    "uri": "file:///data/users.json"
  }
}
```

## Tools

Tools represent executable functions that servers provide.

### List Tools
```json
{
  "jsonrpc": "2.0",
  "id": "tools-list-1",
  "method": "tools/list"
}
```

Response:
```json
{
  "jsonrpc": "2.0",
  "id": "tools-list-1",
  "result": {
    "tools": [
      {
        "name": "create_user",
        "description": "Create a new user account",
        "inputSchema": {
          "type": "object",
          "properties": {
            "name": {
              "type": "string",
              "description": "User's full name"
            },
            "email": {
              "type": "string",
              "format": "email",
              "description": "User's email address"
            }
          },
          "required": ["name", "email"]
        }
      },
      {
        "name": "search_database",
        "description": "Search the database",
        "inputSchema": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string",
              "description": "Search query"
            },
            "limit": {
              "type": "integer",
              "minimum": 1,
              "maximum": 100,
              "default": 10
            }
          },
          "required": ["query"]
        }
      }
    ]
  }
}
```

### Call Tool
```json
{
  "jsonrpc": "2.0",
  "id": "tool-call-1",
  "method": "tools/call",
  "params": {
    "name": "create_user",
    "arguments": {
      "name": "Alice Smith",
      "email": "alice@example.com"
    }
  }
}
```

Response:
```json
{
  "jsonrpc": "2.0",
  "id": "tool-call-1",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "User created successfully with ID: 12345"
      }
    ]
  }
}
```

### Tool Result Types
Tools can return different content types:
```json
{
  "content": [
    {
      "type": "text",
      "text": "Plain text result"
    },
    {
      "type": "image",
      "data": "base64-encoded-image-data",
      "mimeType": "image/png"
    },
    {
      "type": "resource",
      "uri": "file:///results/report.pdf"
    }
  ]
}
```

## Prompts

Prompts are reusable templates for LLM interactions.

### List Prompts
```json
{
  "jsonrpc": "2.0",
  "id": "prompts-list-1",
  "method": "prompts/list"
}
```

Response:
```json
{
  "jsonrpc": "2.0",
  "id": "prompts-list-1",
  "result": {
    "prompts": [
      {
        "name": "code_review",
        "description": "Review code for best practices",
        "arguments": [
          {
            "name": "code",
            "description": "The code to review",
            "required": true
          },
          {
            "name": "language",
            "description": "Programming language",
            "required": false
          }
        ]
      }
    ]
  }
}
```

### Get Prompt
```json
{
  "jsonrpc": "2.0",
  "id": "prompt-get-1",
  "method": "prompts/get",
  "params": {
    "name": "code_review",
    "arguments": {
      "code": "function add(a, b) { return a + b; }",
      "language": "javascript"
    }
  }
}
```

Response:
```json
{
  "jsonrpc": "2.0",
  "id": "prompt-get-1",
  "result": {
    "description": "Code review for JavaScript",
    "messages": [
      {
        "role": "user",
        "content": {
          "type": "text",
          "text": "Please review this JavaScript code:\n\nfunction add(a, b) { return a + b; }"
        }
      }
    ]
  }
}
```

## Sampling

Sampling allows servers to request LLM completions.

### Create Message Request
```json
{
  "jsonrpc": "2.0",
  "id": "sample-1",
  "method": "sampling/createMessage",
  "params": {
    "messages": [
      {
        "role": "user",
        "content": {
          "type": "text",
          "text": "What is the capital of France?"
        }
      }
    ],
    "modelPreferences": {
      "hints": [
        {
          "name": "claude-3-sonnet"
        }
      ],
      "costPriority": 0.3,
      "speedPriority": 0.7,
      "intelligencePriority": 0.5
    },
    "systemPrompt": "You are a helpful geography assistant.",
    "includeContext": "allServers",
    "temperature": 0.7,
    "maxTokens": 150,
    "stopSequences": ["\n\n"],
    "metadata": {}
  }
}
```

Response:
```json
{
  "jsonrpc": "2.0",
  "id": "sample-1",
  "result": {
    "role": "assistant",
    "content": {
      "type": "text",
      "text": "The capital of France is Paris."
    },
    "model": "claude-3-sonnet-20240620",
    "stopReason": "end_turn"
  }
}
```

## Error Handling

### Standard MCP Errors
```json
{
  "jsonrpc": "2.0",
  "id": "failed-request",
  "error": {
    "code": -32001,
    "message": "Resource not found",
    "data": {
      "uri": "file:///missing.txt",
      "details": "The requested file does not exist"
    }
  }
}
```

### Error Codes
- `-32001`: Resource not found
- `-32002`: Resource access denied
- `-32003`: Tool execution failed
- `-32004`: Invalid tool arguments
- `-32005`: Prompt not found
- `-32006`: Sampling not supported
- `-32007`: Capability not supported

## Protocol Versioning

### Version Format
Versions follow the format: `YYYY-MM-DD`

### Version Negotiation
1. Client sends supported version in initialize
2. Server responds with version it will use
3. Must be compatible version

### Current Versions
- `2025-06-18`: Latest stable version
- `2025-03-26`: Previous version
- `2024-11-05`: Legacy version

### Capability Discovery
```json
{
  "capabilities": {
    "resources": {
      "subscribe": true,
      "templates": true
    },
    "tools": {
      "streaming": true
    },
    "prompts": {
      "dynamic": true
    },
    "logging": {
      "levels": ["debug", "info", "warn", "error"]
    },
    "experimental": {
      "feature_x": true
    }
  }
}
```

## Message Flow Examples

### Complete Interaction Flow
```
1. Client → Server: initialize
2. Server → Client: initialize response
3. Client → Server: initialized notification
4. Client → Server: resources/list
5. Server → Client: resource list
6. Client → Server: tools/list
7. Server → Client: tool list
8. Client → Server: tools/call
9. Server → Client: tool result
10. Client → Server: shutdown
11. Server → Client: shutdown response
```

### Batch Request Example
```json
[
  {
    "jsonrpc": "2.0",
    "id": "batch-1",
    "method": "resources/list"
  },
  {
    "jsonrpc": "2.0",
    "id": "batch-2",
    "method": "tools/list"
  },
  {
    "jsonrpc": "2.0",
    "method": "notifications/progress",
    "params": {
      "progress": 50,
      "message": "Processing..."
    }
  }
]
```

## Implementation Requirements

### MUST Support
- JSON-RPC 2.0 message format
- Initialize/shutdown lifecycle
- Error responses with appropriate codes
- UTF-8 encoding

### SHOULD Support
- Batch requests
- Resource subscriptions
- Progress notifications
- Cancellation

### MAY Support
- Experimental features
- Custom extensions
- Additional transport methods

## Next Steps

- **Transport Layer**: Details on stdio, HTTP, and other transports
- **Server Development**: Building MCP servers
- **Client Development**: Creating MCP clients
- **Security**: Authentication and authorization