"""
Tests for the Book Insights Tool - Demonstrating Sampling Testing Patterns

This test file shows how to properly test MCP sampling functionality:
1. Mocking sampling responses
2. Testing both success and failure cases
3. Verifying fallback behavior
4. Testing different insight types
"""

from contextlib import contextmanager
from datetime import date
from unittest.mock import AsyncMock, Mock, patch

import pytest
from mcp.types import CreateMessageResult, TextContent

from database.schema import Author
from database.schema import Book as BookDB
from models.book import Book
from tools.book_insights import InsightType, generate_book_insights


@pytest.fixture
def mock_author():
    """Create a mock author for testing."""
    return Author(
        id="author_fitzgerald01",
        name="F. Scott Fitzgerald",
        birth_date=date(1896, 9, 24),
        nationality="American",
        biography="American novelist and short story writer"
    )


@pytest.fixture
def mock_book_db(mock_author):
    """Create a mock database book for testing."""
    book = BookDB(
        isbn="9780134110362",
        title="The Pragmatic Programmer",
        author_id="author_fitzgerald01",
        genre="Technology",
        publication_year=1999,
        description="A classic book on software development best practices",
        available_copies=3,
        total_copies=5,
    )
    # Set the author relationship
    book.author = mock_author
    return book


@pytest.fixture
def mock_context_with_sampling():
    """Create a mock context with sampling capability enabled."""
    context = Mock()
    context.request_context.session.client_capabilities.sampling = True
    return context


@pytest.fixture
def mock_context_without_sampling():
    """Create a mock context with sampling capability disabled."""
    context = Mock()
    context.request_context.session.client_capabilities.sampling = False
    return context


@pytest.fixture
def mock_book_model(mock_book_db):
    """Create a Book model from the database object."""
    return Book(
        isbn=mock_book_db.isbn,
        title=mock_book_db.title,
        author_id=mock_book_db.author_id,
        author_name=mock_book_db.author.name,
        genre=mock_book_db.genre,
        publication_year=mock_book_db.publication_year,
        description=mock_book_db.description,
        available_copies=mock_book_db.available_copies,
        total_copies=mock_book_db.total_copies,
    )


@contextmanager
def mock_repositories(book_model, author_name="F. Scott Fitzgerald"):
    """Helper to mock both book and author repositories."""
    with patch('tools.book_insights.BookRepository') as MockBookRepo, \
         patch('tools.book_insights.AuthorRepository') as MockAuthorRepo:
        # Mock book repository
        mock_book_repo = Mock()
        mock_book_repo.get_by_isbn.return_value = book_model
        MockBookRepo.return_value = mock_book_repo

        # Mock author repository
        mock_author_repo = Mock()
        mock_author = Mock()
        mock_author.name = author_name
        mock_author_repo.get_by_id.return_value = mock_author
        MockAuthorRepo.return_value = mock_author_repo

        yield mock_book_repo, mock_author_repo


@pytest.mark.asyncio
async def test_generate_book_insights_with_sampling_summary(
    mock_context_with_sampling, mock_book_model
):
    """Test generating a book summary using sampling."""

    # Mock the sampling response
    mock_response = CreateMessageResult(
        role="assistant",
        content=TextContent(
            type="text",
            text="This seminal work by Andrew Hunt and David Thomas revolutionizes how developers approach their craft. Through practical wisdom and timeless principles, the authors guide readers toward becoming more effective programmers. The book covers essential topics from personal responsibility to architectural decisions, making it invaluable for developers at any stage of their career."
        ),
        model="claude-3-sonnet",
        stop_reason="end_turn"
    )

    # Mock the create_message method
    mock_context_with_sampling.request_context.session.create_message = AsyncMock(
        return_value=mock_response
    )

    # Act: Generate insights with mocked repositories
    with mock_repositories(mock_book_model):
        result = await generate_book_insights(
            context=mock_context_with_sampling,
            isbn="9780134110362",
            insight_type="summary"
        )

    # Assert: Check the result
    assert "AI-Generated Summary" in result
    assert "The Pragmatic Programmer" in result
    assert "seminal work" in result
    assert "Andrew Hunt and David Thomas" in result

    # Verify the sampling method was called
    mock_context_with_sampling.request_context.session.create_message.assert_called_once()

    # Verify the request parameters
    call_args = mock_context_with_sampling.request_context.session.create_message.call_args[0][0]
    assert len(call_args.messages) == 1
    assert call_args.messages[0].role == "user"
    assert "The Pragmatic Programmer" in call_args.messages[0].content.text
    assert call_args.maxTokens == 400


@pytest.mark.asyncio
async def test_generate_book_insights_without_sampling(
    mock_context_without_sampling, mock_book_model
):
    """Test fallback behavior when sampling is not available."""
    # Act: Generate insights without sampling
    with mock_repositories(mock_book_model):
        result = await generate_book_insights(
            context=mock_context_without_sampling,
            isbn="9780134110362",
            insight_type="summary"
        )

    # Assert: Check fallback response
    assert "Book Information" in result
    assert "The Pragmatic Programmer" in result
    assert "Technology" in result
    assert "A classic book on software development best practices" in result
    assert "AI-generated summaries require a client with sampling support" not in result  # Has description


@pytest.mark.asyncio
async def test_generate_book_insights_themes(
    mock_context_with_sampling, mock_book_model
):
    """Test generating theme analysis using sampling."""

    mock_response = CreateMessageResult(
        role="assistant",
        content=TextContent(
            type="text",
            text="""1. **Craftsmanship and Professionalism**: The book emphasizes treating programming as a craft, encouraging developers to take pride in their work and continuously improve their skills.

2. **Pragmatic Problem Solving**: Focus on practical solutions rather than theoretical perfection, choosing the right tool for the job.

3. **Continuous Learning**: The importance of staying current with technology while understanding timeless principles.

4. **Communication and Teamwork**: How effective communication is as important as technical skills in software development.

5. **Software Entropy**: The concept of technical debt and how to prevent code decay through refactoring and maintenance."""
        ),
        model="claude-3-sonnet",
        stop_reason="end_turn"
    )

    mock_context_with_sampling.request_context.session.create_message = AsyncMock(
        return_value=mock_response
    )

    # Act
    with mock_repositories(mock_book_model):
        result = await generate_book_insights(
            context=mock_context_with_sampling,
            isbn="9780134110362",
            insight_type="themes"
        )

    # Assert
    assert "AI-Generated Themes" in result
    assert "Craftsmanship and Professionalism" in result
    assert "Software Entropy" in result


@pytest.mark.asyncio
async def test_generate_book_insights_sampling_failure(
    mock_context_with_sampling, mock_book_model
):
    """Test handling of sampling failures."""

    # Mock a sampling failure
    mock_context_with_sampling.request_context.session.create_message = AsyncMock(
        side_effect=Exception("Sampling request failed: User rejected")
    )

    # Act
    with mock_repositories(mock_book_model):
        result = await generate_book_insights(
            context=mock_context_with_sampling,
            isbn="9780134110362",
            insight_type="summary"
        )

    # Assert: Should fall back gracefully
    assert "Book Information" in result
    assert "The Pragmatic Programmer" in result
    # Should show the existing description since sampling failed
    assert "A classic book on software development best practices" in result


@pytest.mark.asyncio
async def test_generate_book_insights_invalid_isbn(
    mock_context_with_sampling
):
    """Test handling of invalid ISBN."""
    # Act
    with mock_repositories(None):  # Return None for invalid ISBN
        result = await generate_book_insights(
            context=mock_context_with_sampling,
            isbn="invalid-isbn",
            insight_type="summary"
        )

    # Assert
    assert "Error: Book with ISBN invalid-isbn not found" in result


@pytest.mark.asyncio
async def test_all_insight_types(
    mock_context_without_sampling, mock_book_model
):
    """Test all insight types work with fallback responses."""

    insight_types: list[InsightType] = ["summary", "themes", "discussion_questions", "similar_books"]

    for insight_type in insight_types:
        # Act
        with mock_repositories(mock_book_model):
            result = await generate_book_insights(
                context=mock_context_without_sampling,
                isbn="9780134110362",
                insight_type=insight_type
            )

        # Assert
        assert "Book Information" in result
        assert "The Pragmatic Programmer" in result

        # Check specific content for each type
        if insight_type == "themes":
            assert "Genre-Typical Themes" in result
        elif insight_type == "discussion_questions":
            assert "Generic Discussion Questions" in result
        elif insight_type == "similar_books":
            assert "Finding Similar Books" in result


@pytest.mark.asyncio
async def test_sampling_request_parameters(
    mock_context_with_sampling, mock_book_model
):
    """Test that sampling requests use appropriate parameters for different insight types."""

    mock_response = CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text="Mock response"),
        model="claude-3-sonnet",
        stop_reason="end_turn"
    )

    mock_create_message = AsyncMock(return_value=mock_response)
    mock_context_with_sampling.request_context.session.create_message = mock_create_message

    # Test different insight types and their parameters
    test_cases = [
        ("summary", 400, 0.7, 0.8, 0.4),
        ("themes", 500, 0.6, 0.9, 0.3),
        ("discussion_questions", 600, 0.8, 0.7, 0.5),
        ("similar_books", 700, 0.8, 0.7, 0.6),
    ]

    for insight_type, expected_tokens, expected_temp, expected_intel, expected_speed in test_cases:
        # Reset mock
        mock_create_message.reset_mock()

        # Act
        with mock_repositories(mock_book_model):
            await generate_book_insights(
                context=mock_context_with_sampling,
                isbn="9780134110362",
                insight_type=insight_type
            )

        # Assert
        call_args = mock_create_message.call_args[0][0]
        assert call_args.maxTokens == expected_tokens
        assert call_args.temperature == expected_temp
        assert call_args.modelPreferences.intelligence_priority == expected_intel
        assert call_args.modelPreferences.speed_priority == expected_speed
