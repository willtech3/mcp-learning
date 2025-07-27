# Model Context Protocol (MCP) - Transport Layer

## Table of Contents
- [Overview](#overview)
- [Transport Requirements](#transport-requirements)
- [stdio Transport](#stdio-transport)
- [HTTP with SSE Transport](#http-with-sse-transport)
- [Streamable HTTP Transport](#streamable-http-transport)
- [Transport Selection](#transport-selection)
- [Message Framing](#message-framing)
- [Connection Management](#connection-management)
- [Error Handling](#error-handling)
- [Performance Considerations](#performance-considerations)
- [Future Transports](#future-transports)

## Overview

The Model Context Protocol supports multiple transport mechanisms for communication between clients and servers. Each transport provides different trade-offs in terms of complexity, performance, and deployment scenarios. All transports carry the same JSON-RPC 2.0 messages defined in the protocol specification.

## Transport Requirements

All MCP transports MUST:
- Support bidirectional message exchange
- Preserve message ordering within a direction
- Handle UTF-8 encoded JSON messages
- Support messages up to 64MB in size
- Provide connection lifecycle management
- Handle graceful disconnection

All transports SHOULD:
- Support message batching
- Provide backpressure mechanisms
- Enable progress notifications
- Support request cancellation

## stdio Transport

The stdio (standard input/output) transport is the simplest transport mechanism, using process pipes for communication.

### Overview
- Server reads from stdin and writes to stdout
- Client spawns server process and communicates via pipes
- Messages are newline-delimited JSON
- Ideal for local process communication

### Message Format
```
<json-rpc-message>\n
<json-rpc-message>\n
...
```

### Implementation Details

#### Server Implementation
```typescript
// Read messages from stdin
const readline = require('readline');
const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
  terminal: false
});

rl.on('line', (line) => {
  try {
    const message = JSON.parse(line);
    handleMessage(message);
  } catch (error) {
    sendError('Parse error', -32700);
  }
});

// Write messages to stdout
function sendMessage(message) {
  process.stdout.write(JSON.stringify(message) + '\n');
}
```

#### Client Implementation
```typescript
import { spawn } from 'child_process';

const server = spawn('node', ['server.js']);

// Send message to server
function sendToServer(message) {
  server.stdin.write(JSON.stringify(message) + '\n');
}

// Read messages from server
server.stdout.on('data', (data) => {
  const lines = data.toString().split('\n');
  for (const line of lines) {
    if (line.trim()) {
      const message = JSON.parse(line);
      handleServerMessage(message);
    }
  }
});
```

### Advantages
- Simple to implement
- No network configuration
- Low latency
- Direct process control

### Disadvantages
- Limited to local communication
- Platform-specific process handling
- No built-in authentication
- Limited scalability

### Use Cases
- Desktop applications (Claude Desktop)
- Development tools
- Local AI assistants
- Command-line interfaces

## HTTP with SSE Transport

HTTP with Server-Sent Events provides a web-friendly transport suitable for browser-based clients and remote servers.

### Overview
- Client sends HTTP POST requests
- Server responds with Server-Sent Events
- Supports long-running operations
- Works through firewalls and proxies

### Request Format
```http
POST /mcp/v1 HTTP/1.1
Host: example.com
Content-Type: application/json
Accept: text/event-stream

{
  "jsonrpc": "2.0",
  "id": "123",
  "method": "tools/call",
  "params": {
    "name": "search",
    "arguments": {
      "query": "example"
    }
  }
}
```

### Response Format
```http
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache

event: message
data: {"jsonrpc":"2.0","method":"notifications/progress","params":{"progress":50}}

event: message
data: {"jsonrpc":"2.0","id":"123","result":{"content":[{"type":"text","text":"Results..."}]}}

event: done
data: 

```

### Implementation Details

#### Server Implementation
```typescript
app.post('/mcp/v1', async (req, res) => {
  const message = req.body;
  
  // Set SSE headers
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive'
  });
  
  // Send progress updates
  const sendProgress = (progress) => {
    res.write(`event: message\n`);
    res.write(`data: ${JSON.stringify({
      jsonrpc: "2.0",
      method: "notifications/progress",
      params: { progress }
    })}\n\n`);
  };
  
  // Process request
  const result = await processRequest(message, sendProgress);
  
  // Send result
  res.write(`event: message\n`);
  res.write(`data: ${JSON.stringify(result)}\n\n`);
  
  // End stream
  res.write(`event: done\n`);
  res.write(`data: \n\n`);
  res.end();
});
```

#### Client Implementation
```typescript
async function sendRequest(message) {
  const response = await fetch('https://example.com/mcp/v1', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream'
    },
    body: JSON.stringify(message)
  });
  
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    
    const chunk = decoder.decode(value);
    const events = parseSSE(chunk);
    
    for (const event of events) {
      if (event.event === 'message') {
        handleMessage(JSON.parse(event.data));
      }
    }
  }
}
```

### Advantages
- Works in browsers
- Firewall-friendly
- Built-in progress support
- Standard HTTP infrastructure

### Disadvantages
- Unidirectional server push
- Connection overhead per request
- Limited by HTTP timeouts
- No request cancellation

### Use Cases
- Web applications
- Remote servers
- Cloud deployments
- API integrations

## Streamable HTTP Transport

The Streamable HTTP transport is an optimized version designed for efficiency and flexibility.

### Overview
- Uses HTTP POST for all messages
- Supports both single responses and streaming
- Efficient for batch operations
- Better timeout handling

### Request Format
```http
POST /mcp HTTP/1.1
Host: example.com
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": "123",
  "method": "resources/read",
  "params": {
    "uri": "file:///data.json"
  }
}
```

### Response Formats

#### Single Response
```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": "123",
  "result": {
    "contents": [...]
  }
}
```

#### Streaming Response
```http
HTTP/1.1 200 OK
Content-Type: text/event-stream
Transfer-Encoding: chunked

data: {"jsonrpc":"2.0","method":"notifications/start"}

data: {"jsonrpc":"2.0","method":"notifications/progress","params":{"progress":25}}

data: {"jsonrpc":"2.0","id":"123","result":{"contents":[...]}}
```

### Batch Support
```http
POST /mcp HTTP/1.1
Content-Type: application/json

[
  {"jsonrpc":"2.0","id":"1","method":"resources/list"},
  {"jsonrpc":"2.0","id":"2","method":"tools/list"},
  {"jsonrpc":"2.0","method":"notifications/log","params":{"level":"info","message":"Batch request"}}
]
```

### Implementation Details

#### Adaptive Response Handler
```typescript
app.post('/mcp', async (req, res) => {
  const message = req.body;
  
  // Determine if streaming is needed
  const needsStreaming = requiresStreaming(message);
  
  if (needsStreaming) {
    // Stream response
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Transfer-Encoding', 'chunked');
    
    const stream = processMessageStream(message);
    for await (const chunk of stream) {
      res.write(`data: ${JSON.stringify(chunk)}\n\n`);
    }
    res.end();
  } else {
    // Single response
    res.setHeader('Content-Type', 'application/json');
    const result = await processMessage(message);
    res.json(result);
  }
});
```

### Advantages
- Flexible response types
- Efficient batch processing
- Better error handling
- Reduced connection overhead

### Disadvantages
- More complex implementation
- Requires smart client logic
- Not all HTTP clients support streaming

### Use Cases
- High-performance applications
- Batch processing systems
- Large data transfers
- Real-time updates

## Transport Selection

### Decision Matrix

| Transport | Local | Remote | Browser | Streaming | Complexity |
|-----------|-------|--------|---------|-----------|------------|
| stdio | ✓ | ✗ | ✗ | ✓ | Low |
| HTTP+SSE | ✓ | ✓ | ✓ | ✓ | Medium |
| Streamable HTTP | ✓ | ✓ | ✓ | ✓ | High |

### Selection Criteria

1. **Deployment Environment**
   - Local only → stdio
   - Web/remote → HTTP variants
   - Mixed → Multiple transports

2. **Performance Requirements**
   - Low latency → stdio
   - High throughput → Streamable HTTP
   - Progress updates → HTTP+SSE

3. **Client Capabilities**
   - Simple clients → stdio
   - Web browsers → HTTP+SSE
   - Advanced clients → Streamable HTTP

## Message Framing

### stdio Framing
- Newline delimited (`\n`)
- No embedded newlines in JSON
- UTF-8 encoding required

### HTTP Framing
- Content-Length header
- Chunked transfer encoding
- SSE format for streaming

### Size Limits
- Maximum message size: 64MB
- Recommended size: <1MB
- Large data via resource URIs

## Connection Management

### Connection Lifecycle
```
1. Transport Initialization
2. Protocol Handshake (initialize)
3. Active Communication
4. Graceful Shutdown
5. Transport Cleanup
```

### Keepalive Strategies

#### stdio
```typescript
// Periodic ping
setInterval(() => {
  sendMessage({
    jsonrpc: "2.0",
    method: "ping"
  });
}, 30000);
```

#### HTTP
```typescript
// HTTP Keep-Alive headers
headers: {
  'Connection': 'keep-alive',
  'Keep-Alive': 'timeout=5, max=1000'
}
```

### Reconnection Logic
```typescript
class TransportClient {
  async connect() {
    let retries = 0;
    while (retries < this.maxRetries) {
      try {
        await this.establishConnection();
        return;
      } catch (error) {
        retries++;
        await this.exponentialBackoff(retries);
      }
    }
    throw new Error('Failed to connect after retries');
  }
  
  exponentialBackoff(attempt) {
    const delay = Math.min(1000 * Math.pow(2, attempt), 30000);
    return new Promise(resolve => setTimeout(resolve, delay));
  }
}
```

## Error Handling

### Transport-Level Errors

#### Connection Errors
```json
{
  "error": "ECONNREFUSED",
  "message": "Connection refused",
  "retry": true,
  "retryAfter": 5000
}
```

#### Timeout Errors
```json
{
  "error": "ETIMEDOUT",
  "message": "Request timeout",
  "timeout": 30000,
  "retry": true
}
```

### Error Recovery

1. **Automatic Retry**
   - Exponential backoff
   - Maximum retry limits
   - Jitter for distributed systems

2. **Circuit Breaker**
   - Fail fast after threshold
   - Periodic health checks
   - Gradual recovery

3. **Fallback Strategies**
   - Alternative transports
   - Cached responses
   - Degraded functionality

## Performance Considerations

### Optimization Techniques

1. **Message Compression**
   ```typescript
   // Enable gzip for HTTP transports
   app.use(compression({
     threshold: 1024,
     level: 6
   }));
   ```

2. **Connection Pooling**
   ```typescript
   const pool = new ConnectionPool({
     maxConnections: 10,
     idleTimeout: 60000
   });
   ```

3. **Request Batching**
   ```typescript
   const batcher = new RequestBatcher({
     maxBatchSize: 50,
     batchTimeout: 100
   });
   ```

### Benchmarks

| Transport | Latency | Throughput | CPU Usage |
|-----------|---------|------------|-----------|
| stdio | <1ms | 100MB/s | Low |
| HTTP+SSE | 10-50ms | 10MB/s | Medium |
| Streamable | 5-20ms | 50MB/s | Medium |

## Future Transports

### WebSocket
- Full duplex communication
- Lower latency than HTTP
- Better for real-time applications

### gRPC
- Binary protocol
- Schema-driven
- Built-in streaming

### WebTransport
- Next-generation web protocol
- UDP and reliable streams
- Better performance than WebSocket

### Implementation Roadmap
1. **Phase 1**: Core transports (stdio, HTTP)
2. **Phase 2**: WebSocket support
3. **Phase 3**: gRPC integration
4. **Phase 4**: Experimental transports

## Best Practices

### For Server Developers
1. Support multiple transports when possible
2. Implement proper error handling
3. Use streaming for large responses
4. Monitor transport health

### For Client Developers
1. Choose appropriate transport for use case
2. Implement reconnection logic
3. Handle transport errors gracefully
4. Support transport fallbacks

### Security Considerations
1. Use TLS for network transports
2. Validate message sizes
3. Implement rate limiting
4. Authenticate connections

## Next Steps

- **Server Development**: Building MCP servers
- **Client Development**: Creating MCP clients
- **Security**: Authentication and authorization
- **Examples**: Transport implementation examples