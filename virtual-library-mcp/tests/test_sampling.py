"""Unit tests for the sampling helper module.

request_ai_generation is a thin layer over ctx.sample(); these tests use a
duck-typed context stub so they need neither a database nor a client.
The full protocol round-trip is covered in tests/tools/test_book_insights.py.
"""

import pytest

from sampling import DEFAULT_MODEL_PREFERENCES, request_ai_generation


class _SampleResult:
    def __init__(self, text):
        self.text = text


class _StubContext:
    """Just enough of fastmcp.Context for request_ai_generation."""

    def __init__(self, text="generated text", error: Exception | None = None):
        self._text = text
        self._error = error
        self.calls: list[dict] = []

    async def sample(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return _SampleResult(self._text)


class TestRequestAiGeneration:
    async def test_returns_generated_text(self):
        ctx = _StubContext(text="Here is your summary.")
        result = await request_ai_generation(ctx, "Summarize this book")
        assert result == "Here is your summary."

    async def test_passes_through_parameters(self):
        ctx = _StubContext()
        await request_ai_generation(
            ctx,
            "prompt",
            system_prompt="be a librarian",
            max_tokens=123,
            temperature=0.2,
        )
        call = ctx.calls[0]
        assert call["messages"] == "prompt"
        assert call["system_prompt"] == "be a librarian"
        assert call["max_tokens"] == 123
        assert call["temperature"] == 0.2

    async def test_default_model_preferences_applied(self):
        ctx = _StubContext()
        await request_ai_generation(ctx, "prompt")
        assert ctx.calls[0]["model_preferences"] == DEFAULT_MODEL_PREFERENCES

    async def test_custom_model_preferences_override_default(self):
        ctx = _StubContext()
        await request_ai_generation(ctx, "prompt", model_preferences=["gpt-x"])
        assert ctx.calls[0]["model_preferences"] == ["gpt-x"]

    async def test_failure_returns_none_not_exception(self):
        ctx = _StubContext(error=RuntimeError("client lacks sampling capability"))
        result = await request_ai_generation(ctx, "prompt")
        assert result is None

    async def test_empty_response_returns_none(self):
        ctx = _StubContext(text="")
        result = await request_ai_generation(ctx, "prompt")
        assert result is None

    @pytest.mark.parametrize("max_tokens", [1, 500, 4000])
    async def test_token_limits_forwarded(self, max_tokens):
        ctx = _StubContext()
        await request_ai_generation(ctx, "prompt", max_tokens=max_tokens)
        assert ctx.calls[0]["max_tokens"] == max_tokens
