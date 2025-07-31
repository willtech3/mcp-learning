"""Prompts Module - AI-Assisted Library Interactions

This module demonstrates MCP prompts, which are pre-defined conversation templates
that help LLMs interact with the library system in consistent, useful ways.

MCP PROMPTS CONCEPT:
Prompts in MCP serve as reusable interaction patterns. They:
1. Define structured conversations between users and LLMs
2. Accept arguments to customize the interaction
3. Generate message sequences that guide the LLM's response
4. Ensure consistent, high-quality AI assistance

KEY FEATURES:
- Dynamic prompt generation based on arguments
- Integration with library data for context
- Support for both simple and complex interactions
- Extensible prompt system for future additions
"""

from .book_recommendations import book_recommendation_prompt
from .reading_plan import reading_plan_prompt
from .review_generator import review_generator_prompt

# Export all prompts for server registration
all_prompts = [
    book_recommendation_prompt,
    reading_plan_prompt,
    review_generator_prompt,
]

__all__ = ["all_prompts"]
