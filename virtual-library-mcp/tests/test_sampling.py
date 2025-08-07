"""
Direct tests for the sampling module - Educational Testing Example

These tests demonstrate how to test MCP sampling functionality
without complex database dependencies.
"""

from unittest.mock import AsyncMock, Mock

import pytest
from mcp.types import CreateMessageResult, TextContent

from sampling import generate_book_summary, generate_reading_recommendation, request_ai_generation


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


@pytest.mark.asyncio
async def test_request_ai_generation_success(mock_context_with_sampling):
    """Test successful AI generation request."""
    # Mock the sampling response
    mock_response = CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text="This is the generated AI response."),
        model="claude-3-sonnet",
        stop_reason="end_turn",
    )

    # Mock the create_message method
    mock_context_with_sampling.request_context.session.create_message = AsyncMock(
        return_value=mock_response
    )

    # Act
    result = await request_ai_generation(
        context=mock_context_with_sampling,
        prompt="Generate something interesting",
        system_prompt="You are a helpful assistant",
        max_tokens=100,
        temperature=0.7,
    )

    # Assert
    assert result == "This is the generated AI response."
    mock_context_with_sampling.request_context.session.create_message.assert_called_once()

    # Verify request parameters
    call_args = mock_context_with_sampling.request_context.session.create_message.call_args[0][0]
    assert len(call_args.messages) == 1
    assert call_args.messages[0].role == "user"
    assert call_args.messages[0].content.text == "Generate something interesting"
    assert call_args.systemPrompt == "You are a helpful assistant"
    assert call_args.maxTokens == 100
    assert call_args.temperature == 0.7


@pytest.mark.asyncio
async def test_request_ai_generation_no_sampling_capability(mock_context_without_sampling):
    """Test behavior when client doesn't support sampling."""
    # Act
    result = await request_ai_generation(
        context=mock_context_without_sampling,
        prompt="Generate something",
    )

    # Assert
    assert result is None


@pytest.mark.asyncio
async def test_request_ai_generation_failure(mock_context_with_sampling):
    """Test handling of sampling failures."""
    # Mock a sampling failure
    mock_context_with_sampling.request_context.session.create_message = AsyncMock(
        side_effect=Exception("Sampling failed: User rejected")
    )

    # Act
    result = await request_ai_generation(
        context=mock_context_with_sampling,
        prompt="Generate something",
    )

    # Assert
    assert result is None


@pytest.mark.asyncio
async def test_generate_book_summary(mock_context_with_sampling):
    """Test the book summary generation helper."""
    # Mock response
    mock_response = CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text="A compelling tale of adventure and discovery..."),
        model="claude-3-sonnet",
        stop_reason="end_turn",
    )

    mock_context_with_sampling.request_context.session.create_message = AsyncMock(
        return_value=mock_response
    )

    # Act
    result = await generate_book_summary(
        context=mock_context_with_sampling,
        book_title="The Adventure",
        author="Jane Doe",
        genre="Fiction",
        year=2023,
    )

    # Assert
    assert result == "A compelling tale of adventure and discovery..."

    # Verify the prompt includes book details
    call_args = mock_context_with_sampling.request_context.session.create_message.call_args[0][0]
    prompt_text = call_args.messages[0].content.text
    assert "The Adventure" in prompt_text
    assert "Jane Doe" in prompt_text
    assert "Fiction" in prompt_text
    assert "2023" in prompt_text


@pytest.mark.asyncio
async def test_generate_reading_recommendation(mock_context_with_sampling):
    """Test the reading recommendation generation helper."""
    # Mock response
    mock_response = CreateMessageResult(
        role="assistant",
        content=TextContent(
            type="text", text="Based on your love of mystery novels, I recommend..."
        ),
        model="claude-3-sonnet",
        stop_reason="end_turn",
    )

    mock_context_with_sampling.request_context.session.create_message = AsyncMock(
        return_value=mock_response
    )

    # Act
    result = await generate_reading_recommendation(
        context=mock_context_with_sampling,
        patron_name="John Smith",
        favorite_genres=["Mystery", "Thriller"],
        recent_books=["Gone Girl", "The Silent Patient"],
        reading_level="adult",
    )

    # Assert
    assert "Based on your love of mystery novels" in result

    # Verify the prompt includes patron details
    call_args = mock_context_with_sampling.request_context.session.create_message.call_args[0][0]
    prompt_text = call_args.messages[0].content.text
    assert "John Smith" in prompt_text
    assert "Mystery, Thriller" in prompt_text
    assert "Gone Girl" in prompt_text


@pytest.mark.asyncio
async def test_model_preferences():
    """Test that model preferences are set correctly."""
    context = Mock()
    context.request_context.session.client_capabilities.sampling = True

    mock_response = CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text="Response"),
        model="claude-3-sonnet",
        stop_reason="end_turn",
    )

    context.request_context.session.create_message = AsyncMock(return_value=mock_response)

    # Act with custom priorities
    await request_ai_generation(
        context=context, prompt="Test", intelligence_priority=0.9, speed_priority=0.2
    )

    # Assert model preferences
    call_args = context.request_context.session.create_message.call_args[0][0]
    prefs = call_args.modelPreferences
    assert prefs.intelligence_priority == 0.9
    assert prefs.speed_priority == 0.2
    # Cost priority should be calculated
    assert prefs.cost_priority == 1.0 - (0.9 + 0.2) / 2
