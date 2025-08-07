"""Tests for reading plan generator prompt functionality."""

from datetime import date

import pytest

from database.author_repository import AuthorCreateSchema, AuthorRepository
from database.book_repository import BookCreateSchema, BookRepository
from prompts.reading_plan import generate_reading_plan


@pytest.mark.asyncio
async def test_generate_reading_plan_basic(test_db_session):
    """Test basic reading plan generation."""
    result = await generate_reading_plan(goal="Learn Python programming", _session=test_db_session)

    assert isinstance(result, str)
    assert "Python programming" in result
    assert "reading plan" in result.lower()
    assert "Learning Path Overview" in result


@pytest.mark.asyncio
async def test_generate_reading_plan_durations(test_db_session):
    """Test reading plans for different durations."""
    durations = ["week", "month", "quarter", "year"]
    expected_books = [1, 3, 8, 24]

    for duration, book_count in zip(durations, expected_books, strict=False):
        result = await generate_reading_plan(
            goal="Master data science", duration=duration, _session=test_db_session
        )

        assert isinstance(result, str)
        assert f"Duration: {duration}" in result
        assert f"aim for {book_count} books" in result


@pytest.mark.asyncio
async def test_generate_reading_plan_experience_levels(test_db_session):
    """Test plans for different experience levels."""
    levels = ["beginner", "intermediate", "advanced", "expert"]

    for level in levels:
        result = await generate_reading_plan(
            goal="Understand machine learning", experience_level=level, _session=test_db_session
        )

        assert isinstance(result, str)
        assert f"Experience Level: {level}" in result
        if level == "expert":
            assert "progression from expert level to mastery" in result
        else:
            assert f"progression from {level}" in result


@pytest.mark.asyncio
async def test_generate_reading_plan_time_commitments(test_db_session):
    """Test plans for different time commitments."""
    commitments = {"light": 100, "moderate": 250, "intensive": 500}

    for commitment, pages in commitments.items():
        result = await generate_reading_plan(
            goal="Study history", time_commitment=commitment, _session=test_db_session
        )

        assert isinstance(result, str)
        assert f"Time Commitment: {commitment}" in result
        assert f"{pages} pages per week" in result


@pytest.mark.asyncio
async def test_generate_reading_plan_finds_relevant_books(test_db_session):
    """Test that the plan searches for relevant books."""
    # Create a book with relevant title
    author_repo = AuthorRepository(test_db_session)
    book_repo = BookRepository(test_db_session)

    # Create author and book
    author_data = AuthorCreateSchema(
        name="Test Author",
        birth_date=date(1970, 1, 1),
        nationality="American",
        biography="Test bio",
    )
    author = author_repo.create(author_data)

    book_data = BookCreateSchema(
        isbn="9781234567899",
        title="Python Programming Fundamentals",
        author_id=author.id,
        genre="Technology",
        publication_year=2023,
        total_copies=3,
    )
    book_repo.create(book_data)
    test_db_session.commit()

    # Generate plan
    result = await generate_reading_plan(goal="Learn Python", _session=test_db_session)

    # Should find the Python book
    assert "Python Programming Fundamentals" in result


@pytest.mark.asyncio
async def test_generate_reading_plan_structure(test_db_session):
    """Test that reading plan has all required sections."""
    result = await generate_reading_plan(
        goal="Become a better writer", duration="quarter", _session=test_db_session
    )

    # Check all sections are present
    assert "Learning Path Overview" in result
    assert "Book Recommendations" in result
    assert "Reading Schedule" in result
    assert "Supplementary Resources" in result
    assert "Success Metrics" in result

    # Check specific instructions
    assert "key concepts to master" in result
    assert "Week-by-week breakdown" in result
    assert "knowledge checkpoints" in result


@pytest.mark.asyncio
async def test_generate_reading_plan_handles_no_matches(test_db_session):
    """Test plan generation when no matching books found."""
    result = await generate_reading_plan(
        goal="Learn about quantum chromodynamics", _session=test_db_session
    )

    assert isinstance(result, str)
    # Should handle case when no books match
    assert "No directly matching books found" in result or len(result) > 100
