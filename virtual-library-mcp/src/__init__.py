"""
Virtual Library MCP Server Package.

This package implements a comprehensive MCP (Model Context Protocol) server
that demonstrates all protocol features through a library management system.

Key Components:
- models: Pydantic models for data validation and serialization
- database: SQLAlchemy models and session management
- config: Configuration management with Pydantic v2
- resources: MCP resources (read-only endpoints)
- tools: MCP tools (operations with side effects)
- prompts: MCP prompts (LLM interaction templates)
"""

__version__ = "0.1.0"

# Make database module available at package level
from . import database

__all__ = [
    "__version__",
    "database",
]
