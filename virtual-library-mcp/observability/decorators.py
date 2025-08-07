"""Decorators for tracing MCP components."""

import functools
from collections.abc import Callable
from datetime import datetime
from typing import Any

import logfire


def trace_tool(tool_name: str):
    """Decorator to trace MCP tool execution."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
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
                    span.set_attribute(
                        "tool.duration_ms", (datetime.now() - start_time).total_seconds() * 1000
                    )

                    # Add result metrics
                    _add_tool_result_metrics(span, tool_name, result)

                    return result

                except Exception as e:
                    span.set_attribute("tool.success", False)
                    span.set_attribute("tool.error", str(e))
                    raise

        return wrapper

    return decorator


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


def trace_prompt(prompt_name: str):
    """Decorator to trace MCP prompt generation."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            with logfire.span(
                f"prompt.generation.{prompt_name}",
                prompt_name=prompt_name,
            ) as span:
                start_time = datetime.now()

                try:
                    result = await func(*args, **kwargs)

                    span.set_attribute("prompt.success", True)
                    span.set_attribute(
                        "prompt.duration_ms", (datetime.now() - start_time).total_seconds() * 1000
                    )

                    # Add result metrics
                    if hasattr(result, "__len__"):
                        span.set_attribute("result.length", len(result))

                    return result

                except Exception as e:
                    span.set_attribute("prompt.success", False)
                    span.set_attribute("prompt.error", str(e))
                    raise

        return wrapper

    return decorator


def _categorize_tool(tool_name: str) -> str:
    """Categorize tools for better organization."""
    if "checkout" in tool_name or "return" in tool_name:
        return "circulation"
    if "import" in tool_name or "maintenance" in tool_name:
        return "catalog"
    if "search" in tool_name:
        return "discovery"
    if "insight" in tool_name:
        return "ai"
    return "general"


def _add_attributes(span, prefix: str, data: dict):
    """Add attributes to span (educational app - no PII concerns)."""
    for key, value in data.items():
        if isinstance(value, str | int | float | bool):
            span.set_attribute(f"{prefix}.{key}", value)


def _add_tool_result_metrics(span, tool_name: str, result: Any):
    """Add tool-specific result metrics."""
    if tool_name == "bulk_import" and hasattr(result, "imported_count"):
        span.set_attribute("result.imported_count", result.imported_count)
    elif tool_name == "search_catalog" and hasattr(result, "__len__"):
        span.set_attribute("result.match_count", len(result))
