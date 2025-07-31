"""Reading Plan Generator Prompt - Structured Learning Paths

This module creates personalized reading plans that guide patrons through
a curated sequence of books to achieve their learning goals.

MCP PROMPT BENEFITS:
- Reusable templates for common library services
- Integration with real catalog data
- Consistent, high-quality AI responses
- Parameterized for different use cases
"""

from typing import Literal

from virtual_library_mcp.database.book_repository import BookRepository
from virtual_library_mcp.database.repository import PaginationParams
from virtual_library_mcp.database.session import get_session


async def generate_reading_plan(
    goal: str,
    duration: Literal["week", "month", "quarter", "year"] = "month",
    experience_level: Literal["beginner", "intermediate", "advanced"] = "beginner",
    time_commitment: Literal["light", "moderate", "intensive"] = "moderate",
    _session=None,  # For testing
) -> str:
    """Create a structured reading plan to achieve specific learning goals.

    This prompt demonstrates:
    - Structured learning path generation
    - Consideration of time constraints and experience
    - Progressive difficulty scaling
    - Integration with available library resources

    Args:
        goal: Learning objective (e.g., "Learn Python programming", "Understand climate science")
        duration: Time frame for the reading plan
        experience_level: Current knowledge level in the subject
        time_commitment: Reading time availability

    Returns:
        Formatted prompt for generating a reading plan
    """

    # Get database session
    session = _session or next(get_session())
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
