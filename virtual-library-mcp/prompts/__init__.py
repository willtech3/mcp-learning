"""Prompts Module - AI-Assisted Library Interactions

MCP prompts are user-invoked conversation templates: unlike tools (model-
invoked) or resources (application-driven), prompts appear in client UIs
(slash commands, menus) for the USER to pick. Each one accepts arguments,
pulls live library data, and returns messages that prime the LLM.

register() binds them with 2025-11-25 metadata (icons, tags).
"""

from fastmcp import FastMCP

from icons import BOOK_ICON, SPARKLE_ICON

from .book_recommendations import book_recommendation_prompt
from .reading_plan import reading_plan_prompt
from .review_generator import review_generator_prompt


def register(mcp: FastMCP) -> None:
    """Register every prompt template with the server."""
    mcp.prompt(book_recommendation_prompt, icons=[SPARKLE_ICON], tags={"ai", "patrons"})
    mcp.prompt(reading_plan_prompt, icons=[BOOK_ICON], tags={"ai", "patrons"})
    mcp.prompt(review_generator_prompt, icons=[SPARKLE_ICON], tags={"ai"})


__all__ = [
    "book_recommendation_prompt",
    "reading_plan_prompt",
    "register",
    "review_generator_prompt",
]
