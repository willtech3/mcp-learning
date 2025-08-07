"""
Educational MCP Sampling Module for Virtual Library Server

This module demonstrates how to use the MCP sampling feature to request
AI-generated content from compatible clients. Sampling allows servers to
leverage the client's LLM capabilities for dynamic content generation.

Key concepts demonstrated:
1. Client capability checking
2. Request construction with model preferences
3. Error handling and fallbacks
4. Proper async/await patterns
"""

import logging

from fastmcp import Context
from mcp.types import (
    CreateMessageRequestParams,
    ModelHint,
    ModelPreferences,
    SamplingMessage,
    TextContent,
)

logger = logging.getLogger(__name__)


async def request_ai_generation(
    context: Context,
    prompt: str,
    system_prompt: str | None = None,
    max_tokens: int = 500,
    temperature: float = 0.7,
    intelligence_priority: float = 0.7,
    speed_priority: float = 0.5,
) -> str | None:
    """
    Request AI-generated content from the MCP client using sampling.

    This function demonstrates the complete sampling workflow:
    1. Checking if the client supports sampling
    2. Building a properly structured request
    3. Handling the response
    4. Gracefully handling errors

    Args:
        context: The FastMCP request context (provides access to session)
        prompt: The user prompt to send to the LLM
        system_prompt: Optional system prompt to guide the LLM's behavior
        max_tokens: Maximum tokens to generate (default: 500)
        temperature: Controls randomness (0.0-1.0, default: 0.7)
        intelligence_priority: How important is model capability (0.0-1.0)
        speed_priority: How important is fast response (0.0-1.0)

    Returns:
        The generated text if successful, None if sampling failed or unavailable
    """
    # Step 1: Check if the client supports sampling
    # This is crucial - not all MCP clients have LLM capabilities
    if not context.request_context.session.client_capabilities.sampling:
        logger.info("Client does not support sampling - returning None")
        return None

    try:
        # Step 2: Build the sampling request
        # The request includes messages, model preferences, and generation parameters

        # Create the message array with the user's prompt
        messages = [
            SamplingMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=prompt
                )
            )
        ]

        # Model preferences help the client choose the right model
        # Higher values indicate higher priority for that aspect
        model_preferences = ModelPreferences(
            hints=[
                # Prefer Claude models for this educational example
                ModelHint(name="claude-3-sonnet"),
                ModelHint(name="claude"),
            ],
            intelligence_priority=intelligence_priority,
            speed_priority=speed_priority,
            # Cost priority is inverse of the other two
            cost_priority=1.0 - (intelligence_priority + speed_priority) / 2,
        )

        # Build the complete request parameters
        request_params = CreateMessageRequestParams(
            messages=messages,
            modelPreferences=model_preferences,
            maxTokens=max_tokens,
            temperature=temperature,
        )

        # Add system prompt if provided
        if system_prompt:
            request_params.systemPrompt = system_prompt

        # Step 3: Make the sampling request
        # This is an async operation that goes to the client
        logger.debug(f"Sending sampling request with prompt: {prompt[:100]}...")

        result = await context.request_context.session.create_message(request_params)

        # Step 4: Extract and return the generated text
        # The result contains the AI's response in a structured format
        if result and result.content and result.content.type == "text":
            generated_text = result.content.text
            logger.info(f"Successfully generated {len(generated_text)} characters")
            return generated_text
        logger.warning("Sampling returned unexpected content type")
        return None

    except Exception:
        # Step 5: Handle errors gracefully
        # Common errors include timeouts, user rejection, or API issues
        logger.exception("Sampling request failed")
        return None


async def generate_book_summary(
    context: Context,
    book_title: str,
    author: str,
    genre: str,
    year: int,
    existing_description: str | None = None,
) -> str | None:
    """
    Generate an AI-powered book summary using sampling.

    This is a specific use case that shows how to:
    - Construct domain-specific prompts
    - Use appropriate system prompts
    - Set model preferences for the task

    Args:
        context: The FastMCP request context
        book_title: Title of the book
        author: Author name
        genre: Book genre
        year: Publication year
        existing_description: Optional existing description to enhance

    Returns:
        AI-generated book summary or None if generation failed
    """
    # Construct a detailed prompt with book information
    prompt = f"""Generate a compelling summary for this book:

Title: {book_title}
Author: {author}
Genre: {genre}
Year: {year}
{"Existing description: " + existing_description if existing_description else ""}

Please create an engaging 2-3 paragraph summary that:
- Captures the essence of the book
- Mentions key themes without spoilers
- Appeals to readers interested in {genre}
- Is appropriate for a library catalog"""

    # System prompt guides the AI's behavior
    system_prompt = """You are a knowledgeable librarian creating book summaries for a library catalog.
Your summaries should be informative, engaging, and help readers decide if they want to read the book.
Avoid spoilers and focus on themes, writing style, and what makes the book unique."""

    # For summaries, we prioritize quality over speed
    return await request_ai_generation(
        context=context,
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=300,  # Summaries should be concise
        temperature=0.7,  # Some creativity is good
        intelligence_priority=0.8,  # High quality is important
        speed_priority=0.3,  # Speed is less critical
    )


async def generate_reading_recommendation(
    context: Context,
    patron_name: str,
    favorite_genres: list[str],
    recent_books: list[str],
    reading_level: str = "adult",
) -> str | None:
    """
    Generate personalized reading recommendations using sampling.

    This example shows how to:
    - Use context about the user (patron)
    - Create personalized content
    - Balance different model priorities

    Args:
        context: The FastMCP request context
        patron_name: Name of the library patron
        favorite_genres: List of genres the patron enjoys
        recent_books: List of recently read books
        reading_level: Reading level (child/teen/adult)

    Returns:
        Personalized recommendation text or None if generation failed
    """
    # Build context about the patron's reading preferences
    genres_text = ", ".join(favorite_genres)
    recent_text = "\n- ".join(recent_books) if recent_books else "No recent reading history"

    prompt = f"""Create a personalized book recommendation for a library patron:

Patron: {patron_name}
Favorite genres: {genres_text}
Reading level: {reading_level}
Recently read books:
- {recent_text}

Please suggest 3-5 books they might enjoy, with brief explanations of why each book would appeal to them based on their preferences."""

    system_prompt = f"""You are a helpful library assistant making personalized book recommendations.
Consider the patron's favorite genres and recent reading history.
Make recommendations appropriate for their reading level ({reading_level}).
Be enthusiastic and encouraging while explaining why each book is a good match."""

    # Recommendations balance quality and speed
    return await request_ai_generation(
        context=context,
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=600,  # More space for multiple recommendations
        temperature=0.8,  # More creativity for varied recommendations
        intelligence_priority=0.7,  # Good quality
        speed_priority=0.6,  # Reasonably fast for interactive use
    )
