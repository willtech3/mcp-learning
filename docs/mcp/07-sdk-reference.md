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

## TypeScript/JavaScript SDK

### Installation
```bash
npm install @modelcontextprotocol/sdk
# or
yarn add @modelcontextprotocol/sdk
# or
pnpm add @modelcontextprotocol/sdk
```

### Core Components

#### Server API
```typescript
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

// Server configuration
const server = new Server(
  {
    name: "example-server",
    version: "1.0.0",
  },
  {
    capabilities: {
      resources: {},
      tools: {},
      prompts: {},
    },
  }
);

// Request handlers
server.setRequestHandler("resources/list", async () => ({
  resources: [
    {
      uri: "example://resource",
      name: "Example Resource",
      mimeType: "text/plain",
    },
  ],
}));

// Start server
const transport = new StdioServerTransport();
await server.connect(transport);
```

#### Client API
```typescript
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

// Client configuration
const client = new Client({
  name: "example-client",
  version: "1.0.0",
});

// Connect to server
const transport = new StdioClientTransport({
  command: "node",
  args: ["server.js"],
});

await client.connect(transport);

// Make requests
const resources = await client.request("resources/list");
```

#### Transport Options
```typescript
// stdio transport
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

// HTTP/SSE transport
import { HttpServerTransport } from "@modelcontextprotocol/sdk/server/http.js";

// WebSocket transport (coming soon)
import { WebSocketServerTransport } from "@modelcontextprotocol/sdk/server/websocket.js";
```

#### Type Definitions
```typescript
// Resource types
interface Resource {
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
}

interface ResourceContent {
  uri: string;
  mimeType?: string;
  text?: string;
  blob?: string;
}

// Tool types
interface Tool {
  name: string;
  description?: string;
  inputSchema: JsonSchema;
}

interface ToolResult {
  content: Array<TextContent | ImageContent | ResourceContent>;
  isError?: boolean;
}

// Prompt types
interface Prompt {
  name: string;
  description?: string;
  arguments?: PromptArgument[];
}

interface PromptMessage {
  role: "user" | "assistant" | "system";
  content: MessageContent;
}
```

### Advanced Features

#### Middleware Support
```typescript
server.use(async (request, next) => {
  console.log(`Handling ${request.method}`);
  const result = await next(request);
  console.log(`Completed ${request.method}`);
  return result;
});
```

#### Error Handling
```typescript
import { McpError, ErrorCode } from "@modelcontextprotocol/sdk/types.js";

server.setRequestHandler("resources/read", async (request) => {
  if (!request.params.uri) {
    throw new McpError(
      ErrorCode.InvalidParams,
      "URI parameter is required"
    );
  }
  // ... handle request
});
```

#### Testing Utilities
```typescript
import { TestClient } from "@modelcontextprotocol/sdk/testing/client.js";
import { TestServer } from "@modelcontextprotocol/sdk/testing/server.js";

const server = new TestServer();
const client = new TestClient(server);

await client.initialize();
const result = await client.request("resources/list");
```

## Python SDK

### Installation
```bash
pip install mcp
# or
poetry add mcp
# or
pipenv install mcp
```

### Core Components

#### Server API
```python
from mcp import Server, Resource, Tool
from mcp.server.stdio import StdioServerTransport

# Server configuration
server = Server(
    name="example-server",
    version="1.0.0"
)

# Resource handler
@server.list_resources()
async def list_resources():
    return [
        Resource(
            uri="example://resource",
            name="Example Resource",
            mime_type="text/plain"
        )
    ]

# Tool handler
@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "example_tool":
        return ToolResult(
            content=[TextContent(text="Tool executed successfully")]
        )
    raise ValueError(f"Unknown tool: {name}")

# Start server
async def main():
    transport = StdioServerTransport()
    await server.connect(transport)
    await server.run()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

#### Client API
```python
from mcp import Client
from mcp.client.stdio import StdioClientTransport

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
    resources = await client.list_resources()
    for resource in resources:
        print(f"Resource: {resource.name} ({resource.uri})")
    
    # Read resource
    content = await client.read_resource("example://resource")
    print(f"Content: {content.text}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

#### Type Hints
```python
from typing import List, Optional, Dict, Any
from mcp.types import (
    Resource,
    ResourceContent,
    Tool,
    ToolResult,
    Prompt,
    PromptMessage,
    TextContent,
    ImageContent,
)

# Custom type definitions
class CustomResource(Resource):
    metadata: Optional[Dict[str, Any]] = None

class CustomTool(Tool):
    category: Optional[str] = None
    tags: List[str] = []
```

### Advanced Features

#### Decorators
```python
# Resource handlers
@server.list_resources()
async def list_resources() -> List[Resource]:
    return [...]

@server.read_resource()
async def read_resource(uri: str) -> ResourceContent:
    return ResourceContent(uri=uri, text="content")

# Tool handlers
@server.list_tools()
async def list_tools() -> List[Tool]:
    return [...]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> ToolResult:
    return ToolResult(content=[...])
```

#### Context Managers
```python
async with Client(name="temp-client", version="1.0.0") as client:
    await client.connect(transport)
    resources = await client.list_resources()
    # Client automatically disconnects
```

#### Error Handling
```python
from mcp.errors import McpError, ErrorCode

@server.read_resource()
async def read_resource(uri: str):
    if not uri.startswith("valid://"):
        raise McpError(
            ErrorCode.INVALID_PARAMS,
            f"Invalid URI scheme: {uri}"
        )
    # ... handle request
```

## C# SDK

### Installation
```xml
<PackageReference Include="ModelContextProtocol" Version="1.0.0" />
```

```bash
dotnet add package ModelContextProtocol
```

### Core Components

#### Server API
```csharp
using MCP.Server;
using MCP.Server.Transport;

// Server configuration
var server = new McpServer(
    name: "example-server",
    version: "1.0.0",
    new ServerCapabilities
    {
        Resources = new ResourceCapabilities(),
        Tools = new ToolCapabilities()
    }
);

// Resource handler
server.OnListResources(async (request) =>
{
    return new ListResourcesResult
    {
        Resources = new[]
        {
            new Resource
            {
                Uri = "example://resource",
                Name = "Example Resource",
                MimeType = "text/plain"
            }
        }
    };
});

// Tool handler
server.OnCallTool(async (request) =>
{
    if (request.Name == "example_tool")
    {
        return new ToolResult
        {
            Content = new[]
            {
                new TextContent { Text = "Tool executed successfully" }
            }
        };
    }
    throw new McpException(ErrorCode.MethodNotFound, $"Unknown tool: {request.Name}");
});

// Start server
var transport = new StdioServerTransport();
await server.ConnectAsync(transport);
```

#### Client API
```csharp
using MCP.Client;
using MCP.Client.Transport;

// Client configuration
var client = new McpClient(
    name: "example-client",
    version: "1.0.0"
);

// Connect to server
var transport = new StdioClientTransport(
    command: "dotnet",
    args: new[] { "server.dll" }
);

await client.ConnectAsync(transport);

// Make requests
var resources = await client.ListResourcesAsync();
foreach (var resource in resources.Resources)
{
    Console.WriteLine($"Resource: {resource.Name} ({resource.Uri})");
}

// Read resource
var content = await client.ReadResourceAsync("example://resource");
Console.WriteLine($"Content: {content.Text}");
```

#### LINQ Support
```csharp
// Query resources
var jsonResources = await client.ListResourcesAsync()
    .Where(r => r.MimeType == "application/json")
    .OrderBy(r => r.Name)
    .ToListAsync();

// Filter tools
var dataTools = await client.ListToolsAsync()
    .Where(t => t.Name.StartsWith("data_"))
    .ToListAsync();
```

### Advanced Features

#### Dependency Injection
```csharp
// In Startup.cs or Program.cs
services.AddMcpServer(options =>
{
    options.Name = "example-server";
    options.Version = "1.0.0";
});

services.AddMcpClient(options =>
{
    options.Name = "example-client";
    options.Version = "1.0.0";
});

// In controller or service
public class MyService
{
    private readonly IMcpClient _client;
    
    public MyService(IMcpClient client)
    {
        _client = client;
    }
}
```

#### Async Enumerables
```csharp
// Stream resources
await foreach (var resource in client.StreamResourcesAsync())
{
    Console.WriteLine($"Resource: {resource.Name}");
}

// Progress tracking
await client.CallToolAsync(
    "long_running_tool",
    arguments,
    progress: new Progress<int>(percent =>
    {
        Console.WriteLine($"Progress: {percent}%");
    })
);
```

## Ruby SDK

### Installation
```ruby
gem install mcp
# or add to Gemfile
gem 'mcp', '~> 1.0'
```

### Core Components

#### Server API
```ruby
require 'mcp'

# Server configuration
server = MCP::Server.new(
  name: 'example-server',
  version: '1.0.0'
)

# Resource handler
server.on_list_resources do
  [
    MCP::Resource.new(
      uri: 'example://resource',
      name: 'Example Resource',
      mime_type: 'text/plain'
    )
  ]
end

# Tool handler
server.on_call_tool do |request|
  case request.name
  when 'example_tool'
    MCP::ToolResult.new(
      content: [
        MCP::TextContent.new(text: 'Tool executed successfully')
      ]
    )
  else
    raise MCP::Error.new(
      code: MCP::ErrorCode::METHOD_NOT_FOUND,
      message: "Unknown tool: #{request.name}"
    )
  end
end

# Start server
transport = MCP::StdioServerTransport.new
server.connect(transport)
server.run
```

#### Client API
```ruby
require 'mcp'

# Client configuration
client = MCP::Client.new(
  name: 'example-client',
  version: '1.0.0'
)

# Connect to server
transport = MCP::StdioClientTransport.new(
  command: 'ruby',
  args: ['server.rb']
)

client.connect(transport)

# Make requests
resources = client.list_resources
resources.each do |resource|
  puts "Resource: #{resource.name} (#{resource.uri})"
end

# Read resource
content = client.read_resource('example://resource')
puts "Content: #{content.text}"
```

#### DSL Support
```ruby
MCP.server do
  name 'example-server'
  version '1.0.0'
  
  resource 'example://config' do
    name 'Configuration'
    mime_type 'application/json'
    
    content do
      { setting: 'value' }.to_json
    end
  end
  
  tool 'process_data' do
    description 'Process data with options'
    
    input_schema do
      property :data, type: :string, required: true
      property :format, type: :string, enum: ['json', 'xml']
    end
    
    execute do |args|
      # Process data
      "Processed: #{args[:data]}"
    end
  end
end
```

## Java SDK

### Installation

#### Maven
```xml
<dependency>
    <groupId>com.modelcontextprotocol</groupId>
    <artifactId>mcp-sdk</artifactId>
    <version>1.0.0</version>
</dependency>
```

#### Gradle
```gradle
implementation 'com.modelcontextprotocol:mcp-sdk:1.0.0'
```

### Core Components

#### Server API
```java
import com.mcp.McpServer;
import com.mcp.transport.StdioServerTransport;
import com.mcp.types.*;

// Server configuration
McpServer server = McpServer.builder()
    .name("example-server")
    .version("1.0.0")
    .capabilities(ServerCapabilities.builder()
        .resources(new ResourceCapabilities())
        .tools(new ToolCapabilities())
        .build())
    .build();

// Resource handler
server.onListResources(request -> {
    return ListResourcesResult.builder()
        .resources(List.of(
            Resource.builder()
                .uri("example://resource")
                .name("Example Resource")
                .mimeType("text/plain")
                .build()
        ))
        .build();
});

// Tool handler
server.onCallTool(request -> {
    if ("example_tool".equals(request.getName())) {
        return ToolResult.builder()
            .content(List.of(
                TextContent.builder()
                    .text("Tool executed successfully")
                    .build()
            ))
            .build();
    }
    throw new McpException(
        ErrorCode.METHOD_NOT_FOUND,
        "Unknown tool: " + request.getName()
    );
});

// Start server
StdioServerTransport transport = new StdioServerTransport();
server.connect(transport);
server.run();
```

#### Client API
```java
import com.mcp.McpClient;
import com.mcp.transport.StdioClientTransport;

// Client configuration
McpClient client = McpClient.builder()
    .name("example-client")
    .version("1.0.0")
    .build();

// Connect to server
StdioClientTransport transport = StdioClientTransport.builder()
    .command("java")
    .args(List.of("-jar", "server.jar"))
    .build();

client.connect(transport);

// Make requests
ListResourcesResult resources = client.listResources();
resources.getResources().forEach(resource -> {
    System.out.println("Resource: " + resource.getName() + 
                      " (" + resource.getUri() + ")");
});

// Read resource
ResourceContent content = client.readResource("example://resource");
System.out.println("Content: " + content.getText());
```

#### Annotations
```java
@McpServer(name = "example-server", version = "1.0.0")
public class ExampleServer {
    
    @ListResources
    public List<Resource> listResources() {
        return List.of(
            new Resource("example://resource", "Example Resource")
        );
    }
    
    @CallTool
    public ToolResult callTool(@ToolName String name, 
                              @Arguments Map<String, Object> args) {
        // Handle tool call
        return new ToolResult(
            List.of(new TextContent("Result"))
        );
    }
}
```

## Go SDK

### Installation
```bash
go get github.com/modelcontextprotocol/go-sdk
```

### Core Components

#### Server API
```go
package main

import (
    "github.com/modelcontextprotocol/go-sdk/server"
    "github.com/modelcontextprotocol/go-sdk/transport"
    "github.com/modelcontextprotocol/go-sdk/types"
)

func main() {
    // Server configuration
    srv := server.NewServer(
        "example-server",
        "1.0.0",
        server.WithCapabilities(&types.ServerCapabilities{
            Resources: &types.ResourceCapabilities{},
            Tools:     &types.ToolCapabilities{},
        }),
    )
    
    // Resource handler
    srv.HandleListResources(func(req *types.Request) (*types.ListResourcesResult, error) {
        return &types.ListResourcesResult{
            Resources: []types.Resource{
                {
                    URI:      "example://resource",
                    Name:     "Example Resource",
                    MimeType: "text/plain",
                },
            },
        }, nil
    })
    
    // Tool handler
    srv.HandleCallTool(func(req *types.CallToolRequest) (*types.ToolResult, error) {
        if req.Name == "example_tool" {
            return &types.ToolResult{
                Content: []types.Content{
                    &types.TextContent{
                        Text: "Tool executed successfully",
                    },
                },
            }, nil
        }
        return nil, types.NewError(
            types.ErrorCodeMethodNotFound,
            "Unknown tool: "+req.Name,
        )
    })
    
    // Start server
    transport := transport.NewStdioServerTransport()
    if err := srv.Connect(transport); err != nil {
        panic(err)
    }
    srv.Run()
}
```

#### Client API
```go
package main

import (
    "fmt"
    "github.com/modelcontextprotocol/go-sdk/client"
    "github.com/modelcontextprotocol/go-sdk/transport"
)

func main() {
    // Client configuration
    c := client.NewClient("example-client", "1.0.0")
    
    // Connect to server
    transport := transport.NewStdioClientTransport(
        "go",
        []string{"run", "server.go"},
    )
    
    if err := c.Connect(transport); err != nil {
        panic(err)
    }
    defer c.Disconnect()
    
    // Make requests
    resources, err := c.ListResources()
    if err != nil {
        panic(err)
    }
    
    for _, resource := range resources.Resources {
        fmt.Printf("Resource: %s (%s)\n", resource.Name, resource.URI)
    }
    
    // Read resource
    content, err := c.ReadResource("example://resource")
    if err != nil {
        panic(err)
    }
    fmt.Printf("Content: %s\n", content.Text)
}
```

#### Goroutine Support
```go
// Concurrent requests
var wg sync.WaitGroup
results := make(chan *types.ToolResult, 10)

for i := 0; i < 10; i++ {
    wg.Add(1)
    go func(id int) {
        defer wg.Done()
        result, err := client.CallTool(
            fmt.Sprintf("tool_%d", id),
            map[string]interface{}{"id": id},
        )
        if err == nil {
            results <- result
        }
    }(i)
}

go func() {
    wg.Wait()
    close(results)
}()

for result := range results {
    fmt.Println("Result:", result)
}
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
All SDKs support protocol version negotiation:
```typescript
// TypeScript
client.protocolVersion // "2025-06-18"

# Python
client.protocol_version # "2025-06-18"

// C#
client.ProtocolVersion // "2025-06-18"

# Ruby
client.protocol_version # "2025-06-18"

// Java
client.getProtocolVersion() // "2025-06-18"

// Go
client.ProtocolVersion() // "2025-06-18"
```

#### Capability Discovery
```typescript
// All SDKs provide capability discovery
const capabilities = await client.getServerCapabilities();
if (capabilities.tools) {
    // Server supports tools
}
```

#### Logging
All SDKs support configurable logging:
```typescript
// TypeScript
server.setLogLevel("debug");

# Python
import logging
logging.getLogger("mcp").setLevel(logging.DEBUG)

// C#
server.LogLevel = LogLevel.Debug;

# Ruby
MCP.logger.level = Logger::DEBUG

// Java
server.setLogLevel(Level.DEBUG);

// Go
server.SetLogLevel(log.DebugLevel)
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
1. **Follow language conventions**: Each SDK should feel native to its language
2. **Maintain type safety**: Use language features for compile-time safety
3. **Write tests**: All features must have comprehensive test coverage
4. **Document thoroughly**: Include examples and API documentation
5. **Ensure compatibility**: Test against multiple protocol versions

### Testing Protocol Compliance
All SDKs include a compliance test suite:
```bash
# Run compliance tests
npm run test:compliance  # TypeScript
python -m mcp.tests.compliance  # Python
dotnet test --filter Category=Compliance  # C#
rspec spec/compliance  # Ruby
mvn test -Dtest=ComplianceTest  # Java
go test ./compliance  # Go
```

## Next Steps

- **Examples**: See complete implementations using each SDK
- **Server Development**: Build servers with your preferred SDK
- **Client Development**: Create clients with your preferred SDK
- **Protocol Specification**: Understand the underlying protocol