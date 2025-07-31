"""Book Recommendation Prompt - AI-Powered Reading Suggestions

This module demonstrates how to create MCP prompts that leverage library data
to provide personalized book recommendations.

MCP PROMPT PATTERN:
This prompt follows the MCP pattern where:
1. Arguments customize the interaction (genre, mood, patron)
2. The handler queries actual library data for context
3. Messages guide the LLM to provide useful recommendations
4. The response integrates real catalog information
"""

from virtual_library_mcp.database.book_repository import BookRepository
from virtual_library_mcp.database.patron_repository import PatronRepository
from virtual_library_mcp.database.repository import PaginationParams
from virtual_library_mcp.database.session import get_session


async def recommend_books(
    genre: str | None = None,
    mood: str | None = None,
    patron_id: int | None = None,
    limit: int = 5,
    _session=None,  # For testing
) -> str:
    """Generate personalized book recommendations based on preferences.

    This prompt demonstrates:
    - Dynamic context building from database queries
    - Optional parameters for flexible interactions
    - Integration of patron history for personalization
    - Structured prompts that guide LLM responses

    Args:
        genre: Preferred genre to filter recommendations
        mood: Reader's current mood (e.g., "adventurous", "contemplative")
        patron_id: Optional patron ID for personalized recommendations
        limit: Maximum number of recommendations to generate

    Returns:
        List of messages forming the recommendation prompt
    """

    # Get database session
    session = _session or next(get_session())
    should_close = _session is None

    try:
        # Build context from library data
        book_repo = BookRepository(session)

        # Get available books based on criteria
        if genre:
            # Filter by genre if specified
            pagination = PaginationParams(page=1, page_size=20)
            result = book_repo.get_by_genre(genre, pagination=pagination)
            books = result.items
        else:
            # Get a diverse selection
            pagination = PaginationParams(page=1, page_size=50)
            result = book_repo.get_all(pagination=pagination)
            books = result if isinstance(result, list) else result.items

        # Get patron context if patron_id provided
        patron_context = ""
        if patron_id:
            patron_repo = PatronRepository(session)
            patron = patron_repo.get_by_id(patron_id)
            if patron:
                # For simplicity, just note that we have a patron
                patron_context = f"\n\nRecommending for patron: {patron.name} (Member since {patron.membership_date})"

        # Format available books
        book_list = []
        for book in books[:20]:  # Limit context size
            availability = "Available" if book.available_copies > 0 else "Checked out"
            book_list.append(
                f"- '{book.title}' ({book.genre}, {book.publication_year}) - {availability}"
            )

        # Build and return the prompt content
        return f"""You are a knowledgeable librarian helping a patron find their next great read.

Based on the following criteria, recommend {limit} books from our library catalog:
{f"- Genre preference: {genre}" if genre else "- No specific genre preference"}
{f"- Current mood: {mood}" if mood else "- Open to any mood/theme"}
{patron_context}

Here are some books currently in our catalog:
{chr(10).join(book_list)}

Please provide thoughtful recommendations that:
1. Match the patron's preferences and mood
2. Include a mix of popular and lesser-known titles
3. Briefly explain why each book would be a good fit
4. Mention availability status
5. Suggest a reading order if the books are related

Format your response as a numbered list with title, author, and your recommendation reason."""

    finally:
        if should_close:
            session.close()


# Export the prompt function for server registration
# FastMCP will use the function signature and docstring to generate the prompt metadata
book_recommendation_prompt = recommend_books
