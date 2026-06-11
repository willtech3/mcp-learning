"""
Educational MCP Sampling Module for the Virtual Library Server

Sampling reverses the usual MCP flow: the SERVER asks the CLIENT to run an
LLM completion (`sampling/createMessage`). The client controls model choice,
applies human-in-the-loop approval, and pays for tokens — the server just
describes what it wants:

1. The server sends messages + model *preferences* (hints and priorities),
   never a hard model requirement.
2. The client may show the request to the user, pick any model, and return
   the completion (or refuse).
3. As of MCP 2025-11-25 (SEP-1577), sampling requests can also carry TOOLS
   the client-side LLM may call mid-completion — see
   tools/book_insights.py for a working example.

FastMCP 3 wraps all of this in ``ctx.sample()``; this module adds the
library's defaults, logging, and graceful degradation for clients that
don't support sampling at all.
"""

import logging

from fastmcp import Context

from observability import logfire
from observability.metrics import ai_generation_requests, ai_generation_tokens

logger = logging.getLogger(__name__)

# Model preferences are HINTS, not commands: the client maps them to the
# closest model it actually has. Order expresses preference.
DEFAULT_MODEL_PREFERENCES = ["claude-opus-4-8", "claude"]


async def request_ai_generation(
    ctx: Context,
    prompt: str,
    system_prompt: str | None = None,
    max_tokens: int = 500,
    temperature: float = 0.7,
    model_preferences: list[str] | None = None,
) -> str | None:
    """Request an LLM completion from the client, returning text or None.

    Returns None when the client lacks the sampling capability or the
    request fails — callers are expected to degrade gracefully rather
    than surface a protocol error to the user.
    """
    with logfire.span(
        "ai.sampling.request",
        ai_max_tokens=max_tokens,
        ai_temperature=temperature,
    ) as span:
        try:
            ai_generation_requests.add(1, {"status": "requested"})
            result = await ctx.sample(
                messages=prompt,
                system_prompt=system_prompt,
                model_preferences=model_preferences or DEFAULT_MODEL_PREFERENCES,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            # Most commonly: the connected client never declared the
            # sampling capability. Treat as "unavailable", not fatal.
            logger.info("Sampling unavailable or failed: %s", e)
            span.set_attribute("ai.fallback", "unavailable")
            ai_generation_requests.add(1, {"status": "failed"})
            return None

        text = result.text
        if not text:
            logger.warning("Sampling returned no text content")
            return None

        estimated_tokens = len(text.split()) * 1.3  # rough estimate
        ai_generation_tokens.record(estimated_tokens)
        span.set_attribute("ai.response_length", len(text))
        logger.info("Sampling succeeded: %d characters generated", len(text))
        return text
