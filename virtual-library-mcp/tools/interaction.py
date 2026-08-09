"""Bounded client-interaction helpers shared by mutating tools."""

import asyncio
from typing import Any

from config import get_config
from modern.context import ModernContext


class ElicitationUnavailableError(RuntimeError):
    """The current transport cannot complete a legacy elicitation promptly."""


async def elicit_with_timeout(
    ctx: Any,
    message: str,
    response_type: Any,
    *,
    response_title: str | None = None,
    response_description: str | None = None,
) -> Any:
    """Elicit input without letting hosted legacy calls wedge indefinitely.

    The modern 2026-07-28 context converts this call into MRTR immediately, so
    it must not be wrapped in a local timeout. The legacy hosted path is
    intentionally stateless and therefore cannot carry a server-initiated
    request; fail fast so the model can collect the answer and retry with an
    explicit tool argument instead.
    """
    if isinstance(ctx, ModernContext):
        return await ctx.elicit(
            message,
            response_type=response_type,
            response_title=response_title,
            response_description=response_description,
        )

    config = get_config()
    if config.transport in {"http", "streamable_http"} and config.http_stateless:
        raise ElicitationUnavailableError(
            "Stateless HTTP cannot complete server-initiated elicitation."
        )

    try:
        return await asyncio.wait_for(
            ctx.elicit(
                message,
                response_type=response_type,
                response_title=response_title,
                response_description=response_description,
            ),
            timeout=config.elicitation_timeout_seconds,
        )
    except TimeoutError as exc:
        raise ElicitationUnavailableError(
            "The client did not answer elicitation within "
            f"{config.elicitation_timeout_seconds:g} seconds."
        ) from exc
