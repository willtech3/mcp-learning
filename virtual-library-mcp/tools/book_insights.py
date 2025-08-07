"""
Book Insights Tool - Educational Demonstration of MCP Sampling

This tool demonstrates how to integrate MCP sampling into a practical feature.
It generates AI-powered insights about books in the library catalog, showing
how sampling can enhance existing functionality with dynamic content.
"""

import logging
from typing import Literal

from fastmcp import Context
from pydantic import Field

from database.author_repository import AuthorRepository
from database.book_repository import BookRepository
from database.session import session_scope
from models.book import Book
# Observability is handled by middleware, not decorators
from sampling import request_ai_generation

logger = logging.getLogger(__name__)

# Type for different insight types
InsightType = Literal["summary", "themes", "discussion_questions", "similar_books"]


async def generate_book_insights_handler(
    context: Context,
    isbn: str = Field(description="ISBN of the book to generate insights for"),
    insight_type: InsightType = Field(
        default="summary",
        description="Type of insight to generate: summary, themes, discussion_questions, or similar_books",
    ),
) -> str:
    """
    Generate AI-powered insights about a book using MCP sampling.

    This tool demonstrates:
    1. Integration with existing database/repository pattern
    2. Different types of AI-generated content
    3. Graceful fallback when sampling is unavailable
    4. Context-aware prompt construction

    The tool will attempt to use sampling if available, but provides
    meaningful fallback behavior for clients without sampling support.
    """
    # Get the book from the database
    with session_scope() as session:
        book_repo = BookRepository(session)
        book_model = book_repo.get_by_isbn(isbn)

        if not book_model:
            return f"Error: Book with ISBN {isbn} not found in the library catalog."

        # Get author name using author repository
        author_repo = AuthorRepository(session)
        author = author_repo.get_by_id(book_model.author_id)
        author_name = author.name if author else "Unknown Author"

    # Check if sampling is available
    if not context.request_context.session.client_capabilities.sampling:
        # Fallback behavior when sampling is not available
        return _generate_fallback_response(book_model, author_name, insight_type)

    # Generate different prompts based on insight type
    try:
        if insight_type == "summary":
            result = await _generate_summary(context, book_model, author_name)
        elif insight_type == "themes":
            result = await _generate_themes(context, book_model, author_name)
        elif insight_type == "discussion_questions":
            result = await _generate_discussion_questions(context, book_model, author_name)
        elif insight_type == "similar_books":
            result = await _generate_similar_books(context, book_model, author_name)
        else:
            result = None

        if result:
            return f"**AI-Generated {insight_type.replace('_', ' ').title()} for '{book_model.title}'**\n\n{result}"
        # Sampling failed, use fallback
        logger.warning(f"Sampling failed for {insight_type}, using fallback")
        return _generate_fallback_response(book_model, author_name, insight_type)

    except Exception:
        logger.exception("Error generating insights")
        return _generate_fallback_response(book_model, author_name, insight_type)


async def _generate_summary(context, book: Book, author_name: str) -> str | None:
    """Generate an enhanced book summary using sampling."""
    prompt = f"""Create an engaging summary for this library book:

Title: {book.title}
Author: {author_name}
Genre: {book.genre}
Published: {book.publication_year}
Current description: {book.description or "No description available"}

Generate a compelling 2-3 paragraph summary that would help library patrons decide if they want to read this book.
Focus on the main themes, writing style, and what makes it unique."""

    system_prompt = "You are a knowledgeable librarian creating book summaries. Be informative and engaging without spoilers."

    return await request_ai_generation(
        context=context,
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=400,
        temperature=0.7,
        intelligence_priority=0.8,
        speed_priority=0.4,
    )


async def _generate_themes(context, book: Book, author_name: str) -> str | None:
    """Generate analysis of book themes using sampling."""
    prompt = f"""Analyze the major themes in this book:

Title: {book.title}
Author: {author_name}
Genre: {book.genre}
Description: {book.description or "No description available"}

Identify and explain 3-5 major themes in this book. For each theme, provide a brief explanation of how it's explored in the story."""

    system_prompt = "You are a literature expert analyzing book themes for library patrons. Be insightful but avoid major spoilers."

    return await request_ai_generation(
        context=context,
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=500,
        temperature=0.6,
        intelligence_priority=0.9,  # High intelligence for literary analysis
        speed_priority=0.3,
    )


async def _generate_discussion_questions(context, book: Book, author_name: str) -> str | None:
    """Generate book club discussion questions using sampling."""
    prompt = f"""Create thoughtful discussion questions for a book club reading:

Title: {book.title}
Author: {author_name}
Genre: {book.genre}

Generate 5-7 open-ended discussion questions that would promote engaging conversation in a book club setting.
Include questions about themes, characters, and the reader's personal connection to the story."""

    system_prompt = "You are a book club facilitator creating discussion questions. Make them thought-provoking and open to interpretation."

    return await request_ai_generation(
        context=context,
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=600,
        temperature=0.8,  # More creativity for varied questions
        intelligence_priority=0.7,
        speed_priority=0.5,
    )


async def _generate_similar_books(context, book: Book, author_name: str) -> str | None:
    """Generate recommendations for similar books using sampling."""
    prompt = f"""Recommend books similar to:

Title: {book.title}
Author: {author_name}
Genre: {book.genre}
Description: {book.description or "No description available"}

Suggest 4-5 books that readers who enjoyed this book might also like.
For each recommendation, explain what makes it similar (themes, style, genre) and what makes it unique."""

    system_prompt = "You are a library recommendation expert. Focus on books that share themes or style while offering something new."

    return await request_ai_generation(
        context=context,
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=700,
        temperature=0.8,
        intelligence_priority=0.7,
        speed_priority=0.6,  # Faster for interactive recommendations
    )


def _generate_fallback_response(book: Book, author_name: str, insight_type: InsightType) -> str:
    """
    Generate a meaningful response when sampling is not available.

    This demonstrates how to gracefully degrade functionality while
    still providing value to the user.
    """
    base_info = f"**Book Information**\n\nTitle: {book.title}\nAuthor: {author_name}\nGenre: {book.genre}\nYear: {book.publication_year}\n\n"

    if insight_type == "summary":
        return base_info + (
            book.description
            or "No summary available. AI-generated summaries require a client with sampling support."
        )

    if insight_type == "themes":
        fallback_themes = {
            "Fiction": "Common themes might include: human nature, relationships, conflict, and personal growth.",
            "Non-Fiction": "Key topics might include: main arguments, supporting evidence, and practical applications.",
            "Mystery": "Typical themes include: justice, deception, truth, and moral ambiguity.",
            "Science Fiction": "Common themes: technology's impact, human identity, social commentary, and future possibilities.",
            "Fantasy": "Often explores: good vs evil, power and corruption, coming of age, and destiny.",
        }
        genre_themes = fallback_themes.get(book.genre, "Themes vary by genre and author style.")
        return (
            base_info
            + f"**Genre-Typical Themes**\n\n{genre_themes}\n\n*Note: AI-generated theme analysis requires a client with sampling support.*"
        )

    if insight_type == "discussion_questions":
        return (
            base_info
            + """**Generic Discussion Questions**

1. What was your overall impression of this book?
2. Which character did you relate to most and why?
3. What themes stood out to you while reading?
4. Would you recommend this book to others? Why or why not?
5. How did the book's setting influence the story?

*Note: AI-generated discussion questions tailored to this specific book require a client with sampling support.*"""
        )

    if insight_type == "similar_books":
        return (
            base_info
            + f"""**Finding Similar Books**

To find books similar to this one, consider:
- Other books by {author_name}
- Other {book.genre} books in our catalog
- Books from the same time period ({book.publication_year}s)
- Books with similar themes or settings

*Note: AI-generated personalized recommendations require a client with sampling support.*"""
        )

    return base_info + "Invalid insight type requested."


# Export as dictionary for server registration
generate_book_insights_tool = {
    "name": "generate_book_insights",
    "description": (
        "Generate AI-powered insights about a book including summaries, themes, "
        "discussion questions, or similar book recommendations. Demonstrates MCP "
        "sampling integration for dynamic content generation."
    ),
    "handler": generate_book_insights_handler,
}
