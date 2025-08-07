# Logfire Telemetry User Guide

A practical guide for viewing and understanding telemetry data from the Virtual Library MCP Server using Pydantic Logfire.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Understanding the Dashboards](#understanding-the-dashboards)
3. [Tracing MCP Requests](#tracing-mcp-requests)
4. [Analyzing Performance](#analyzing-performance)
5. [Monitoring Errors](#monitoring-errors)
6. [Business Metrics](#business-metrics)
7. [Development Workflow](#development-workflow)
8. [Common Queries](#common-queries)
9. [Best Practices](#best-practices)

## Getting Started

### 1. Create a Logfire Account

1. Visit [pydantic.dev/logfire](https://pydantic.dev/logfire)
2. Sign up for a free account
3. Create a new project named "virtual-library-mcp"
4. Note your project URL (e.g., `https://logfire.pydantic.dev/your-org/virtual-library-mcp`)

### 2. Obtain API Token

```bash
# In your Logfire project dashboard:
1. Click "Settings" → "API Keys"
2. Create a new Write token
3. Copy the token (starts with "lgf_")
```

### 3. Configure Environment

```bash
# .env file in virtual-library-mcp/
LOGFIRE_TOKEN=lgf_your_token_here
LOGFIRE_ENABLED=true
LOGFIRE_SEND=true
LOGFIRE_CONSOLE=false
ENVIRONMENT=development

# For local development with console output:
LOGFIRE_CONSOLE=true
LOGFIRE_SEND=false
```

### 4. Verify Connection

```bash
# Start the server
just dev

# Check Logfire dashboard for incoming data
# You should see "virtual-library-mcp" appear in your projects
```

## Understanding the Dashboards

### Main Dashboard Overview

When you open your Logfire project, you'll see several pre-configured views:

```
┌─────────────────────────────────────────┐
│         MCP Protocol Overview           │
├─────────────┬───────────────────────────┤
│  Requests   │  Response Times    │ Errors│
│  by Method  │  (P50/P95/P99)    │ Rate  │
└─────────────┴───────────────────────────┘
```

### Key Metrics Explained

#### Request Rate
- **What it shows**: Number of MCP requests per minute
- **Why it matters**: Indicates server load and usage patterns
- **Normal range**: 10-100 requests/minute for development

#### Response Time Percentiles
- **P50 (Median)**: Half of requests are faster than this
- **P95**: 95% of requests are faster than this
- **P99**: 99% of requests are faster than this
- **Target values**:
  - Resources: < 100ms (P95)
  - Tools: < 500ms (P95)
  - AI Sampling: < 2000ms (P95)

#### Error Rate
- **What it shows**: Percentage of failed requests
- **Why it matters**: Indicates system health
- **Target**: < 1% for production

## Tracing MCP Requests

### Understanding Trace View

Each MCP request creates a trace with nested spans:

```
MCP tools/call [1234ms]
├── tool.execution.checkout_book [1200ms]
│   ├── db.circulation.check_availability [50ms]
│   ├── db.circulation.create_checkout [100ms]
│   └── db.patron.update_history [50ms]
└── response.formatting [34ms]
```

### How to Find a Specific Request

1. **By Request ID**:
   ```sql
   SELECT * FROM spans 
   WHERE attributes->>'mcp_request_id' = 'your-request-id'
   ORDER BY start_time;
   ```

2. **By Time Range**:
   - Use the time picker in the top-right
   - Select "Last 15 minutes" or custom range
   - Filter by `name LIKE 'MCP %'`

3. **By Method**:
   - Click "Filters" → "Add Filter"
   - Select `attributes.mcp_method`
   - Enter method name (e.g., "tools/call")

### Reading a Trace

**Example: Book Checkout Trace**

```yaml
Trace ID: abc123def456
Duration: 523ms
Status: Success

Spans:
  - Name: MCP tools/call
    Duration: 523ms
    Attributes:
      mcp_method: tools/call
      tool.name: checkout_book
      
  - Name: tool.execution.checkout_book
    Duration: 489ms
    Attributes:
      input.isbn: 9780134110362
      input.patron_id: patron_001
      tool.success: true
      
  - Name: db.book.get_by_isbn
    Duration: 45ms
    Attributes:
      db.operation: query
      db.table: books
      result.found: true
```

**What to Look For**:
- 🟢 Green spans = successful operations
- 🔴 Red spans = errors occurred
- 🟡 Yellow spans = warnings or slow operations
- Long bars = performance bottlenecks

## Analyzing Performance

### Performance Dashboard

Navigate to "Dashboards" → "Performance Analysis"

#### Slow Query Identification

```sql
-- Find slowest database operations
SELECT 
    name,
    attributes->>'db_operation' as operation,
    attributes->>'db_table' as table,
    duration_ms,
    timestamp
FROM spans
WHERE name LIKE 'db.%'
  AND duration_ms > 100
ORDER BY duration_ms DESC
LIMIT 20;
```

#### Tool Execution Profiling

```sql
-- Analyze tool performance
SELECT 
    attributes->>'tool_name' as tool,
    COUNT(*) as calls,
    AVG(duration_ms) as avg_ms,
    MAX(duration_ms) as max_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) as p95_ms
FROM spans
WHERE name LIKE 'tool.execution.%'
GROUP BY tool
ORDER BY p95_ms DESC;
```

### Identifying Bottlenecks

1. **Go to Trace View**
2. **Sort by Duration (descending)**
3. **Look for patterns**:
   - Repeated slow queries → Add index
   - Sequential operations → Parallelize
   - N+1 queries → Batch fetch

### Performance Over Time

```sql
-- Track performance trends
SELECT 
    DATE_TRUNC('hour', timestamp) as hour,
    attributes->>'mcp_method' as method,
    AVG(duration_ms) as avg_duration,
    COUNT(*) as request_count
FROM spans
WHERE name LIKE 'MCP %'
GROUP BY hour, method
ORDER BY hour DESC;
```

## Monitoring Errors

### Error Dashboard

Navigate to "Dashboards" → "Error Tracking"

#### Error Overview

```sql
-- Error summary by type
SELECT 
    attributes->>'error.type' as error_type,
    attributes->>'mcp_method' as method,
    COUNT(*) as count,
    MAX(timestamp) as last_seen
FROM spans
WHERE attributes->>'mcp.status' = 'error'
  AND timestamp > NOW() - INTERVAL '24 hours'
GROUP BY error_type, method
ORDER BY count DESC;
```

#### Error Details

Click on any error span to see:
- Full stack trace
- Request parameters
- User context
- Related spans

#### Common Error Patterns

1. **Book Not Available**:
   ```yaml
   error.type: BookNotAvailableError
   mcp_method: tools/call
   tool.name: checkout_book
   ```

2. **Invalid ISBN**:
   ```yaml
   error.type: ValidationError
   mcp_method: resources/read
   resource.uri: /books/invalid-isbn
   ```

3. **Sampling Failure**:
   ```yaml
   error.type: SamplingError
   ai.fallback: user_rejected
   ```

### Setting Up Error Alerts

1. Go to "Alerts" → "Create Alert"
2. Configure:
   ```yaml
   Name: High Error Rate
   Query: |
     SELECT COUNT(*) as errors
     FROM spans
     WHERE attributes->>'mcp.status' = 'error'
       AND timestamp > NOW() - INTERVAL '5 minutes'
   Threshold: > 10
   Action: Send to Slack/Email
   ```

## Business Metrics

### Library Operations Dashboard

#### Book Circulation

```sql
-- Daily circulation statistics
SELECT 
    DATE(timestamp) as date,
    attributes->>'event_type' as event,
    COUNT(*) as count
FROM metrics
WHERE name = 'library.books.circulation'
GROUP BY date, event
ORDER BY date DESC;
```

**Visualization**: Line chart showing checkouts vs returns

#### Popular Books

```sql
-- Most checked out books
SELECT 
    attributes->>'isbn' as isbn,
    attributes->>'title' as title,
    COUNT(*) as checkouts
FROM spans
WHERE name = 'tool.execution.checkout_book'
  AND attributes->>'tool.success' = 'true'
GROUP BY isbn, title
ORDER BY checkouts DESC
LIMIT 10;
```

#### Patron Activity

```sql
-- Active patrons by day
SELECT 
    DATE(timestamp) as date,
    COUNT(DISTINCT attributes->>'patron_id') as active_patrons
FROM spans
WHERE name LIKE 'tool.execution.%'
  AND attributes->>'patron_id' IS NOT NULL
GROUP BY date
ORDER BY date DESC;
```

### AI/Sampling Metrics

#### Sampling Success Rate

```sql
-- AI generation success rate
SELECT 
    DATE(timestamp) as date,
    SUM(CASE WHEN attributes->>'ai.fallback' IS NULL THEN 1 ELSE 0 END) as successes,
    COUNT(*) as total,
    ROUND(100.0 * SUM(CASE WHEN attributes->>'ai.fallback' IS NULL THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM spans
WHERE name = 'ai.sampling.request'
GROUP BY date
ORDER BY date DESC;
```

#### Token Usage

```sql
-- Estimated token usage by day
SELECT 
    DATE(timestamp) as date,
    SUM(CAST(attributes->>'ai.estimated_tokens' AS INTEGER)) as total_tokens,
    AVG(CAST(attributes->>'ai.estimated_tokens' AS INTEGER)) as avg_tokens
FROM spans
WHERE name = 'ai.sampling.request'
  AND attributes->>'ai.estimated_tokens' IS NOT NULL
GROUP BY date;
```

## Development Workflow

### Local Development Setup

```python
# config.py for local development
class LocalConfig:
    LOGFIRE_ENABLED = True
    LOGFIRE_CONSOLE = True      # See traces in terminal
    LOGFIRE_SEND = False        # Don't send to cloud
    LOGFIRE_DEBUG = True        # Verbose output
```

### Console Output Format

```
[2024-08-07 10:23:45] 🟢 MCP resources/list [45ms]
  └── 📚 resource.read.books [12ms] (10 items)
  
[2024-08-07 10:23:46] 🟢 MCP tools/call [523ms]
  └── 🔧 tool.execution.checkout_book [489ms]
      ├── 💾 db.book.get_by_isbn [45ms]
      ├── 💾 db.patron.verify [23ms]
      └── 💾 db.circulation.create [89ms]
```

### Testing with Captured Spans

```python
# In tests
from logfire.testing import CaptureLogfire

def test_checkout_creates_spans():
    with CaptureLogfire() as capfire:
        # Execute checkout
        result = await checkout_book(isbn="123", patron_id="p1")
        
        # Verify spans
        spans = capfire.exporter.exported_spans_as_dict()
        assert any(s["name"] == "tool.execution.checkout_book" for s in spans)
        
        # Check attributes
        checkout_span = next(s for s in spans if "checkout" in s["name"])
        assert checkout_span["attributes"]["tool.success"] == True
```

## Common Queries

### Finding Specific Operations

#### All Resource Reads Today
```sql
SELECT * FROM spans
WHERE name LIKE 'resource.read.%'
  AND DATE(timestamp) = CURRENT_DATE
ORDER BY timestamp DESC;
```

#### Failed Tool Executions
```sql
SELECT * FROM spans
WHERE name LIKE 'tool.execution.%'
  AND attributes->>'tool.success' = 'false'
ORDER BY timestamp DESC;
```

#### Sampling Requests with Fallback
```sql
SELECT * FROM spans
WHERE name = 'ai.sampling.request'
  AND attributes->>'ai.fallback' IS NOT NULL;
```

### Performance Analysis

#### Average Response Time by Hour
```sql
SELECT 
    DATE_TRUNC('hour', timestamp) as hour,
    AVG(duration_ms) as avg_ms
FROM spans
WHERE name LIKE 'MCP %'
GROUP BY hour
ORDER BY hour;
```

#### Database Query Performance
```sql
SELECT 
    attributes->>'db_table' as table,
    attributes->>'db_operation' as operation,
    COUNT(*) as count,
    AVG(duration_ms) as avg_ms
FROM spans
WHERE name LIKE 'db.%'
GROUP BY table, operation
ORDER BY avg_ms DESC;
```

### Usage Patterns

#### Peak Usage Hours
```sql
SELECT 
    EXTRACT(HOUR FROM timestamp) as hour,
    COUNT(*) as requests
FROM spans
WHERE name LIKE 'MCP %'
GROUP BY hour
ORDER BY hour;
```

#### Most Used Features
```sql
SELECT 
    CASE 
        WHEN name LIKE '%resource%' THEN 'Resources'
        WHEN name LIKE '%tool%' THEN 'Tools'
        WHEN name LIKE '%prompt%' THEN 'Prompts'
        WHEN name LIKE '%sampling%' THEN 'AI Sampling'
        ELSE 'Other'
    END as feature,
    COUNT(*) as usage_count
FROM spans
GROUP BY feature
ORDER BY usage_count DESC;
```

## Best Practices

### 1. Use Filters Effectively

- Start broad, then narrow down
- Save frequently used filters
- Use time ranges to reduce data volume

### 2. Create Custom Dashboards

```yaml
My Dashboard:
  - Widget 1: Request rate (line chart)
  - Widget 2: Error count (number)
  - Widget 3: P95 latency (gauge)
  - Widget 4: Recent errors (table)
```

### 3. Set Up Meaningful Alerts

**Good Alert**:
```sql
-- Specific, actionable, with context
SELECT COUNT(*) as checkout_failures
FROM spans
WHERE name = 'tool.execution.checkout_book'
  AND attributes->>'tool.success' = 'false'
  AND timestamp > NOW() - INTERVAL '10 minutes'
HAVING COUNT(*) > 5
```

**Bad Alert**:
```sql
-- Too generic, noisy
SELECT COUNT(*) FROM spans WHERE duration_ms > 1000
```

### 4. Use Trace Sampling in Production

```python
# Production config
LOGFIRE_SAMPLE_RATE = 0.1  # Sample 10% of requests

# But always sample errors
if error_occurred:
    span.set_attribute("sampling.priority", 1)
```

### 5. Regular Review Routine

**Daily**:
- Check error rate
- Review any alerts
- Spot check slow operations

**Weekly**:
- Analyze performance trends
- Review most common errors
- Check resource utilization

**Monthly**:
- Deep dive into usage patterns
- Optimize slow queries
- Update dashboards and alerts

## Troubleshooting

### No Data Appearing

1. Check environment variables are set
2. Verify `LOGFIRE_ENABLED=true`
3. Check network connectivity
4. Look for errors in console if `LOGFIRE_CONSOLE=true`

### Missing Spans

1. Verify sampling rate isn't too low
2. Check that instrumentation is applied
3. Look for exceptions in middleware

### Performance Impact

1. Reduce sampling rate
2. Disable console output in production
3. Limit span attributes
4. Use batch export

## Advanced Features

### Custom Span Attributes

```python
# Add business context
span.set_attribute("library.season", "summer_reading")
span.set_attribute("library.branch", "main")
```

### Trace Correlation

```python
# Link related operations
span.set_attribute("correlation.checkout_id", checkout_id)
span.set_attribute("correlation.patron_session", session_id)
```

### Export to Other Systems

```python
# Export to Prometheus
logfire.configure(
    additional_exporters=[
        PrometheusExporter(port=9090)
    ]
)
```

## Conclusion

Logfire provides powerful observability for the Virtual Library MCP Server. Start with the basics:

1. ✅ View traces for individual requests
2. ✅ Monitor error rates and types
3. ✅ Track performance metrics
4. ✅ Analyze usage patterns

Then advance to:
- 🎯 Custom dashboards for your needs
- 🎯 Sophisticated alerting rules
- 🎯 Performance optimization based on data
- 🎯 Business intelligence from telemetry

Remember: Good observability helps you understand not just *what* happened, but *why* it happened and *how* to improve it.

## Resources

- [Logfire Documentation](https://docs.pydantic.dev/logfire)
- [OpenTelemetry Concepts](https://opentelemetry.io/docs/concepts/)
- [MCP Protocol Specification](https://modelcontextprotocol.io)
- [Virtual Library MCP Server](https://github.com/your-org/virtual-library-mcp)