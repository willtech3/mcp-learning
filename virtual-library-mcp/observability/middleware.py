"""FastMCP middleware for instrumentation."""

from datetime import datetime
from typing import Any

from . import logfire


class MCPInstrumentationMiddleware:
    """Middleware to trace all MCP protocol operations."""

    def __init__(self):
        self.start_time = datetime.now()

    async def __call__(self, handler, request: dict[str, Any]) -> Any:
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
        if method.startswith("tools/"):
            return "tool"
        if method.startswith("prompts/"):
            return "prompt"
        if method.startswith("completion/"):
            return "sampling"
        return "system"

    def _add_method_attributes(self, span, method: str, params: dict):
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
