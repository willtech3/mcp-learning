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

#### TypeScript/JavaScript
```bash
npm install @modelcontextprotocol/sdk
```

```typescript
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

// Create and connect a client
const client = new Client({
  name: "my-mcp-client",
  version: "1.0.0",
});

const transport = new StdioClientTransport({
  command: "node",
  args: ["path/to/server.js"],
});

await client.connect(transport);

// Use the client
const resources = await client.request("resources/list", {});
console.log("Available resources:", resources);
```

#### Python
```bash
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
```typescript
class MCPClient {
  private transport: Transport;
  private requestId: number = 0;
  private pendingRequests: Map<string | number, PendingRequest>;
  private serverCapabilities: ServerCapabilities;
  
  constructor(private config: ClientConfig) {
    this.pendingRequests = new Map();
  }
  
  async connect(transport: Transport): Promise<void> {
    this.transport = transport;
    
    // Set up message handlers
    this.transport.onMessage(this.handleMessage.bind(this));
    this.transport.onError(this.handleError.bind(this));
    this.transport.onClose(this.handleClose.bind(this));
    
    // Start transport
    await this.transport.start();
    
    // Initialize protocol
    await this.initialize();
  }
  
  async request<T>(method: string, params?: any): Promise<T> {
    const id = ++this.requestId;
    
    return new Promise((resolve, reject) => {
      // Track pending request
      this.pendingRequests.set(id, { resolve, reject });
      
      // Send request
      this.transport.send({
        jsonrpc: "2.0",
        id,
        method,
        params,
      });
      
      // Set timeout
      setTimeout(() => {
        if (this.pendingRequests.has(id)) {
          this.pendingRequests.delete(id);
          reject(new Error(`Request timeout: ${method}`));
        }
      }, 30000);
    });
  }
}
```

## Connection Management

### Transport Selection
```typescript
// stdio transport for local servers
const stdioTransport = new StdioClientTransport({
  command: "node",
  args: ["./server.js"],
  env: {
    NODE_ENV: "production",
  },
});

// HTTP transport for remote servers
const httpTransport = new HttpClientTransport({
  url: "https://api.example.com/mcp",
  headers: {
    Authorization: "Bearer token",
  },
});

// SSE transport for streaming
const sseTransport = new SseClientTransport({
  url: "https://api.example.com/mcp/stream",
});
```

### Connection Lifecycle
```typescript
class ConnectionManager {
  private client: MCPClient;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  
  async connect(): Promise<void> {
    try {
      await this.client.connect(this.transport);
      this.reconnectAttempts = 0;
      console.log("Connected successfully");
    } catch (error) {
      console.error("Connection failed:", error);
      await this.handleConnectionError();
    }
  }
  
  async handleConnectionError(): Promise<void> {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      throw new Error("Max reconnection attempts reached");
    }
    
    this.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
    
    console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
    await new Promise(resolve => setTimeout(resolve, delay));
    
    return this.connect();
  }
  
  async disconnect(): Promise<void> {
    // Send shutdown request
    await this.client.request("shutdown");
    
    // Close transport
    await this.transport.close();
  }
}
```

### Health Monitoring
```typescript
class HealthMonitor {
  private pingInterval: NodeJS.Timer;
  private lastPong: number;
  
  startMonitoring(client: MCPClient): void {
    this.pingInterval = setInterval(async () => {
      try {
        const start = Date.now();
        await client.request("ping");
        const latency = Date.now() - start;
        
        this.lastPong = Date.now();
        this.onHealthCheck({ healthy: true, latency });
      } catch (error) {
        this.onHealthCheck({ healthy: false, error });
      }
    }, 30000);
  }
  
  stopMonitoring(): void {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
    }
  }
  
  private onHealthCheck(status: HealthStatus): void {
    // Emit health status event
    this.emit("health", status);
  }
}
```

## Making Requests

### Basic Request Pattern
```typescript
// Simple request without parameters
const result = await client.request("tools/list");

// Request with parameters
const resource = await client.request("resources/read", {
  uri: "file:///data/config.json",
});

// Request with timeout
const resultWithTimeout = await Promise.race([
  client.request("tools/call", {
    name: "long_running_tool",
    arguments: { data: "..." },
  }),
  new Promise((_, reject) => 
    setTimeout(() => reject(new Error("Timeout")), 60000)
  ),
]);
```

### Batch Requests
```typescript
class BatchRequestClient {
  async batchRequest(requests: Array<{method: string, params?: any}>) {
    // Create batch with unique IDs
    const batch = requests.map((req, index) => ({
      jsonrpc: "2.0",
      id: `batch-${Date.now()}-${index}`,
      method: req.method,
      params: req.params,
    }));
    
    // Send batch
    const responses = await this.client.sendBatch(batch);
    
    // Map responses back to requests
    return responses.sort((a, b) => {
      const aIndex = parseInt(a.id.split('-')[2]);
      const bIndex = parseInt(b.id.split('-')[2]);
      return aIndex - bIndex;
    });
  }
}

// Usage
const results = await batchClient.batchRequest([
  { method: "resources/list" },
  { method: "tools/list" },
  { method: "prompts/list" },
]);
```

### Request Queuing
```typescript
class QueuedClient {
  private queue: Array<QueuedRequest> = [];
  private processing = false;
  private concurrency = 3;
  
  async queueRequest<T>(method: string, params?: any): Promise<T> {
    return new Promise((resolve, reject) => {
      this.queue.push({ method, params, resolve, reject });
      this.processQueue();
    });
  }
  
  private async processQueue(): Promise<void> {
    if (this.processing || this.queue.length === 0) return;
    
    this.processing = true;
    const active = new Set<Promise<any>>();
    
    while (this.queue.length > 0 || active.size > 0) {
      // Start new requests up to concurrency limit
      while (this.queue.length > 0 && active.size < this.concurrency) {
        const request = this.queue.shift()!;
        const promise = this.executeRequest(request)
          .then(result => {
            request.resolve(result);
            active.delete(promise);
          })
          .catch(error => {
            request.reject(error);
            active.delete(promise);
          });
        
        active.add(promise);
      }
      
      // Wait for at least one to complete
      if (active.size > 0) {
        await Promise.race(active);
      }
    }
    
    this.processing = false;
  }
}
```

## Handling Responses

### Response Processing
```typescript
class ResponseHandler {
  handleMessage(message: any): void {
    // Handle responses
    if (message.id !== undefined) {
      this.handleResponse(message);
    }
    // Handle notifications
    else if (message.method) {
      this.handleNotification(message);
    }
  }
  
  private handleResponse(message: any): void {
    const pending = this.pendingRequests.get(message.id);
    if (!pending) return;
    
    this.pendingRequests.delete(message.id);
    
    if (message.error) {
      pending.reject(new MCPError(
        message.error.message,
        message.error.code,
        message.error.data
      ));
    } else {
      pending.resolve(message.result);
    }
  }
  
  private handleNotification(message: any): void {
    switch (message.method) {
      case "notifications/progress":
        this.emit("progress", message.params);
        break;
        
      case "notifications/resources/updated":
        this.emit("resourceUpdated", message.params);
        break;
        
      case "notifications/log":
        this.emit("log", message.params);
        break;
        
      default:
        console.warn("Unknown notification:", message.method);
    }
  }
}
```

### Streaming Responses
```typescript
class StreamingClient {
  async *streamRequest(method: string, params: any): AsyncGenerator<any> {
    const streamId = await this.client.request("stream/start", {
      method,
      params,
    });
    
    try {
      while (true) {
        const chunk = await this.waitForChunk(streamId);
        if (chunk.done) break;
        yield chunk.data;
      }
    } finally {
      // Clean up stream
      await this.client.request("stream/end", { streamId });
    }
  }
  
  // Usage
  async processStream() {
    const stream = this.streamRequest("tools/call", {
      name: "stream_logs",
      arguments: { follow: true },
    });
    
    for await (const log of stream) {
      console.log("Log:", log);
    }
  }
}
```

## Resource Operations

### Resource Discovery
```typescript
class ResourceManager {
  private resourceCache: Map<string, Resource> = new Map();
  
  async listResources(): Promise<Resource[]> {
    const response = await this.client.request("resources/list");
    
    // Cache resources
    response.resources.forEach(resource => {
      this.resourceCache.set(resource.uri, resource);
    });
    
    return response.resources;
  }
  
  async getResourceByPattern(pattern: string): Promise<Resource[]> {
    const resources = await this.listResources();
    const regex = new RegExp(pattern);
    
    return resources.filter(resource => 
      regex.test(resource.uri) || regex.test(resource.name)
    );
  }
}
```

### Reading Resources
```typescript
class ResourceReader {
  private cache: LRUCache<string, any>;
  
  constructor(cacheSize: number = 100) {
    this.cache = new LRUCache({ max: cacheSize });
  }
  
  async readResource(uri: string, options?: ReadOptions): Promise<any> {
    // Check cache first
    const cacheKey = `${uri}:${JSON.stringify(options)}`;
    if (this.cache.has(cacheKey) && !options?.noCache) {
      return this.cache.get(cacheKey);
    }
    
    // Read from server
    const response = await this.client.request("resources/read", {
      uri,
      ...options,
    });
    
    // Process content based on type
    const content = this.processContent(response.contents[0]);
    
    // Cache result
    this.cache.set(cacheKey, content);
    
    return content;
  }
  
  private processContent(content: ResourceContent): any {
    switch (content.mimeType) {
      case "application/json":
        return JSON.parse(content.text);
        
      case "text/plain":
        return content.text;
        
      case "application/octet-stream":
        return Buffer.from(content.blob, "base64");
        
      default:
        return content;
    }
  }
}
```

### Resource Subscriptions
```typescript
class ResourceSubscriber {
  private subscriptions: Map<string, Subscription> = new Map();
  
  async subscribe(uri: string, callback: (change: any) => void): Promise<string> {
    // Subscribe on server
    const { subscriptionId } = await this.client.request("resources/subscribe", {
      uri,
    });
    
    // Track subscription
    this.subscriptions.set(subscriptionId, {
      uri,
      callback,
    });
    
    // Listen for updates
    this.client.on("resourceUpdated", (params) => {
      if (params.subscriptionId === subscriptionId) {
        callback(params.change);
      }
    });
    
    return subscriptionId;
  }
  
  async unsubscribe(subscriptionId: string): Promise<void> {
    await this.client.request("resources/unsubscribe", {
      subscriptionId,
    });
    
    this.subscriptions.delete(subscriptionId);
  }
  
  async unsubscribeAll(): Promise<void> {
    const promises = Array.from(this.subscriptions.keys()).map(id =>
      this.unsubscribe(id)
    );
    
    await Promise.all(promises);
  }
}
```

## Tool Execution

### Tool Discovery and Validation
```typescript
class ToolManager {
  private toolSchemas: Map<string, ToolSchema> = new Map();
  
  async listTools(): Promise<Tool[]> {
    const response = await this.client.request("tools/list");
    
    // Cache tool schemas
    response.tools.forEach(tool => {
      this.toolSchemas.set(tool.name, tool);
    });
    
    return response.tools;
  }
  
  validateArguments(toolName: string, args: any): ValidationResult {
    const schema = this.toolSchemas.get(toolName);
    if (!schema) {
      return {
        valid: false,
        errors: [`Unknown tool: ${toolName}`],
      };
    }
    
    // Validate against JSON schema
    return validateJsonSchema(args, schema.inputSchema);
  }
}
```

### Tool Execution with Progress
```typescript
class ToolExecutor {
  async executeTool(
    name: string,
    args: any,
    onProgress?: (progress: Progress) => void
  ): Promise<ToolResult> {
    // Validate arguments
    const validation = this.toolManager.validateArguments(name, args);
    if (!validation.valid) {
      throw new Error(`Invalid arguments: ${validation.errors.join(", ")}`);
    }
    
    // Set up progress listener
    const progressHandler = (params: any) => {
      if (onProgress) {
        onProgress(params);
      }
    };
    
    this.client.on("progress", progressHandler);
    
    try {
      // Execute tool
      const result = await this.client.request("tools/call", {
        name,
        arguments: args,
      });
      
      return result;
    } finally {
      // Clean up listener
      this.client.off("progress", progressHandler);
    }
  }
}

// Usage
const executor = new ToolExecutor();
const result = await executor.executeTool(
  "process_data",
  { input: "data.csv" },
  (progress) => {
    console.log(`Progress: ${progress.progress}% - ${progress.message}`);
  }
);
```

### Tool Result Processing
```typescript
class ToolResultProcessor {
  processResult(result: ToolResult): ProcessedResult {
    const processed: ProcessedResult = {
      text: [],
      images: [],
      resources: [],
      metadata: {},
    };
    
    for (const content of result.content) {
      switch (content.type) {
        case "text":
          processed.text.push(content.text);
          break;
          
        case "image":
          processed.images.push({
            data: content.data,
            mimeType: content.mimeType,
          });
          break;
          
        case "resource":
          processed.resources.push(content.uri);
          break;
          
        default:
          console.warn(`Unknown content type: ${content.type}`);
      }
    }
    
    return processed;
  }
  
  async saveResults(result: ProcessedResult, outputDir: string): Promise<void> {
    // Save text content
    if (result.text.length > 0) {
      await fs.writeFile(
        path.join(outputDir, "output.txt"),
        result.text.join("\n")
      );
    }
    
    // Save images
    for (let i = 0; i < result.images.length; i++) {
      const image = result.images[i];
      const ext = image.mimeType.split("/")[1];
      await fs.writeFile(
        path.join(outputDir, `image-${i}.${ext}`),
        Buffer.from(image.data, "base64")
      );
    }
  }
}
```

## Prompt Management

### Prompt Discovery
```typescript
class PromptManager {
  private promptCache: Map<string, Prompt> = new Map();
  
  async listPrompts(): Promise<Prompt[]> {
    const response = await this.client.request("prompts/list");
    
    response.prompts.forEach(prompt => {
      this.promptCache.set(prompt.name, prompt);
    });
    
    return response.prompts;
  }
  
  async getPrompt(name: string, args: any): Promise<PromptResult> {
    // Validate arguments
    const prompt = this.promptCache.get(name);
    if (!prompt) {
      throw new Error(`Unknown prompt: ${name}`);
    }
    
    // Check required arguments
    const missing = prompt.arguments
      .filter(arg => arg.required && !(arg.name in args))
      .map(arg => arg.name);
      
    if (missing.length > 0) {
      throw new Error(`Missing required arguments: ${missing.join(", ")}`);
    }
    
    // Get prompt content
    return await this.client.request("prompts/get", {
      name,
      arguments: args,
    });
  }
}
```

### Prompt Integration with LLMs
```typescript
class LLMIntegration {
  constructor(
    private mcpClient: MCPClient,
    private llmClient: LLMClient
  ) {}
  
  async executePrompt(
    promptName: string,
    args: any,
    llmOptions?: LLMOptions
  ): Promise<string> {
    // Get prompt from MCP server
    const promptResult = await this.mcpClient.request("prompts/get", {
      name: promptName,
      arguments: args,
    });
    
    // Convert to LLM format
    const messages = promptResult.messages.map(msg => ({
      role: msg.role,
      content: msg.content.type === "text" ? msg.content.text : msg.content,
    }));
    
    // Send to LLM
    const completion = await this.llmClient.complete({
      messages,
      ...llmOptions,
    });
    
    return completion.content;
  }
  
  async chainPrompts(
    prompts: Array<{name: string, args: any}>
  ): Promise<string[]> {
    const results: string[] = [];
    let context = {};
    
    for (const prompt of prompts) {
      // Include previous results in arguments
      const enrichedArgs = {
        ...prompt.args,
        previousResults: results,
        context,
      };
      
      const result = await this.executePrompt(prompt.name, enrichedArgs);
      results.push(result);
      
      // Extract context for next prompt
      context = this.extractContext(result);
    }
    
    return results;
  }
}
```

## Error Handling

### Comprehensive Error Handling
```typescript
class MCPError extends Error {
  constructor(
    message: string,
    public code: number,
    public data?: any
  ) {
    super(message);
    this.name = "MCPError";
  }
}

class ErrorHandler {
  async handleRequest<T>(
    operation: () => Promise<T>,
    options: ErrorHandlingOptions = {}
  ): Promise<T> {
    const {
      retries = 3,
      retryDelay = 1000,
      onError,
      fallback,
    } = options;
    
    let lastError: Error;
    
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        return await operation();
      } catch (error) {
        lastError = error;
        
        if (onError) {
          onError(error, attempt);
        }
        
        // Check if error is retryable
        if (!this.isRetryable(error) || attempt === retries) {
          break;
        }
        
        // Wait before retry
        await new Promise(resolve => 
          setTimeout(resolve, retryDelay * Math.pow(2, attempt))
        );
      }
    }
    
    // Use fallback if provided
    if (fallback) {
      return fallback(lastError);
    }
    
    throw lastError;
  }
  
  private isRetryable(error: any): boolean {
    if (error instanceof MCPError) {
      // Don't retry client errors
      return error.code < -32000 || error.code > -32099;
    }
    
    // Retry network errors
    return error.code === "ECONNRESET" ||
           error.code === "ETIMEDOUT" ||
           error.code === "ENOTFOUND";
  }
}
```

### Circuit Breaker Pattern
```typescript
class CircuitBreaker {
  private failures = 0;
  private lastFailureTime = 0;
  private state: "closed" | "open" | "half-open" = "closed";
  
  constructor(
    private threshold: number = 5,
    private timeout: number = 60000
  ) {}
  
  async execute<T>(operation: () => Promise<T>): Promise<T> {
    if (this.state === "open") {
      if (Date.now() - this.lastFailureTime > this.timeout) {
        this.state = "half-open";
      } else {
        throw new Error("Circuit breaker is open");
      }
    }
    
    try {
      const result = await operation();
      this.onSuccess();
      return result;
    } catch (error) {
      this.onFailure();
      throw error;
    }
  }
  
  private onSuccess(): void {
    this.failures = 0;
    this.state = "closed";
  }
  
  private onFailure(): void {
    this.failures++;
    this.lastFailureTime = Date.now();
    
    if (this.failures >= this.threshold) {
      this.state = "open";
    }
  }
}
```

## Advanced Features

### Multi-Server Management
```typescript
class MultiServerClient {
  private clients: Map<string, MCPClient> = new Map();
  
  async addServer(id: string, config: ServerConfig): Promise<void> {
    const client = new MCPClient(config.clientConfig);
    const transport = this.createTransport(config.transport);
    
    await client.connect(transport);
    this.clients.set(id, client);
  }
  
  async request(serverId: string, method: string, params?: any): Promise<any> {
    const client = this.clients.get(serverId);
    if (!client) {
      throw new Error(`Unknown server: ${serverId}`);
    }
    
    return client.request(method, params);
  }
  
  async broadcast(method: string, params?: any): Promise<Map<string, any>> {
    const results = new Map<string, any>();
    
    const promises = Array.from(this.clients.entries()).map(
      async ([id, client]) => {
        try {
          const result = await client.request(method, params);
          results.set(id, { success: true, result });
        } catch (error) {
          results.set(id, { success: false, error });
        }
      }
    );
    
    await Promise.all(promises);
    return results;
  }
}
```

### Request Caching
```typescript
class CachedClient {
  private cache: Map<string, CacheEntry> = new Map();
  
  async request<T>(
    method: string,
    params?: any,
    options?: CacheOptions
  ): Promise<T> {
    const cacheKey = this.getCacheKey(method, params);
    
    // Check cache
    if (options?.useCache !== false) {
      const cached = this.cache.get(cacheKey);
      if (cached && !this.isExpired(cached)) {
        return cached.value as T;
      }
    }
    
    // Make request
    const result = await this.client.request<T>(method, params);
    
    // Cache result
    if (options?.cache !== false && this.isCacheable(method)) {
      this.cache.set(cacheKey, {
        value: result,
        timestamp: Date.now(),
        ttl: options?.ttl || this.getDefaultTTL(method),
      });
    }
    
    return result;
  }
  
  private getCacheKey(method: string, params: any): string {
    return `${method}:${JSON.stringify(params)}`;
  }
  
  private isExpired(entry: CacheEntry): boolean {
    return Date.now() - entry.timestamp > entry.ttl;
  }
  
  private isCacheable(method: string): boolean {
    // Only cache read operations
    return method.startsWith("resources/") ||
           method === "tools/list" ||
           method === "prompts/list";
  }
}
```

### Request Middleware
```typescript
class MiddlewareClient {
  private middleware: Middleware[] = [];
  
  use(middleware: Middleware): void {
    this.middleware.push(middleware);
  }
  
  async request<T>(method: string, params?: any): Promise<T> {
    let index = 0;
    
    const next = async (): Promise<T> => {
      if (index >= this.middleware.length) {
        return this.client.request<T>(method, params);
      }
      
      const middleware = this.middleware[index++];
      return middleware(method, params, next);
    };
    
    return next();
  }
}

// Example middleware
const loggingMiddleware: Middleware = async (method, params, next) => {
  console.log(`Request: ${method}`, params);
  const start = Date.now();
  
  try {
    const result = await next();
    console.log(`Response: ${method} (${Date.now() - start}ms)`);
    return result;
  } catch (error) {
    console.error(`Error: ${method}`, error);
    throw error;
  }
};

const authMiddleware: Middleware = async (method, params, next) => {
  // Add authentication token
  const enrichedParams = {
    ...params,
    auth: await getAuthToken(),
  };
  
  return next(method, enrichedParams);
};
```

## Testing Clients

### Unit Testing
```typescript
import { describe, it, expect, vi } from "vitest";
import { MockTransport } from "@modelcontextprotocol/sdk/testing";

describe("MCP Client", () => {
  let client: MCPClient;
  let transport: MockTransport;
  
  beforeEach(() => {
    transport = new MockTransport();
    client = new MCPClient({ name: "test", version: "1.0.0" });
  });
  
  it("should list resources", async () => {
    // Set up mock response
    transport.mockResponse("resources/list", {
      resources: [
        {
          uri: "test://resource",
          name: "Test Resource",
          mimeType: "text/plain",
        },
      ],
    });
    
    await client.connect(transport);
    const result = await client.request("resources/list");
    
    expect(result.resources).toHaveLength(1);
    expect(result.resources[0].uri).toBe("test://resource");
  });
  
  it("should handle errors", async () => {
    transport.mockError("tools/call", {
      code: -32003,
      message: "Tool execution failed",
    });
    
    await client.connect(transport);
    
    await expect(
      client.request("tools/call", { name: "test" })
    ).rejects.toThrow("Tool execution failed");
  });
});
```

### Integration Testing
```typescript
describe("MCP Client Integration", () => {
  let client: MCPClient;
  let server: TestServer;
  
  beforeAll(async () => {
    // Start test server
    server = new TestServer();
    await server.start();
    
    // Connect client
    client = new MCPClient({ name: "test", version: "1.0.0" });
    const transport = new HttpClientTransport({
      url: `http://localhost:${server.port}/mcp`,
    });
    await client.connect(transport);
  });
  
  afterAll(async () => {
    await client.disconnect();
    await server.stop();
  });
  
  it("should execute full workflow", async () => {
    // List resources
    const resources = await client.request("resources/list");
    expect(resources.resources).toHaveLength(2);
    
    // Read resource
    const content = await client.request("resources/read", {
      uri: resources.resources[0].uri,
    });
    expect(content.contents).toHaveLength(1);
    
    // Execute tool
    const toolResult = await client.request("tools/call", {
      name: "process_data",
      arguments: {
        data: content.contents[0].text,
      },
    });
    expect(toolResult.content[0].type).toBe("text");
  });
});
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
```typescript
class ProductionMCPClient {
  private client: MCPClient;
  private errorHandler: ErrorHandler;
  private circuitBreaker: CircuitBreaker;
  private metrics: MetricsCollector;
  private cache: CachedClient;
  
  constructor(config: ProductionConfig) {
    this.client = new MCPClient(config.client);
    this.errorHandler = new ErrorHandler();
    this.circuitBreaker = new CircuitBreaker(config.circuitBreaker);
    this.metrics = new MetricsCollector(config.metrics);
    this.cache = new CachedClient(this.client, config.cache);
    
    this.setupMiddleware();
  }
  
  private setupMiddleware(): void {
    // Metrics middleware
    this.client.use(async (method, params, next) => {
      const start = Date.now();
      try {
        const result = await next();
        this.metrics.recordSuccess(method, Date.now() - start);
        return result;
      } catch (error) {
        this.metrics.recordError(method, error);
        throw error;
      }
    });
    
    // Circuit breaker middleware
    this.client.use(async (method, params, next) => {
      return this.circuitBreaker.execute(() => next());
    });
  }
  
  async request<T>(method: string, params?: any): Promise<T> {
    return this.errorHandler.handleRequest(
      () => this.cache.request<T>(method, params),
      {
        retries: 3,
        onError: (error, attempt) => {
          console.error(`Request failed (attempt ${attempt}):`, error);
        },
      }
    );
  }
}
```

## Next Steps

- **SDK Reference**: Detailed SDK API documentation
- **Examples**: Complete client implementations
- **Server Development**: Building servers for your clients
- **Best Practices**: Production deployment guide