# Logfire Instrumentation Plan for Virtual Library MCP Server

## Executive Summary

This plan outlines the implementation of Pydantic Logfire observability for the Virtual Library MCP Server. The instrumentation provides production-grade monitoring while serving as an educational tool for understanding MCP protocol operations. This updated plan reflects the current codebase structure and provides concrete implementation guidance.

## Current State Analysis

### Existing Components
- **FastMCP Server**: Complete MCP implementation with all protocol features
- **5 Tools**: book_insights (with sampling), bulk_import, catalog_maintenance, circulation, search
- **5 Resources**: books, advanced_books, patrons, recommendations, stats
- **3 Prompts**: book_recommendations, reading_plan, review_generator
- **Sampling Module**: AI generation capability with request_ai_generation
- **Database Layer**: SQLAlchemy with repository pattern (book, author, patron, circulation)
- **Models**: Pydantic v2 models for all entities

### Missing Components
- No observability module exists yet
- No Logfire dependency in pyproject.toml
- No instrumentation code implemented

## Core Principles

1. **Zero Business Logic Modification**: Use decorators, context managers, and middleware
2. **MCP Protocol Focus**: Instrument at protocol boundaries, not implementation details
3. **Educational Clarity**: Make MCP flows visible and understandable with helpful context
4. **Simplicity First**: No PII concerns with simulated data - focus on learning
5. **Performance Target**: < 5% overhead while maintaining educational value
6. **Progressive Implementation**: Start simple, enhance iteratively

## Architecture

### Module Structure
```
virtual-library-mcp/
├── observability/                  # NEW - Logfire instrumentation
│   ├── __init__.py                # Logfire setup and configuration
│   ├── config.py                  # Configuration management
│   ├── decorators.py              # Tool, resource, prompt decorators
│   ├── middleware.py              # FastMCP middleware
│   ├── context.py                 # Database operation context managers
│   ├── metrics.py                 # Custom metrics (circulation, etc.)
│   ├── educational.py             # Educational context and hints
│   └── dashboards.py              # Dashboard query definitions
```

## Implementation Plan

### Phase 1: Foundation (Days 1-3)

#### 1.1 Dependencies and Setup

```toml
# Add to pyproject.toml
[tool.poetry.dependencies]
logfire = "^2.0.0"
```

#### 1.2 Configuration Module

```python
# observability/config.py
from pydantic import BaseModel, Field
from typing import Optional
import os

class ObservabilityConfig(BaseModel):
    """Configuration for Logfire observability."""
    
    # Connection
    token: str = Field(default_factory=lambda: os.getenv("LOGFIRE_TOKEN", ""))
    project_name: str = "virtual-library-mcp"
    environment: str = Field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    
    # Behavior
    enabled: bool = Field(default_factory=lambda: os.getenv("LOGFIRE_ENABLED", "true").lower() == "true")
    console_output: bool = Field(default_factory=lambda: os.getenv("LOGFIRE_CONSOLE", "false").lower() == "true")
    send_to_logfire: bool = Field(default_factory=lambda: os.getenv("LOGFIRE_SEND", "true").lower() == "true")
    
    # Sampling
    sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    
    # Performance
    max_span_attributes: int = 50
    max_attribute_length: int = 1000
    
    # Debug
    debug_mode: bool = Field(default_factory=lambda: os.getenv("LOGFIRE_DEBUG", "false").lower() == "true")
```

#### 1.3 Initialization

```python
# observability/__init__.py
import logfire
from typing import Optional
from .config import ObservabilityConfig

_config: Optional[ObservabilityConfig] = None

def initialize_observability(config: Optional[ObservabilityConfig] = None):
    """Initialize Logfire with configuration."""
    global _config
    _config = config or ObservabilityConfig()
    
    if not _config.enabled:
        return
    
    logfire.configure(
        token=_config.token,
        project_name=_config.project_name,
        environment=_config.environment,
        send_to_logfire=_config.send_to_logfire,
        console=_config.console_output,
        console_colors="auto",
        console_include_timestamp=True,
        console_verbose=_config.debug_mode,
    )
    
    # Optionally instrument system metrics
    if _config.environment == "production":
        logfire.instrument_system_metrics()

def get_config() -> ObservabilityConfig:
    """Get current observability configuration."""
    global _config
    if _config is None:
        _config = ObservabilityConfig()
    return _config
```

### Phase 2: MCP Protocol Instrumentation (Days 4-7)

#### 2.1 FastMCP Middleware

```python
# observability/middleware.py
import logfire
from typing import Any, Dict, Optional
from datetime import datetime
import json

class MCPInstrumentationMiddleware:
    """Middleware to trace all MCP protocol operations."""
    
    def __init__(self):
        self.start_time = datetime.now()
    
    async def __call__(self, handler, request: Dict[str, Any]) -> Any:
        """Instrument MCP request handling."""
        method = request.get("method", "unknown")
        request_id = request.get("id")
        params = request.get("params", {})
        
        # Determine operation type
        operation_type = self._get_operation_type(method)
        
        with logfire.span(
            f"mcp.{operation_type}.{method}",
            _span_name=f"MCP {method}",
            mcp_method=method,
            mcp_request_id=request_id,
            mcp_operation_type=operation_type,
            mcp_jsonrpc_version=request.get("jsonrpc", "2.0"),
        ) as span:
            # Add method-specific attributes
            self._add_method_attributes(span, method, params)
            
            try:
                # Execute the actual handler
                result = await handler(request)
                
                # Track success
                span.set_attribute("mcp.status", "success")
                
                # Add result metrics
                self._add_result_metrics(span, method, result)
                
                return result
                
            except Exception as e:
                # Track error
                span.set_attribute("mcp.status", "error")
                span.set_attribute("error.type", type(e).__name__)
                span.set_attribute("error.message", str(e))
                span.set_attribute("error.mcp_code", getattr(e, "code", -1))
                raise
    
    def _get_operation_type(self, method: str) -> str:
        """Categorize MCP method into operation type."""
        if method.startswith("resources/"):
            return "resource"
        elif method.startswith("tools/"):
            return "tool"
        elif method.startswith("prompts/"):
            return "prompt"
        elif method.startswith("completion/"):
            return "sampling"
        else:
            return "system"
    
    def _add_method_attributes(self, span, method: str, params: Dict):
        """Add method-specific attributes to span."""
        if method == "tools/call":
            span.set_attribute("tool.name", params.get("name", "unknown"))
        elif method == "resources/read":
            span.set_attribute("resource.uri", params.get("uri", "unknown"))
        elif method == "prompts/get":
            span.set_attribute("prompt.name", params.get("name", "unknown"))
    
    def _add_result_metrics(self, span, method: str, result: Any):
        """Add result-based metrics to span."""
        if method == "resources/list" and isinstance(result, dict):
            resources = result.get("resources", [])
            span.set_attribute("result.resource_count", len(resources))
        elif method == "tools/list" and isinstance(result, dict):
            tools = result.get("tools", [])
            span.set_attribute("result.tool_count", len(tools))
```

#### 2.2 Integration with Server

```python
# server.py updates
from observability import initialize_observability
from observability.middleware import MCPInstrumentationMiddleware

# Initialize observability
initialize_observability()

# Create FastMCP server with middleware
mcp = FastMCP(
    "Virtual Library MCP Server",
    version="1.0.0"
)

# Add instrumentation middleware
mcp.add_middleware(MCPInstrumentationMiddleware())
```

### Phase 3: Component Instrumentation (Days 8-14)

#### 3.1 Tool Decorators

```python
# observability/decorators.py
import functools
import logfire
from typing import Any, Callable
from datetime import datetime

def trace_tool(tool_name: str):
    """Decorator to trace MCP tool execution."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract context and arguments
            context = args[0] if args else kwargs.get("context")
            
            # Start span
            with logfire.span(
                f"tool.execution.{tool_name}",
                tool_name=tool_name,
                tool_category=_categorize_tool(tool_name),
            ) as span:
                start_time = datetime.now()
                
                # Add input attributes (all data - educational app)
                _add_attributes(span, "input", kwargs)
                
                try:
                    # Execute tool
                    result = await func(*args, **kwargs)
                    
                    # Track success
                    span.set_attribute("tool.success", True)
                    span.set_attribute("tool.duration_ms", 
                                      (datetime.now() - start_time).total_seconds() * 1000)
                    
                    # Add result metrics
                    _add_tool_result_metrics(span, tool_name, result)
                    
                    return result
                    
                except Exception as e:
                    span.set_attribute("tool.success", False)
                    span.set_attribute("tool.error", str(e))
                    raise
        
        return wrapper
    return decorator

def _categorize_tool(tool_name: str) -> str:
    """Categorize tools for better organization."""
    if "checkout" in tool_name or "return" in tool_name:
        return "circulation"
    elif "import" in tool_name or "maintenance" in tool_name:
        return "catalog"
    elif "search" in tool_name:
        return "discovery"
    elif "insight" in tool_name:
        return "ai"
    return "general"

def _add_attributes(span, prefix: str, data: dict):
    """Add attributes to span (educational app - no PII concerns)."""
    for key, value in data.items():
        if isinstance(value, (str, int, float, bool)):
            span.set_attribute(f"{prefix}.{key}", value)

def _add_tool_result_metrics(span, tool_name: str, result: Any):
    """Add tool-specific result metrics."""
    if tool_name == "bulk_import" and hasattr(result, "imported_count"):
        span.set_attribute("result.imported_count", result.imported_count)
    elif tool_name == "search_catalog" and hasattr(result, "__len__"):
        span.set_attribute("result.match_count", len(result))
```

#### 3.2 Resource Decorators

```python
def trace_resource(resource_type: str):
    """Lightweight decorator for resource operations."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(uri: str, *args, **kwargs):
            with logfire.span(
                f"resource.read.{resource_type}",
                resource_uri=uri,
                resource_type=resource_type,
            ) as span:
                result = await func(uri, *args, **kwargs)
                
                # Add metrics
                if hasattr(result, "__len__"):
                    span.set_attribute("result.item_count", len(result))
                elif hasattr(result, "dict"):
                    span.set_attribute("result.type", type(result).__name__)
                
                return result
        return wrapper
    return decorator
```

#### 3.3 Database Context Managers

```python
# observability/context.py
from contextlib import contextmanager
import logfire
from typing import Optional

@contextmanager
def trace_repository_operation(
    repository: str,
    operation: str,
    table: Optional[str] = None
):
    """Context manager for tracing repository operations."""
    with logfire.span(
        f"db.{repository}.{operation}",
        db_repository=repository,
        db_operation=operation,
        db_table=table or repository,
        db_system="sqlite",
    ) as span:
        try:
            yield span
        except Exception as e:
            span.set_attribute("db.error", str(e))
            raise

# Usage in repositories
class BookRepository:
    def get_by_isbn(self, isbn: str) -> Optional[Book]:
        with trace_repository_operation("book", "get_by_isbn"):
            return self.session.query(BookDB).filter_by(isbn=isbn).first()
```

### Phase 4: Advanced Features (Days 15-21)

#### 4.1 Custom Metrics

```python
# observability/metrics.py
import logfire
from typing import Dict

# MCP Protocol Metrics
mcp_request_counter = logfire.metric_counter(
    "mcp.requests.total",
    description="Total MCP requests by method"
)

mcp_request_duration = logfire.metric_histogram(
    "mcp.request.duration_ms",
    unit="milliseconds",
    description="MCP request duration by method"
)

# Library Business Metrics
books_circulation = logfire.metric_counter(
    "library.books.circulation",
    description="Book circulation events (checkout/return)"
)

patron_activity = logfire.metric_gauge(
    "library.patrons.active",
    description="Number of patrons with active checkouts"
)

# AI/Sampling Metrics
ai_generation_requests = logfire.metric_counter(
    "ai.generation.requests",
    description="AI generation requests by type"
)

ai_generation_tokens = logfire.metric_histogram(
    "ai.generation.tokens",
    unit="tokens",
    description="Token usage for AI generation"
)

# Bulk Operation Metrics
bulk_import_progress = logfire.metric_gauge(
    "bulk.import.progress",
    description="Current bulk import progress percentage"
)

def record_circulation_event(event_type: str, book_genre: str):
    """Record a circulation event."""
    books_circulation.add(1, {
        "event_type": event_type,
        "genre": book_genre
    })

def update_import_progress(current: int, total: int, operation_id: str):
    """Update bulk import progress."""
    if total > 0:
        progress = (current / total) * 100
        bulk_import_progress.set(progress, {
            "operation_id": operation_id
        })
```

#### 4.2 Sampling Integration

```python
# Updates to sampling.py
import logfire
from observability.metrics import ai_generation_requests, ai_generation_tokens

async def request_ai_generation(
    context: Context,
    prompt: str,
    system_prompt: str | None = None,
    max_tokens: int = 500,
    temperature: float = 0.7,
    intelligence_priority: float = 0.7,
    speed_priority: float = 0.5,
) -> str | None:
    """Request AI-generated content with full instrumentation."""
    
    with logfire.span(
        "ai.sampling.request",
        ai_max_tokens=max_tokens,
        ai_temperature=temperature,
        ai_intelligence_priority=intelligence_priority,
        ai_speed_priority=speed_priority,
    ) as span:
        # Check capability
        if not context.request_context.session.client_capabilities.sampling:
            span.set_attribute("ai.fallback", "no_capability")
            return None
        
        try:
            # Record request metric
            ai_generation_requests.add(1, {"status": "requested"})
            
            # Build and send request
            messages = [
                SamplingMessage(
                    role="user",
                    content=TextContent(type="text", text=prompt)
                )
            ]
            
            # ... rest of implementation ...
            
            # Track token usage
            if result:
                estimated_tokens = len(result.split()) * 1.3  # Rough estimate
                ai_generation_tokens.add(estimated_tokens)
                span.set_attribute("ai.estimated_tokens", estimated_tokens)
                span.set_attribute("ai.response_length", len(result))
            
            return result
            
        except Exception as e:
            span.set_attribute("ai.error", str(e))
            ai_generation_requests.add(1, {"status": "failed"})
            return None
```

#### 4.3 Educational Data Attributes

```python
# observability/educational.py
from typing import Any, Dict

def add_educational_context(span, operation: str):
    """Add educational context to spans for learning."""
    
    # Add context about what this operation demonstrates
    educational_contexts = {
        "checkout_book": "Demonstrates tool execution with database transactions",
        "bulk_import": "Shows long-running operations with progress tracking",
        "book_insights": "Illustrates AI sampling integration",
        "search_catalog": "Examples full-text search patterns",
        "get_recommendations": "Shows resource caching strategies"
    }
    
    if operation in educational_contexts:
        span.set_attribute("educational.concept", educational_contexts[operation])
    
    # Add MCP protocol education
    span.set_attribute("mcp.protocol_version", "1.0")
    span.set_attribute("mcp.transport", "stdio")

def add_performance_hint(span, duration_ms: float, operation_type: str):
    """Add performance hints for educational purposes."""
    
    thresholds = {
        "resource": 100,
        "tool": 500,
        "sampling": 2000,
        "database": 50
    }
    
    threshold = thresholds.get(operation_type, 200)
    
    if duration_ms > threshold * 2:
        span.set_attribute("performance.hint", f"Consider optimizing - {duration_ms}ms exceeds target {threshold}ms")
    elif duration_ms < threshold / 2:
        span.set_attribute("performance.hint", f"Excellent performance - {duration_ms}ms well under target {threshold}ms")
```

### Phase 5: Production Configuration (Days 22-28)

#### 5.1 Environment-Specific Settings

```python
# config.py additions
class ProductionConfig(ObservabilityConfig):
    """Production-specific configuration."""
    sample_rate: float = 0.1  # Sample 10% of requests
    console_output: bool = False
    send_to_logfire: bool = True
    max_span_attributes: int = 30
    
class DevelopmentConfig(ObservabilityConfig):
    """Development-specific configuration."""
    sample_rate: float = 1.0  # Sample everything
    console_output: bool = True
    send_to_logfire: bool = False
    debug_mode: bool = True

def get_environment_config() -> ObservabilityConfig:
    """Get configuration based on environment."""
    env = os.getenv("ENVIRONMENT", "development")
    
    if env == "production":
        return ProductionConfig()
    elif env == "development":
        return DevelopmentConfig()
    else:
        return ObservabilityConfig()
```

#### 5.2 Performance Optimization

```python
# observability/performance.py
import random
from typing import Optional
from .config import get_config

class SamplingDecision:
    """Make sampling decisions for performance."""
    
    @staticmethod
    def should_sample(operation: str) -> bool:
        """Determine if operation should be sampled."""
        config = get_config()
        
        # Always sample errors
        if "error" in operation:
            return True
        
        # Apply base sample rate
        if random.random() > config.sample_rate:
            return False
        
        # Additional rules for specific operations
        if operation.startswith("resource.read"):
            # Sample fewer resource reads
            return random.random() < 0.05
        elif operation.startswith("tool."):
            # Sample more tool operations
            return random.random() < 0.5
        
        return True
```

## Testing Strategy

### Unit Tests

```python
# tests/observability/test_decorators.py
import pytest
from unittest.mock import Mock, patch
from observability.decorators import trace_tool

@pytest.mark.asyncio
async def test_trace_tool_success():
    """Test tool decorator with successful execution."""
    with patch("observability.decorators.logfire") as mock_logfire:
        @trace_tool("test_tool")
        async def dummy_tool(context, **kwargs):
            return {"success": True}
        
        result = await dummy_tool(Mock(), test_param="value")
        
        assert result == {"success": True}
        mock_logfire.span.assert_called_once()
        
        # Verify span attributes
        span_call = mock_logfire.span.call_args
        assert span_call[0][0] == "tool.execution.test_tool"
```

### Integration Tests

```python
# tests/observability/test_integration.py
from logfire.testing import CaptureLogfire

def test_mcp_request_creates_spans(test_client):
    """Test that MCP requests create appropriate spans."""
    with CaptureLogfire() as capfire:
        # Make MCP request
        response = test_client.post("/mcp", json={
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 1
        })
        
        # Check spans
        spans = capfire.exporter.exported_spans_as_dict()
        mcp_spans = [s for s in spans if s["name"].startswith("MCP")]
        
        assert len(mcp_spans) > 0
        assert mcp_spans[0]["attributes"]["mcp.method"] == "tools/list"
```

## Dashboard Queries

### MCP Protocol Overview
```sql
-- Request rate by method (last hour)
SELECT 
    DATE_TRUNC('minute', timestamp) as minute,
    attributes->>'mcp_method' as method,
    COUNT(*) as requests
FROM spans
WHERE 
    name LIKE 'MCP %'
    AND timestamp > NOW() - INTERVAL '1 hour'
GROUP BY minute, method
ORDER BY minute DESC;

-- Slowest operations (P95)
SELECT 
    attributes->>'mcp_method' as method,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) as p95_ms,
    COUNT(*) as count
FROM spans
WHERE name LIKE 'MCP %'
GROUP BY method
ORDER BY p95_ms DESC;
```

### Library Operations
```sql
-- Book circulation trends
SELECT 
    DATE_TRUNC('hour', timestamp) as hour,
    attributes->>'event_type' as event,
    attributes->>'genre' as genre,
    COUNT(*) as count
FROM metrics
WHERE name = 'library.books.circulation'
GROUP BY hour, event, genre
ORDER BY hour DESC;

-- Most active patrons
SELECT 
    attributes->>'patron_id' as patron,
    COUNT(*) as actions
FROM spans
WHERE name LIKE 'tool.execution.%'
    AND attributes->>'patron_id' IS NOT NULL
GROUP BY patron
ORDER BY actions DESC
LIMIT 10;
```

## Monitoring Alerts

```yaml
# alerts.yaml
alerts:
  - name: high_error_rate
    query: |
      SELECT COUNT(*) as errors
      FROM spans
      WHERE attributes->>'mcp.status' = 'error'
        AND timestamp > NOW() - INTERVAL '5 minutes'
    threshold: 10
    action: notify_oncall
    
  - name: slow_response_time
    query: |
      SELECT AVG(duration_ms) as avg_duration
      FROM spans
      WHERE name LIKE 'MCP %'
        AND timestamp > NOW() - INTERVAL '5 minutes'
    threshold: 1000  # 1 second
    action: notify_team
    
  - name: bulk_import_stuck
    query: |
      SELECT MAX(timestamp) as last_update
      FROM metrics
      WHERE name = 'bulk.import.progress'
    threshold: 300  # 5 minutes without update
    action: investigate
```

## Success Metrics

### Technical Metrics
- ✅ < 5% performance overhead
- ✅ Zero modification to business logic
- ✅ 100% MCP protocol coverage
- ✅ Clean, educational telemetry data

### Educational Metrics
- ✅ Clear visualization of MCP request flows
- ✅ Understanding of resource vs tool performance
- ✅ AI sampling patterns visible
- ✅ Database query analysis available

### Operational Metrics
- ✅ Early error detection (< 1 minute)
- ✅ Performance regression alerts
- ✅ Usage pattern insights
- ✅ Cost-effective telemetry

## Implementation Checklist

### Week 1
- [ ] Add logfire to pyproject.toml
- [ ] Create observability/ module structure
- [ ] Implement configuration management
- [ ] Add FastMCP middleware
- [ ] Test basic request tracing

### Week 2
- [ ] Implement tool decorators
- [ ] Add resource decorators
- [ ] Create database context managers
- [ ] Integrate with repositories
- [ ] Add prompt instrumentation

### Week 3
- [ ] Define custom metrics
- [ ] Instrument sampling module
- [ ] Add bulk operation tracking
- [ ] Add educational context attributes
- [ ] Create test fixtures

### Week 4
- [ ] Configure production settings
- [ ] Optimize sampling rates
- [ ] Create Logfire dashboards
- [ ] Set up alerts
- [ ] Write documentation

## Conclusion

This updated instrumentation plan provides comprehensive observability for the Virtual Library MCP Server while maintaining clean, educational code. The implementation is tailored to the actual codebase structure and provides both operational insights and educational value for understanding MCP protocols.