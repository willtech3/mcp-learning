"""Book Recommendation Prompt - Personalized Reading Suggestions

Generates book recommendations based on genre, mood, and patron history.
Client receives formatted prompt ready for LLM to provide suggestions.

Usage: prompt.get("recommend_books", {"genre": "mystery", "mood": "thrilling"})
"""

from ..database.book_repository import BookRepository
from ..database.patron_repository import PatronRepository
from ..database.repository import PaginationParams
from ..database.session import get_session


async def recommend_books(
    genre: str | None = None,
    mood: str | None = None,
    patron_id: int | None = None,
    limit: int = 5,
    _session=None,  # For testing
) -> str:
    """Generate personalized book recommendations.

    Fetches available books matching criteria and formats prompt
    for LLM to suggest readings based on genre, mood, and history.
    """

    session = _session or next(get_session())
    should_close = _session is None

    try:
        book_repo = BookRepository(session)

        if genre:
            pagination = PaginationParams(page=1, page_size=20)
            result = book_repo.get_by_genre(genre, pagination=pagination)
            books = result.items
        else:
            pagination = PaginationParams(page=1, page_size=50)
            result = book_repo.get_all(pagination=pagination)
            books = result if isinstance(result, list) else result.items

        patron_context = ""
        if patron_id:
            patron_repo = PatronRepository(session)
            patron = patron_repo.get_by_id(patron_id)
            if patron:
                patron_context = f"\n\nRecommending for patron: {patron.name} (Member since {patron.membership_date})"

        book_list = []
        for book in books[:20]:
            availability = "Available" if book.available_copies > 0 else "Checked out"
            book_list.append(
                f"- '{book.title}' ({book.genre}, {book.publication_year}) - {availability}"
            )

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


book_recommendation_prompt = recommend_books
