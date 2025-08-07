"""Reading Plan Generator Prompt - Learning Path Creation

Creates structured reading plans based on goals and time constraints.
Client receives formatted prompt for LLM to design learning journey.

Usage: prompt.get("generate_reading_plan", {"goal": "learn AI", "duration": "quarter"})
"""

from typing import Literal

from database.book_repository import BookRepository
from database.repository import PaginationParams
from database.session import get_session


async def generate_reading_plan(
    goal: str,
    duration: Literal["week", "month", "quarter", "year"] = "month",
    experience_level: Literal["beginner", "intermediate", "advanced"] = "beginner",
    time_commitment: Literal["light", "moderate", "intensive"] = "moderate",
    _session=None,  # For testing
) -> str:
    """Generate structured reading plan for learning goals.

    Searches catalog for relevant books and formats prompt
    for LLM to create progressive learning path.
    """

    # Get database session
    session = _session or get_session()
    should_close = _session is None

    try:
        book_repo = BookRepository(session)

        # Search for books related to the goal
        # In a real implementation, we'd have better search capabilities
        pagination = PaginationParams(page=1, page_size=100)
        result = book_repo.get_all(pagination=pagination)
        all_books = result if isinstance(result, list) else result.items

        # Filter books that might be relevant (simple keyword matching)
        goal_keywords = goal.lower().split()
        relevant_books = []

        for book in all_books:
            # Check if any keyword appears in title, genre, or description
            book_text = f"{book.title} {book.genre}".lower()
            if any(keyword in book_text for keyword in goal_keywords):
                relevant_books.append(book)

        # Sort by publication year (newer first) and limit
        relevant_books.sort(key=lambda b: b.publication_year, reverse=True)
        relevant_books = relevant_books[:20]

        # Format book list
        book_list = []
        for book in relevant_books:
            availability = "Available" if book.available_copies > 0 else "Waitlist"
            book_list.append(f"- '{book.title}' ({book.publication_year}) - {availability}")

        # Map duration to approximate book count
        duration_map = {"week": 1, "month": 3, "quarter": 8, "year": 24}

        # Map time commitment to pages per week
        commitment_map = {"light": 100, "moderate": 250, "intensive": 500}

        target_books = duration_map[duration]
        pages_per_week = commitment_map[time_commitment]

        # Build the prompt
        return f"""You are an expert learning curator creating a personalized reading plan.

Goal: {goal}
Duration: {duration}
Experience Level: {experience_level}
Time Commitment: {time_commitment} (approximately {pages_per_week} pages per week)

Available books that might be relevant:
{chr(10).join(book_list) if book_list else "No directly matching books found, but you can suggest general titles."}

Please create a structured reading plan that:

1. **Learning Path Overview**
   - Explain the progression from {experience_level} to the next level
   - Identify key concepts to master
   - Set realistic milestones

2. **Book Recommendations** (aim for {target_books} books)
   - Order books from foundational to advanced
   - For each book, explain:
     * Why it's included in the plan
     * Key concepts it covers
     * Estimated reading time
     * Prerequisites (if any)

3. **Reading Schedule**
   - Week-by-week breakdown
   - Account for {pages_per_week} pages per week capacity
   - Include review/practice time

4. **Supplementary Resources**
   - Suggest complementary materials (articles, videos, exercises)
   - Recommend practical projects or applications
   - Identify knowledge checkpoints

5. **Success Metrics**
   - Define what success looks like
   - Suggest ways to test understanding
   - Provide next steps after completion

Format the plan clearly with sections and bullet points for easy following."""

    finally:
        if should_close:
            session.close()


# Export for server registration
reading_plan_prompt = generate_reading_plan
