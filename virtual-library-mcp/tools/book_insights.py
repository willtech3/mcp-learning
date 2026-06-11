"""
Book Insights Tool - MCP Sampling in Practice

Generates AI-powered insights about catalog books by asking the CLIENT's
LLM to write them (MCP sampling). Demonstrates:

1. ctx.sample() — server-initiated completions with model preferences
2. Tool-enabled sampling (SEP-1577, MCP 2025-11-25): for similar-book
   recommendations, the client's LLM is handed a search tool so its
   suggestions are grounded in what this library actually owns
3. Graceful fallback when the client doesn't support sampling
"""

import logging
from typing import Annotated, Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from database.author_repository import AuthorRepository
from database.book_repository import BookRepository, BookSearchParams
from database.repository import PaginationParams
from database.session import session_scope
from models.book import Book
from sampling import request_ai_generation

logger = logging.getLogger(__name__)

InsightType = Literal["summary", "themes", "discussion_questions", "similar_books"]


def search_library_catalog(genre: str, limit: int = 8) -> list[dict]:
    """Search this library's catalog for available books in a genre.

    Exposed to the *client's* LLM during tool-enabled sampling so that
    similar-book recommendations only mention titles we actually hold.
    """
    with session_scope() as session:
        repo = BookRepository(session)
        result = repo.search(
            search_params=BookSearchParams(genre=genre.strip().title(), available_only=False),
            pagination=PaginationParams(page=1, page_size=max(1, min(limit, 20))),
        )
        return [
            {
                "title": b.title,
                "isbn": b.isbn,
                "genre": b.genre,
                "year": b.publication_year,
                "available": b.is_available,
            }
            for b in result.items
        ]


async def generate_book_insights(
    isbn: Annotated[
        str, Field(description="ISBN-13 of the book to generate insights for", pattern=r"^\d{13}$")
    ],
    ctx: Context,
    insight_type: Annotated[
        InsightType,
        Field(
            description="Kind of insight: summary, themes, discussion_questions, or similar_books"
        ),
    ] = "summary",
) -> str:
    """Generate AI-powered insights about a book using MCP sampling.

    Falls back to genre-based static content when the connected client
    doesn't support sampling, so the tool is useful everywhere.
    """
    with session_scope() as session:
        book = BookRepository(session).get_by_isbn(isbn)
        if not book:
            raise ToolError(f"Book with ISBN {isbn} not found in the catalog.")
        author = AuthorRepository(session).get_by_id(book.author_id)
        author_name = author.name if author else "Unknown Author"

    generators = {
        "summary": _generate_summary,
        "themes": _generate_themes,
        "discussion_questions": _generate_discussion_questions,
        "similar_books": _generate_similar_books,
    }
    result = await generators[insight_type](ctx, book, author_name)

    if result:
        title = insight_type.replace("_", " ").title()
        return f"**AI-Generated {title} for '{book.title}'**\n\n{result}"
    logger.info("Sampling unavailable for %s; serving fallback content", insight_type)
    return _generate_fallback_response(book, author_name, insight_type)


async def _generate_summary(ctx: Context, book: Book, author_name: str) -> str | None:
    prompt = f"""Create an engaging summary for this library book:

Title: {book.title}
Author: {author_name}
Genre: {book.genre}
Published: {book.publication_year}
Current description: {book.description or "No description available"}

Generate a compelling 2-3 paragraph summary that would help library patrons
decide if they want to read this book. Focus on themes, style, and what makes it unique."""

    return await request_ai_generation(
        ctx,
        prompt,
        system_prompt=(
            "You are a knowledgeable librarian creating book summaries. "
            "Be informative and engaging without spoilers."
        ),
        max_tokens=400,
    )


async def _generate_themes(ctx: Context, book: Book, author_name: str) -> str | None:
    prompt = f"""Analyze the major themes in this book:

Title: {book.title}
Author: {author_name}
Genre: {book.genre}
Description: {book.description or "No description available"}

Identify and explain 3-5 major themes, each with a brief explanation of how
the story explores it."""

    return await request_ai_generation(
        ctx,
        prompt,
        system_prompt=(
            "You are a literature expert analyzing book themes for library patrons. "
            "Be insightful but avoid major spoilers."
        ),
        max_tokens=500,
        temperature=0.6,
    )


async def _generate_discussion_questions(ctx: Context, book: Book, author_name: str) -> str | None:
    prompt = f"""Create thoughtful discussion questions for a book club reading:

Title: {book.title}
Author: {author_name}
Genre: {book.genre}

Generate 5-7 open-ended questions covering themes, characters, and the
reader's personal connection to the story."""

    return await request_ai_generation(
        ctx,
        prompt,
        system_prompt=(
            "You are a book club facilitator. Make questions thought-provoking "
            "and open to interpretation."
        ),
        max_tokens=600,
        temperature=0.8,
    )


async def _generate_similar_books(ctx: Context, book: Book, author_name: str) -> str | None:
    """Tool-enabled sampling (SEP-1577): the client's LLM can call our
    search_library_catalog() tool mid-completion, so every recommendation
    can cite real holdings and availability."""
    prompt = f"""Recommend books from THIS library similar to:

Title: {book.title}
Author: {author_name}
Genre: {book.genre}
Description: {book.description or "No description available"}

Use the search_library_catalog tool to check what the library holds in
relevant genres, then suggest 3-5 of those titles. For each, explain what
makes it similar and note whether it is currently available."""

    try:
        result = await ctx.sample(
            messages=prompt,
            system_prompt=(
                "You are a library recommendation expert. Ground every "
                "recommendation in actual catalog holdings via the provided tool."
            ),
            max_tokens=700,
            temperature=0.8,
            tools=[search_library_catalog],
        )
    except Exception as e:
        logger.info("Tool-enabled sampling unavailable: %s", e)
        return None
    return result.text or None


def _generate_fallback_response(book: Book, author_name: str, insight_type: InsightType) -> str:
    """Meaningful degradation when the client has no sampling support."""
    base_info = (
        f"**Book Information**\n\nTitle: {book.title}\nAuthor: {author_name}\n"
        f"Genre: {book.genre}\nYear: {book.publication_year}\n\n"
    )

    if insight_type == "summary":
        return base_info + (
            book.description
            or "No summary available. AI-generated summaries require a client with sampling support."
        )

    if insight_type == "themes":
        fallback_themes = {
            "Fiction": "Common themes might include: human nature, relationships, conflict, and personal growth.",
            "Mystery": "Typical themes include: justice, deception, truth, and moral ambiguity.",
            "Science Fiction": "Common themes: technology's impact, human identity, social commentary, and future possibilities.",
            "Fantasy": "Often explores: good vs evil, power and corruption, coming of age, and destiny.",
        }
        genre_themes = fallback_themes.get(book.genre, "Themes vary by genre and author style.")
        return (
            base_info
            + f"**Genre-Typical Themes**\n\n{genre_themes}\n\n"
            + "*Note: AI-generated theme analysis requires a client with sampling support.*"
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

    return (
        base_info
        + f"""**Finding Similar Books**

To find books similar to this one, consider:
- Other books by {author_name}
- Other {book.genre} books in our catalog
- Books from the same era ({book.publication_year}s)

*Note: AI-generated personalized recommendations require a client with sampling support.*"""
    )
