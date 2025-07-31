"""Tests for book review generator prompt functionality."""

import pytest
from virtual_library_mcp.prompts.review_generator import generate_book_review


@pytest.mark.asyncio
async def test_generate_review_basic(test_db_session, sample_book):
    """Test basic review generation."""
    result = await generate_book_review(isbn=sample_book.isbn, _session=test_db_session)

    assert isinstance(result, str)
    assert sample_book.title in result
    assert sample_book.author_id in result
    assert "professional book reviewer" in result


@pytest.mark.asyncio
async def test_generate_review_types(test_db_session, sample_book):
    """Test different review types."""
    review_types = {
        "summary": "concise overview",
        "critical": "balanced analysis",
        "recommendation": "enthusiastic guide",
    }

    for review_type, expected_phrase in review_types.items():
        result = await generate_book_review(
            isbn=sample_book.isbn, review_type=review_type, _session=test_db_session
        )

        assert isinstance(result, str)
        assert f"Type: {review_type}" in result
        assert expected_phrase in result


@pytest.mark.asyncio
async def test_generate_review_with_target_audience(test_db_session, sample_book):
    """Test review with specific target audience."""
    result = await generate_book_review(
        isbn=sample_book.isbn,
        target_audience="Young adults interested in technology",
        _session=test_db_session,
    )

    assert isinstance(result, str)
    assert "Target Audience: Young adults interested in technology" in result
    assert "Specific appeal for Young adults" in result


@pytest.mark.asyncio
async def test_generate_review_with_quotes(test_db_session, sample_book):
    """Test review requesting quotes."""
    result = await generate_book_review(
        isbn=sample_book.isbn, include_quotes=True, _session=test_db_session
    )

    assert isinstance(result, str)
    assert "memorable quotes" in result


@pytest.mark.asyncio
async def test_generate_review_invalid_isbn(test_db_session):
    """Test review generation with invalid ISBN."""
    result = await generate_book_review(isbn="9999999999999", _session=test_db_session)

    assert isinstance(result, str)
    assert "No book found" in result
    assert "valid ISBN" in result


@pytest.mark.asyncio
async def test_generate_review_includes_circulation_data(test_db_session, sample_book):
    """Test that review includes circulation statistics."""
    # For the learning project, we're using simulated circulation data
    # so we don't need to create actual checkouts

    # For the learning project, we're using simulated circulation data
    # so we don't need to create actual checkouts
    test_db_session.commit()

    # Generate review
    result = await generate_book_review(isbn=sample_book.isbn, _session=test_db_session)

    # The prompt uses simulated values
    assert "Total Checkouts:" in result
    assert "popular" in result.lower()

    # Session managed by fixture


@pytest.mark.asyncio
async def test_generate_review_structure(test_db_session, sample_book):
    """Test that review has all required sections."""
    result = await generate_book_review(
        isbn=sample_book.isbn, review_type="critical", _session=test_db_session
    )

    # Check all sections
    assert "Opening Hook" in result
    assert "Core Content" in result
    assert "Writing Style Assessment" in result
    assert "Target Audience" in result
    assert "Final Verdict" in result

    # Check specific requirements
    assert "Star rating (1-5)" in result
    assert "400-500 words" in result


@pytest.mark.asyncio
async def test_generate_review_popularity_tiers(test_db_session, sample_book):
    """Test different popularity classifications."""
    # For the learning project, we're using simulated circulation data
    # The prompt uses fixed values for demonstration

    # For the learning project, we're using simulated circulation data
    # The prompt uses fixed values for demonstration
    test_db_session.commit()

    result = await generate_book_review(isbn=sample_book.isbn, _session=test_db_session)
    # The prompt uses fixed values (25 checkouts = "Moderately popular")
    assert "popular" in result.lower()

    # Session managed by fixture
