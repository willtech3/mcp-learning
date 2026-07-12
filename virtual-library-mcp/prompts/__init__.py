"""Prompts Module - AI-Assisted Library Interactions

MCP prompts are user-invoked conversation templates: unlike tools (model-
invoked) or resources (application-driven), prompts appear in client UIs
(slash commands, menus) for the USER to pick. Each one accepts arguments,
pulls live library data, and returns messages that prime the LLM.

register() binds them with 2025-11-25 metadata (icons, tags).

PROMPT_SPECS is the declarative source of truth shared by BOTH protocol
eras. The legacy path derives argument metadata from the function
signatures via FastMCP; the modern path (MCP 2026-07-28, modern/registry.py)
reads the hand-declared argument tables here instead — prompt arguments are
string-typed on the wire in every revision, so an explicit table is clearer
than re-deriving JSON Schema just to throw most of it away. The ``fn``
objects are the exact same callables FastMCP registers.
"""

from dataclasses import dataclass, field
from typing import Any

from fastmcp import FastMCP
from mcp.types import Icon

from icons import BOOK_ICON, SPARKLE_ICON

from .book_recommendations import book_recommendation_prompt
from .reading_plan import reading_plan_prompt
from .review_generator import review_generator_prompt


@dataclass(frozen=True)
class PromptArgSpec:
    """One prompt argument as it appears on the wire (name-sorted lists,
    string values). Mirrors the spec's PromptArgument: name/description/
    required — prompt arguments carry no type information in MCP."""

    name: str
    description: str
    required: bool = False


@dataclass(frozen=True)
class PromptSpec:
    """Era-agnostic description of one prompt template."""

    fn: Any
    name: str
    description: str
    arguments: tuple[PromptArgSpec, ...] = ()
    icons: list[Icon] = field(default_factory=list)
    tags: frozenset[str] = frozenset()


PROMPT_SPECS: list[PromptSpec] = [
    PromptSpec(
        fn=book_recommendation_prompt,
        # FastMCP registers under fn.__name__; keep the eras consistent.
        name="recommend_books",
        description="Generate personalized book recommendations from the live catalog",
        arguments=(
            PromptArgSpec("genre", "Preferred genre, e.g. 'Fiction' or 'Mystery'"),
            PromptArgSpec("mood", "Current reading mood, e.g. 'thrilling'"),
            PromptArgSpec("patron_id", "Patron to personalize recommendations for"),
            PromptArgSpec("limit", "How many recommendations to request (default 5)"),
        ),
        icons=[SPARKLE_ICON],
        tags=frozenset({"ai", "patrons"}),
    ),
    PromptSpec(
        fn=reading_plan_prompt,
        name="generate_reading_plan",
        description="Create a structured reading plan for a learning goal",
        arguments=(
            PromptArgSpec("goal", "Learning goal, e.g. 'learn AI'", required=True),
            PromptArgSpec("duration", "Plan length: week, month, quarter, or year"),
            PromptArgSpec(
                "experience_level",
                "Starting level: beginner, intermediate, advanced, or expert",
            ),
            PromptArgSpec("time_commitment", "Reading pace: light, moderate, or intensive"),
        ),
        icons=[BOOK_ICON],
        tags=frozenset({"ai", "patrons"}),
    ),
    PromptSpec(
        fn=review_generator_prompt,
        name="generate_book_review",
        description="Draft a professional book review from catalog data",
        arguments=(
            PromptArgSpec("isbn", "ISBN-13 of the book to review", required=True),
            PromptArgSpec("review_type", "Style: summary, critical, or recommendation"),
            PromptArgSpec("target_audience", "Audience the review is written for"),
            PromptArgSpec("include_quotes", "Whether to include illustrative quotes"),
        ),
        icons=[SPARKLE_ICON],
        tags=frozenset({"ai"}),
    ),
]


def register(mcp: FastMCP) -> None:
    """Register every prompt template with the server."""
    for spec in PROMPT_SPECS:
        mcp.prompt(spec.fn, icons=spec.icons, tags=set(spec.tags))


__all__ = [
    "PROMPT_SPECS",
    "PromptArgSpec",
    "PromptSpec",
    "book_recommendation_prompt",
    "reading_plan_prompt",
    "register",
    "review_generator_prompt",
]
