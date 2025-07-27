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
- Node.js 18+ (for TypeScript/JavaScript)
- Python 3.8+ (for Python)
- Basic understanding of JSON-RPC 2.0
- Familiarity with async programming

### Quick Start

#### TypeScript/JavaScript
```bash
# Install the MCP SDK
npm install @modelcontextprotocol/sdk

# Create a new server
npx @modelcontextprotocol/create-server my-server
cd my-server
npm install
npm start
```

#### Python
```bash
# Install the MCP SDK
pip install mcp

# Create a new server
mcp create-server my-server
cd my-server
pip install -r requirements.txt
python server.py
```

### Minimal Server Example

```typescript
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new Server(
  {
    name: "my-first-server",
    version: "1.0.0",
  },
  {
    capabilities: {
      resources: {},
      tools: {},
    },
  }
);

// Add a simple resource
server.setRequestHandler("resources/list", async () => {
  return {
    resources: [
      {
        uri: "greeting://hello",
        name: "Hello Message",
        description: "A friendly greeting",
        mimeType: "text/plain",
      },
    ],
  };
});

server.setRequestHandler("resources/read", async (request) => {
  const { uri } = request.params;
  if (uri === "greeting://hello") {
    return {
      contents: [
        {
          uri: "greeting://hello",
          mimeType: "text/plain",
          text: "Hello from MCP!",
        },
      ],
    };
  }
  throw new Error("Resource not found");
});

// Start the server
const transport = new StdioServerTransport();
await server.connect(transport);
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
```typescript
interface ServerConfig {
  name: string;           // Server identifier
  version: string;        // Server version
  capabilities: {         // Advertised capabilities
    resources?: {};
    tools?: {};
    prompts?: {};
    logging?: {};
    experimental?: {};
  };
}
```

### Request Handlers
Request handlers are the core of your server implementation:

```typescript
// Generic handler type
server.setRequestHandler(method: string, handler: RequestHandler);

// Specific handler examples
server.setRequestHandler("initialize", async (request) => {
  // Initialization logic
  return {
    protocolVersion: "2025-06-18",
    capabilities: server.capabilities,
    serverInfo: {
      name: server.name,
      version: server.version,
    },
  };
});
```

## Resources

Resources expose data that clients can read. Think of them as GET endpoints in a REST API.

### Basic Resource Implementation
```typescript
// List available resources
server.setRequestHandler("resources/list", async () => {
  return {
    resources: [
      {
        uri: "file:///data/config.json",
        name: "Configuration",
        description: "Server configuration file",
        mimeType: "application/json",
      },
      {
        uri: "db://users",
        name: "User Database",
        description: "All user records",
        mimeType: "application/json",
      },
    ],
  };
});

// Read a specific resource
server.setRequestHandler("resources/read", async (request) => {
  const { uri } = request.params;
  
  switch (uri) {
    case "file:///data/config.json":
      const config = await readConfigFile();
      return {
        contents: [
          {
            uri,
            mimeType: "application/json",
            text: JSON.stringify(config, null, 2),
          },
        ],
      };
      
    case "db://users":
      const users = await queryDatabase("SELECT * FROM users");
      return {
        contents: [
          {
            uri,
            mimeType: "application/json",
            text: JSON.stringify(users),
          },
        ],
      };
      
    default:
      throw new Error(`Resource not found: ${uri}`);
  }
});
```

### Dynamic Resources with Templates
```typescript
// Resource with URI template
const userResourceTemplate = {
  uri: "db://users/{userId}",
  name: "User Details",
  description: "Get specific user information",
  mimeType: "application/json",
};

// Handle templated URIs
server.setRequestHandler("resources/read", async (request) => {
  const { uri } = request.params;
  
  // Parse URI template
  const userMatch = uri.match(/^db:\/\/users\/(\d+)$/);
  if (userMatch) {
    const userId = userMatch[1];
    const user = await queryDatabase(
      "SELECT * FROM users WHERE id = ?",
      [userId]
    );
    
    return {
      contents: [
        {
          uri,
          mimeType: "application/json",
          text: JSON.stringify(user),
        },
      ],
    };
  }
});
```

### Resource Subscriptions
```typescript
// Track subscriptions
const subscriptions = new Map();

server.setRequestHandler("resources/subscribe", async (request) => {
  const { uri } = request.params;
  const subscriptionId = generateId();
  
  // Set up file watcher, database trigger, etc.
  const watcher = watchResource(uri, (change) => {
    // Send notification on change
    server.notification({
      method: "notifications/resources/updated",
      params: {
        uri,
        subscriptionId,
        change,
      },
    });
  });
  
  subscriptions.set(subscriptionId, watcher);
  
  return { subscriptionId };
});

server.setRequestHandler("resources/unsubscribe", async (request) => {
  const { subscriptionId } = request.params;
  const watcher = subscriptions.get(subscriptionId);
  if (watcher) {
    watcher.stop();
    subscriptions.delete(subscriptionId);
  }
  return {};
});
```

## Tools

Tools provide executable functionality with potential side effects. Think of them as POST endpoints in a REST API.

### Basic Tool Implementation
```typescript
// List available tools
server.setRequestHandler("tools/list", async () => {
  return {
    tools: [
      {
        name: "create_file",
        description: "Create a new file with content",
        inputSchema: {
          type: "object",
          properties: {
            path: {
              type: "string",
              description: "File path",
            },
            content: {
              type: "string",
              description: "File content",
            },
          },
          required: ["path", "content"],
        },
      },
      {
        name: "send_email",
        description: "Send an email",
        inputSchema: {
          type: "object",
          properties: {
            to: {
              type: "string",
              format: "email",
            },
            subject: {
              type: "string",
            },
            body: {
              type: "string",
            },
          },
          required: ["to", "subject", "body"],
        },
      },
    ],
  };
});

// Execute tools
server.setRequestHandler("tools/call", async (request) => {
  const { name, arguments: args } = request.params;
  
  switch (name) {
    case "create_file":
      await fs.writeFile(args.path, args.content);
      return {
        content: [
          {
            type: "text",
            text: `File created at ${args.path}`,
          },
        ],
      };
      
    case "send_email":
      const result = await sendEmail(args.to, args.subject, args.body);
      return {
        content: [
          {
            type: "text",
            text: `Email sent to ${args.to}`,
          },
        ],
      };
      
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
});
```

### Advanced Tool Features

#### Progress Reporting
```typescript
server.setRequestHandler("tools/call", async (request) => {
  const { name, arguments: args } = request.params;
  
  if (name === "process_large_dataset") {
    const totalItems = args.items.length;
    
    for (let i = 0; i < totalItems; i++) {
      // Process item
      await processItem(args.items[i]);
      
      // Send progress notification
      server.notification({
        method: "notifications/progress",
        params: {
          progress: Math.round((i + 1) / totalItems * 100),
          message: `Processing item ${i + 1} of ${totalItems}`,
        },
      });
    }
    
    return {
      content: [
        {
          type: "text",
          text: `Processed ${totalItems} items successfully`,
        },
      ],
    };
  }
});
```

#### Streaming Results
```typescript
server.setRequestHandler("tools/call", async (request) => {
  const { name, arguments: args } = request.params;
  
  if (name === "stream_logs") {
    const logStream = createLogStream(args.filter);
    const results = [];
    
    for await (const log of logStream) {
      results.push(log);
      
      // Send intermediate results
      server.notification({
        method: "notifications/tools/output",
        params: {
          toolName: name,
          output: {
            type: "text",
            text: log,
          },
        },
      });
    }
    
    return {
      content: [
        {
          type: "text",
          text: results.join("\n"),
        },
      ],
    };
  }
});
```

## Prompts

Prompts provide reusable templates for LLM interactions, allowing servers to guide AI behavior.

### Basic Prompt Implementation
```typescript
// List available prompts
server.setRequestHandler("prompts/list", async () => {
  return {
    prompts: [
      {
        name: "analyze_code",
        description: "Analyze code for issues and improvements",
        arguments: [
          {
            name: "code",
            description: "The code to analyze",
            required: true,
          },
          {
            name: "language",
            description: "Programming language",
            required: false,
          },
        ],
      },
      {
        name: "generate_report",
        description: "Generate a report from data",
        arguments: [
          {
            name: "data",
            description: "The data to analyze",
            required: true,
          },
          {
            name: "format",
            description: "Report format (pdf, html, markdown)",
            required: false,
          },
        ],
      },
    ],
  };
});

// Get prompt content
server.setRequestHandler("prompts/get", async (request) => {
  const { name, arguments: args } = request.params;
  
  switch (name) {
    case "analyze_code":
      return {
        description: "Code analysis prompt",
        messages: [
          {
            role: "user",
            content: {
              type: "text",
              text: `Please analyze the following ${args.language || "code"} and provide:
1. Potential bugs or issues
2. Performance improvements
3. Code style suggestions
4. Security considerations

Code:
\`\`\`${args.language || ""}
${args.code}
\`\`\``,
            },
          },
        ],
      };
      
    case "generate_report":
      const analysisResult = analyzeData(args.data);
      return {
        description: "Report generation prompt",
        messages: [
          {
            role: "user",
            content: {
              type: "text",
              text: `Generate a comprehensive report in ${args.format || "markdown"} format based on the following data analysis:

${JSON.stringify(analysisResult, null, 2)}

Include:
- Executive summary
- Key findings
- Detailed analysis
- Recommendations`,
            },
          },
        ],
      };
      
    default:
      throw new Error(`Unknown prompt: ${name}`);
  }
});
```

## Server Lifecycle

### Initialization Phase
```typescript
class MyMCPServer {
  async initialize(request) {
    // Validate client capabilities
    const clientVersion = request.params.protocolVersion;
    if (!this.isVersionSupported(clientVersion)) {
      throw new Error(`Unsupported protocol version: ${clientVersion}`);
    }
    
    // Initialize server resources
    await this.connectDatabase();
    await this.loadConfiguration();
    
    // Return server capabilities
    return {
      protocolVersion: "2025-06-18",
      capabilities: {
        resources: {
          subscribe: true,
          templates: true,
        },
        tools: {
          streaming: true,
        },
        prompts: {},
        logging: {
          levels: ["debug", "info", "warn", "error"],
        },
      },
      serverInfo: {
        name: this.name,
        version: this.version,
      },
    };
  }
}
```

### Shutdown Handling
```typescript
server.setRequestHandler("shutdown", async () => {
  // Clean up resources
  await closeDatabase();
  await saveState();
  
  // Stop background tasks
  cancelAllSubscriptions();
  stopBackgroundJobs();
  
  return {};
});

// Handle process termination
process.on("SIGINT", async () => {
  await server.close();
  process.exit(0);
});

process.on("SIGTERM", async () => {
  await server.close();
  process.exit(0);
});
```

## Error Handling

### Error Response Format
```typescript
class MCPError extends Error {
  constructor(message, code, data) {
    super(message);
    this.code = code;
    this.data = data;
  }
}

// Standard error codes
const ErrorCodes = {
  ParseError: -32700,
  InvalidRequest: -32600,
  MethodNotFound: -32601,
  InvalidParams: -32602,
  InternalError: -32603,
  
  // MCP-specific errors
  ResourceNotFound: -32001,
  ResourceAccessDenied: -32002,
  ToolExecutionFailed: -32003,
  InvalidToolArguments: -32004,
  PromptNotFound: -32005,
};
```

### Error Handling Best Practices
```typescript
server.setRequestHandler("tools/call", async (request) => {
  const { name, arguments: args } = request.params;
  
  try {
    // Validate tool exists
    const tool = await getToolDefinition(name);
    if (!tool) {
      throw new MCPError(
        `Tool not found: ${name}`,
        ErrorCodes.MethodNotFound
      );
    }
    
    // Validate arguments
    const validation = validateArguments(args, tool.inputSchema);
    if (!validation.valid) {
      throw new MCPError(
        "Invalid tool arguments",
        ErrorCodes.InvalidToolArguments,
        { errors: validation.errors }
      );
    }
    
    // Execute tool with timeout
    const result = await withTimeout(
      executeTool(name, args),
      30000,
      `Tool execution timeout: ${name}`
    );
    
    return result;
    
  } catch (error) {
    // Log error for debugging
    logger.error(`Tool execution failed: ${name}`, error);
    
    // Return appropriate error response
    if (error instanceof MCPError) {
      throw error;
    }
    
    // Wrap unexpected errors
    throw new MCPError(
      "Internal server error",
      ErrorCodes.InternalError,
      { 
        tool: name,
        message: error.message 
      }
    );
  }
});
```

## Testing

### Unit Testing
```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { TestClient } from "@modelcontextprotocol/sdk/testing";

describe("MCP Server", () => {
  let client;
  let server;
  
  beforeEach(async () => {
    server = createTestServer();
    client = new TestClient(server);
    await client.initialize();
  });
  
  describe("Resources", () => {
    it("should list available resources", async () => {
      const response = await client.request("resources/list");
      expect(response.resources).toHaveLength(2);
      expect(response.resources[0].uri).toBe("file:///config.json");
    });
    
    it("should read resource content", async () => {
      const response = await client.request("resources/read", {
        uri: "file:///config.json",
      });
      expect(response.contents[0].mimeType).toBe("application/json");
      expect(JSON.parse(response.contents[0].text)).toHaveProperty("version");
    });
  });
  
  describe("Tools", () => {
    it("should execute tool successfully", async () => {
      const response = await client.request("tools/call", {
        name: "create_file",
        arguments: {
          path: "/tmp/test.txt",
          content: "Hello, MCP!",
        },
      });
      expect(response.content[0].text).toContain("File created");
    });
    
    it("should validate tool arguments", async () => {
      await expect(
        client.request("tools/call", {
          name: "create_file",
          arguments: {
            // Missing required 'content' field
            path: "/tmp/test.txt",
          },
        })
      ).rejects.toThrow("Invalid tool arguments");
    });
  });
});
```

### Integration Testing
```typescript
describe("MCP Server Integration", () => {
  it("should handle concurrent requests", async () => {
    const promises = Array.from({ length: 10 }, (_, i) =>
      client.request("tools/call", {
        name: "process_data",
        arguments: { id: i },
      })
    );
    
    const results = await Promise.all(promises);
    expect(results).toHaveLength(10);
    results.forEach((result, i) => {
      expect(result.content[0].text).toContain(`Processed: ${i}`);
    });
  });
  
  it("should maintain state across requests", async () => {
    // Create a session
    const createResponse = await client.request("tools/call", {
      name: "create_session",
      arguments: { userId: "test-user" },
    });
    const sessionId = JSON.parse(createResponse.content[0].text).sessionId;
    
    // Use the session
    const useResponse = await client.request("tools/call", {
      name: "use_session",
      arguments: { sessionId },
    });
    expect(useResponse.content[0].text).toContain("test-user");
  });
});
```

## Deployment

### Docker Deployment
```dockerfile
FROM node:18-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci --only=production

COPY . .

# Security: Run as non-root user
RUN addgroup -g 1001 -S nodejs
RUN adduser -S nodejs -u 1001
USER nodejs

EXPOSE 3000

CMD ["node", "server.js"]
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
```typescript
server.setRequestHandler("health", async () => {
  const checks = {
    server: "healthy",
    database: await checkDatabaseConnection(),
    memory: process.memoryUsage().heapUsed < 500 * 1024 * 1024 ? "healthy" : "warning",
    uptime: process.uptime(),
  };
  
  const isHealthy = Object.values(checks).every(
    (status) => status === "healthy" || typeof status === "number"
  );
  
  return {
    status: isHealthy ? "healthy" : "degraded",
    checks,
  };
});
```

#### Monitoring
```typescript
import { createMetricsCollector } from "./metrics";

const metrics = createMetricsCollector();

// Track request metrics
server.use(async (request, next) => {
  const start = Date.now();
  const method = request.method;
  
  try {
    const response = await next();
    metrics.recordRequest(method, "success", Date.now() - start);
    return response;
  } catch (error) {
    metrics.recordRequest(method, "error", Date.now() - start);
    throw error;
  }
});

// Expose metrics endpoint
server.setRequestHandler("metrics", async () => {
  return {
    metrics: metrics.getAll(),
  };
});
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
```typescript
{
  name: "query_database",
  description: "Execute a safe database query with pagination",
  inputSchema: {
    type: "object",
    properties: {
      table: {
        type: "string",
        enum: ["users", "orders", "products"],
        description: "Table to query",
      },
      filters: {
        type: "object",
        description: "Filter conditions",
        additionalProperties: {
          type: "string",
        },
      },
      limit: {
        type: "integer",
        minimum: 1,
        maximum: 100,
        default: 10,
        description: "Number of results to return",
      },
      offset: {
        type: "integer",
        minimum: 0,
        default: 0,
        description: "Number of results to skip",
      },
    },
    required: ["table"],
  },
}
```

## Next Steps

- **Client Development**: Learn to build MCP clients
- **SDK Reference**: Explore SDK capabilities
- **Examples**: See complete server implementations
- **Security**: Implement secure MCP servers