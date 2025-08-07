# Observability Overview - Virtual Library MCP Server

## Table of Contents
- [Introduction](#introduction)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Instrumentation Points](#instrumentation-points)
- [Metrics](#metrics)
- [Environment Variables](#environment-variables)
- [Usage Guide](#usage-guide)

## Introduction

The Virtual Library MCP Server implements comprehensive observability using **Logfire** by Pydantic. The observability layer provides distributed tracing, metrics collection, and performance monitoring across all MCP protocol operations and database interactions.

### Key Features
- **Graceful Degradation**: Works without Logfire installed (mock implementation)
- **Configurable**: Environment-based configuration for different deployment scenarios
- **Protocol-Aware**: Custom instrumentation for MCP-specific operations
- **Database Tracing**: Automatic SQLite query instrumentation
- **AI Sampling Metrics**: Tracks LLM generation requests and token usage

## Architecture

```
┌─────────────────────────────────────────────┐
│           MCP Client Request                 │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│      MCPInstrumentationMiddleware            │
│  (observability/middleware.py)               │
│  - Traces all MCP protocol operations        │
│  - Categorizes by operation type             │
│  - Records request/response metrics          │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│         FastMCP Server Core                  │
│  (server.py)                                 │
│  - Initializes observability                 │
│  - Registers middleware                      │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│    Resources / Tools / Prompts               │
│  - Business logic execution                  │
│  - Database operations                       │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│         Database Layer                       │
│  - SQLite3 auto-instrumentation              │
│  - Query tracing via logfire                 │
└─────────────────────────────────────────────┘
```

## Configuration

### Main Configuration Module
**Location**: `observability/config.py`

Defines three configuration profiles:
1. **Base ObservabilityConfig**: Default settings with environment variable overrides
2. **ProductionConfig**: Optimized for production (no console output, full sampling)
3. **DevelopmentConfig**: Enhanced debugging (console output, debug mode enabled)

### Key Configuration Options

| Setting | Description | Default |
|---------|-------------|---------|
| `enabled` | Enable/disable observability | `true` |
| `token` | Logfire authentication token | `""` (from env) |
| `project_name` | Project identifier | `"virtual-library-mcp"` |
| `environment` | Deployment environment | `"development"` |
| `console_output` | Show traces in console | `false` (true in dev) |
| `send_to_logfire` | Send data to Logfire cloud | `true` |
| `sample_rate` | Trace sampling rate (0.0-1.0) | `1.0` |
| `max_span_attributes` | Max attributes per span | `50` (30 in prod) |
| `debug_mode` | Enable debug logging | `false` (true in dev) |

## Instrumentation Points

### 1. Initialization (`observability/__init__.py`)
- **Function**: `initialize_observability()`
- **Features**:
  - Graceful handling when Logfire not installed
  - Token validation and fallback to console-only mode
  - Automatic SQLite3 instrumentation
  - System metrics collection (production only)

### 2. MCP Protocol Middleware (`observability/middleware.py`)
- **Class**: `MCPInstrumentationMiddleware`
- **Traced Operations**:
  - **Resources**: `resources/list`, `resources/read`
  - **Tools**: `tools/list`, `tools/call`
  - **Prompts**: `prompts/list`, `prompts/get`
  - **Sampling**: `completion/complete`
- **Attributes Captured**:
  - Method name and operation type
  - Request ID and JSON-RPC version
  - Method-specific details (tool names, resource URIs, prompt names)
  - Success/error status
  - Error details (type, message, code)

### 3. Database Operations (`database/session.py`)
- **Auto-Instrumentation**: `logfire.instrument_sqlite3()`
- **Features**:
  - All SQL queries automatically traced
  - Query timing and parameters captured
  - Connection pool metrics
  - Transaction boundaries

### 4. AI Sampling (`sampling.py`)
- **Function**: `request_ai_generation()`
- **Traced Attributes**:
  - Max tokens, temperature, priorities
  - Fallback reasons (no capability, error)
  - Token usage metrics
  - Request status tracking

### 5. Repository Operations (`observability/context.py`)
- **Context Manager**: `trace_repository_operation()`
- **Attributes**:
  - Repository name
  - Operation type
  - Table name
  - Database system
  - Error details

## Metrics

### Custom Metrics (`observability/metrics.py`)

#### MCP Protocol Metrics
- `mcp.requests.total`: Total requests by method (Counter)
- `mcp.request.duration_ms`: Request duration by method (Histogram)

#### Library Business Metrics
- `library.books.circulation`: Book checkout/return events (Counter)
- `library.patrons.active`: Active patrons with checkouts (Gauge)

#### AI/Sampling Metrics
- `ai.generation.requests`: AI generation requests by type (Counter)
- `ai.generation.tokens`: Token usage distribution (Histogram)

#### Bulk Operation Metrics
- `bulk.import.progress`: Import progress percentage (Gauge)

### Helper Functions
- `record_circulation_event(event_type, book_genre)`: Track circulation events
- `update_import_progress(current, total, operation_id)`: Track bulk imports

## Environment Variables

### Core Settings
| Variable | Description | Example |
|----------|-------------|---------|
| `LOGFIRE_ENABLED` | Enable/disable observability | `true` |
| `LOGFIRE_TOKEN` | Authentication token | `your-token-here` |
| `LOGFIRE_SEND` | Send to Logfire cloud | `true` |
| `LOGFIRE_CONSOLE` | Console output | `false` |
| `LOGFIRE_DEBUG` | Debug mode | `false` |
| `ENVIRONMENT` | Deployment environment | `development` |

### Behavior Control
- `LOGFIRE_IGNORE_NO_CONFIG=1`: Suppress warning when token missing (tests)
- Environment determines config profile selection

## Usage Guide

### Development Setup
1. Copy `.env.sample` to `.env`
2. Set `LOGFIRE_CONSOLE=true` for local debugging
3. Optionally add `LOGFIRE_TOKEN` for cloud dashboards

### Production Deployment
1. Set `ENVIRONMENT=production`
2. Configure `LOGFIRE_TOKEN` (required)
3. Ensure `LOGFIRE_SEND=true`
4. Set `LOGFIRE_CONSOLE=false`

### Testing Without Logfire
The system gracefully degrades when Logfire is not installed:
- Mock implementations prevent crashes
- All operations continue normally
- No telemetry data is collected

### Viewing Telemetry

#### Console Output (Development)
When `LOGFIRE_CONSOLE=true`, traces appear in stderr:
```
[span] mcp.resource.resources/read {resource.uri: library://books/9780134685991}
  [span] db.books.get_by_id {db_repository: books, db_operation: get_by_id}
```

#### Logfire Dashboard (All Environments)
With valid token and `LOGFIRE_SEND=true`:
1. Navigate to https://logfire.pydantic.dev
2. Select "virtual-library-mcp" project
3. View traces, metrics, and dashboards

### Common Patterns

#### Tracing Custom Operations
```python
from observability import logfire

with logfire.span("custom.operation", custom_attr="value") as span:
    # Your operation
    span.set_attribute("result", "success")
```

#### Recording Metrics
```python
from observability.metrics import books_circulation

books_circulation.add(1, {"event_type": "checkout", "genre": "fiction"})
```

## Implementation Notes

### Design Decisions
1. **Middleware over Decorators**: Centralized instrumentation at protocol boundary
2. **Graceful Degradation**: Mock implementation when Logfire unavailable
3. **Environment-Based Config**: Different profiles for dev/prod
4. **Auto-Instrumentation**: SQLite3 queries traced automatically

### Performance Considerations
- Sampling rate configurable (default 100% in dev, adjustable in prod)
- Attribute limits prevent memory bloat
- Console output disabled in production
- System metrics only in production

### Security
- Token never logged or exposed
- Sensitive data not included in spans
- Error messages sanitized

## Future Enhancements
- Custom dashboards for library metrics
- Alert rules for anomalies
- Distributed tracing across services
- Performance profiling integration
- Custom sampling strategies