"""Dashboard query definitions for Logfire."""

# MCP Protocol Overview Queries
MCP_REQUEST_RATE = """
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
"""

MCP_SLOWEST_OPERATIONS = """
-- Slowest operations (P95)
SELECT
    attributes->>'mcp_method' as method,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) as p95_ms,
    COUNT(*) as count
FROM spans
WHERE name LIKE 'MCP %'
GROUP BY method
ORDER BY p95_ms DESC;
"""

# Library Operations Queries
BOOK_CIRCULATION_TRENDS = """
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
"""

MOST_ACTIVE_PATRONS = """
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
"""

# Error Tracking Queries
ERROR_RATE = """
-- Error rate by method
SELECT
    attributes->>'mcp_method' as method,
    COUNT(CASE WHEN attributes->>'mcp.status' = 'error' THEN 1 END) as errors,
    COUNT(*) as total,
    ROUND(COUNT(CASE WHEN attributes->>'mcp.status' = 'error' THEN 1 END) * 100.0 / COUNT(*), 2) as error_rate
FROM spans
WHERE timestamp > NOW() - INTERVAL '1 hour'
GROUP BY method
HAVING COUNT(*) > 10
ORDER BY error_rate DESC;
"""
