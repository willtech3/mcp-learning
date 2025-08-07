"""FastMCP middleware for instrumentation."""

from datetime import datetime
from typing import Any

from fastmcp.server.middleware import Middleware, MiddlewareContext

from . import LOGFIRE_AVAILABLE, get_config, logfire


class MCPInstrumentationMiddleware(Middleware):
    """Middleware to trace all MCP protocol operations."""

    def __init__(self):
        self.start_time = datetime.now()
        # Ensure we have a valid config
        self.config = get_config()
        self.enabled = LOGFIRE_AVAILABLE and self.config.enabled

    async def on_message(self, context: MiddlewareContext, call_next) -> Any:
        """Instrument all MCP messages."""
        # Skip if not enabled
        if not self.enabled:
            return await call_next(context)

        method = context.method

        # Determine operation type
        operation_type = self._get_operation_type(method)

        with logfire.span(
            f"mcp.{operation_type}.{method}",
            _span_name=f"MCP {method}",
            mcp_method=method,
            mcp_operation_type=operation_type,
            mcp_source=getattr(context, "source", "unknown"),
        ) as span:
            # Try to extract attributes from the message
            if hasattr(context, "message"):
                # For tool calls
                if hasattr(context.message, "name"):
                    span.set_attribute("tool.name", context.message.name)
                # For resource reads
                elif hasattr(context.message, "uri"):
                    span.set_attribute("resource.uri", context.message.uri)

            try:
                # Execute the next middleware/handler
                result = await call_next(context)

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
        if method.startswith("tools/"):
            return "tool"
        if method.startswith("prompts/"):
            return "prompt"
        if method.startswith("completion/"):
            return "sampling"
        return "system"

    def _add_result_metrics(self, span, method: str, result: Any):
        """Add result-based metrics to span."""
        if method == "resources/list" and isinstance(result, dict):
            resources = result.get("resources", [])
            span.set_attribute("result.resource_count", len(resources))
        elif method == "tools/list" and isinstance(result, dict):
            tools = result.get("tools", [])
            span.set_attribute("result.tool_count", len(tools))
