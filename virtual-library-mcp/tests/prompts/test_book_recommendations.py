"""Tests for book recommendation prompt functionality."""

import pytest

from src.prompts.book_recommendations import recommend_books


@pytest.mark.asyncio
async def test_recommend_books_basic(test_db_session, sample_books):
    """Test basic book recommendation without filters."""
    # Call the prompt function
    result = await recommend_books(_session=test_db_session)

    # Verify we get a string response
    assert isinstance(result, str)
    assert len(result) > 0

    # Check for expected content
    assert "knowledgeable librarian" in result
    assert "recommend" in result.lower()
    assert "catalog" in result


@pytest.mark.asyncio
async def test_recommend_books_with_genre(test_db_session):
    """Test book recommendation with genre filter."""
    result = await recommend_books(genre="Science Fiction", _session=test_db_session)

    assert isinstance(result, str)
    assert "Science Fiction" in result
    assert "Genre preference: Science Fiction" in result


@pytest.mark.asyncio
async def test_recommend_books_with_mood(test_db_session):
    """Test book recommendation with mood parameter."""
    result = await recommend_books(mood="adventurous", _session=test_db_session)

    assert isinstance(result, str)
    assert "adventurous" in result
    assert "Current mood: adventurous" in result


@pytest.mark.asyncio
async def test_recommend_books_with_limit(test_db_session):
    """Test book recommendation with custom limit."""
    result = await recommend_books(limit=3, _session=test_db_session)

    assert isinstance(result, str)
    assert "recommend 3 books" in result


@pytest.mark.asyncio
async def test_recommend_books_with_patron(test_db_session, sample_patron):
    """Test personalized recommendations with patron history."""
    # For simplicity in this test, we just verify patron info is included
    # Actual borrowing history would require more complex setup
    test_db_session.commit()

    # Now test recommendations with patron context
    result = await recommend_books(patron_id=sample_patron.id, _session=test_db_session)

    assert isinstance(result, str)
    assert "Recommending for patron" in result
    assert sample_patron.name in result


@pytest.mark.asyncio
async def test_recommend_books_all_parameters(test_db_session, sample_patron):
    """Test recommendation with all parameters."""
    result = await recommend_books(
        genre="Mystery",
        mood="contemplative",
        patron_id=sample_patron.id,
        limit=10,
        _session=test_db_session,
    )

    assert isinstance(result, str)
    assert "Mystery" in result
    assert "contemplative" in result
    assert "recommend 10 books" in result


@pytest.mark.asyncio
async def test_recommend_books_formats_book_list(test_db_session, sample_books):
    """Test that available books are properly formatted."""
    result = await recommend_books(
        _session=test_db_session,
    )

    # Should include book details if books are available
    if sample_books:  # Only check if we have books
        assert "Available" in result or "Checked out" in result  # Status
        assert "(" in result  # Publication info
        assert ")" in result


@pytest.mark.asyncio
async def test_recommend_books_includes_instructions(test_db_session):
    """Test that recommendation instructions are included."""
    result = await recommend_books(
        _session=test_db_session,
    )

    # Check for recommendation guidelines
    assert "Match the patron's preferences" in result
    assert "mix of popular and lesser-known" in result
    assert "explain why each book" in result
    assert "availability status" in result
    assert "numbered list" in result
