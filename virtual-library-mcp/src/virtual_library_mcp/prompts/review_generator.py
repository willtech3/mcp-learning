"""Review Generator Prompt - AI-Assisted Book Reviews

This module generates thoughtful book reviews based on library catalog data
and optional patron feedback, demonstrating AI content generation.

MCP PROMPT USE CASE:
This showcases how prompts can:
- Generate content based on structured data
- Incorporate multiple perspectives
- Maintain consistent quality and format
- Save time for library staff and patrons
"""

from typing import Literal

from virtual_library_mcp.database.book_repository import BookRepository
from virtual_library_mcp.database.session import get_session


async def generate_book_review(
    isbn: str,
    review_type: Literal["summary", "critical", "recommendation"] = "summary",
    target_audience: str | None = None,
    include_quotes: bool = False,
    _session=None,  # For testing
) -> str:
    """Generate a book review based on catalog data and circulation patterns.

    This prompt demonstrates:
    - Content generation from structured data
    - Different review styles for different purposes
    - Audience-aware writing
    - Integration of circulation data for popularity insights

    Args:
        isbn: ISBN of the book to review
        review_type: Style of review to generate
        target_audience: Specific audience to tailor the review for
        include_quotes: Whether to include notable quotes (simulated)

    Returns:
        Formatted prompt for generating a book review
    """

    # Get database session
    session = _session or next(get_session())
    should_close = _session is None

    try:
        book_repo = BookRepository(session)

        # Get book details
        book = book_repo.get_by_isbn(isbn)
        if not book:
            return f"No book found with ISBN {isbn}. Please provide a valid ISBN from our catalog."

        # For simplicity in this learning project, use placeholder values
        # In a real implementation, these would come from actual circulation data
        total_checkouts = 25  # Simulated value
        current_holds = 2  # Simulated value

        # Calculate popularity metrics
        if total_checkouts > 50:
            popularity = "Highly popular"
        elif total_checkouts > 20:
            popularity = "Moderately popular"
        elif total_checkouts > 5:
            popularity = "Growing interest"
        else:
            popularity = "Hidden gem"

        # Build review context
        review_context = {
            "summary": "concise overview that captures the essence without spoilers",
            "critical": "balanced analysis of strengths and weaknesses with literary merit assessment",
            "recommendation": "enthusiastic guide highlighting who would enjoy this book and why",
        }

        # Create and return the prompt
        return f"""You are a professional book reviewer for a public library system.

Book Details:
- Title: "{book.title}"
- Author ID: {book.author_id}
- Genre: {book.genre}
- Published: {book.publication_year}
- Total Copies: {book.total_copies}
- ISBN: {book.isbn}

Library Metrics:
- Total Checkouts: {total_checkouts}
- Current Reservations: {current_holds}
- Popularity: {popularity}

Review Requirements:
- Type: {review_type} - Write a {review_context[review_type]}
{f"- Target Audience: {target_audience}" if target_audience else "- General audience review"}
{"- Include 2-3 memorable quotes that capture the book's voice" if include_quotes else ""}

Please write a {review_type} review that:

1. **Opening Hook** (1 paragraph)
   - Capture attention immediately
   - Set the tone for the review
   - Hint at what makes this book special

2. **Core Content** (2-3 paragraphs)
   - For summary: Plot overview without spoilers
   - For critical: Literary analysis and cultural context
   - For recommendation: Reading experience and emotional impact

3. **Writing Style Assessment**
   - Describe the author's voice and technique
   - Note any unique stylistic elements
   - Compare to similar works if relevant

4. **Target Audience**
   {"- Who will love this book and why" if review_type == "recommendation" else "- Readership considerations"}
   {"- Required background knowledge" if review_type == "critical" else "- Accessibility level"}
   {f"- Specific appeal for {target_audience}" if target_audience else ""}

5. **Final Verdict**
   - Star rating (1-5) with justification
   - One-sentence summary
   - {"Call to action for readers" if review_type == "recommendation" else "Lasting impression"}

Additional Notes:
- Mention the {popularity} status based on our circulation data
- Note that we currently have {book.available_copies} copies available
- Write in an engaging, professional tone suitable for library patrons

Length: 400-500 words"""

    finally:
        if should_close:
            session.close()


# Export for server registration
review_generator_prompt = generate_book_review
