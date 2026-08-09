"""Privacy-conscious patron discovery for circulation workflows."""

import logging
import re
from typing import Annotated

from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

from database.patron_repository import PatronRepository, PatronSearchParams
from database.repository import PaginationParams
from database.session import session_scope

logger = logging.getLogger(__name__)


class PatronMatch(BaseModel):
    """A minimal patron identity result safe for conversational disambiguation."""

    patron_id: str
    name: str
    email_hint: str
    phone_hint: str | None
    membership_status: str
    expiration_date: str | None
    current_checkouts: int
    borrowing_limit: int
    outstanding_fines: float
    can_checkout: bool
    preferred_genres: list[str]


class PatronSearchResponse(BaseModel):
    """Structured result for find_patron."""

    summary: str
    patrons: list[PatronMatch]
    total_matches: int


def mask_email(email: str) -> str:
    """Keep enough of a synthetic email to disambiguate without returning it whole."""
    local, separator, domain = email.partition("@")
    if not separator:
        return "•••"
    visible = local[:1]
    return f"{visible}{'•' * max(3, len(local) - 1)}@{domain}"


def mask_phone(phone: str | None) -> str | None:
    """Return only the last four digits of a phone number."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    return f"•••-•••-{digits[-4:]}" if len(digits) >= 4 else "•••"


async def find_patron(
    query: Annotated[
        str,
        Field(
            min_length=2,
            max_length=120,
            description="Patron name, email address, or phone digits; no patron number required",
        ),
    ],
    limit: Annotated[
        int,
        Field(ge=1, le=10, description="Maximum candidate accounts to return"),
    ] = 5,
) -> PatronSearchResponse:
    """Find a patron by familiar details before a circulation action.

    Use this when the patron does not know their internal patron number. Results
    intentionally mask contact details and omit addresses; use the returned
    patron_id with checkout, reservation, renewal, and history operations.
    """
    normalized_query = query.strip()
    if len(normalized_query) < 2:
        raise ToolError("Enter at least two non-space characters to find a patron.")
    phone_digits = re.sub(r"\D", "", normalized_query)
    if len(phone_digits) >= 4 and not any(char.isalpha() for char in normalized_query):
        normalized_query = phone_digits

    try:
        with session_scope() as session:
            result = PatronRepository(session).search(
                search_params=PatronSearchParams(query=normalized_query),
                pagination=PaginationParams(page=1, page_size=limit),
            )

        patrons = [
            PatronMatch(
                patron_id=patron.id,
                name=patron.name,
                email_hint=mask_email(patron.email),
                phone_hint=mask_phone(patron.phone),
                membership_status=str(getattr(patron.status, "value", patron.status)),
                expiration_date=(
                    patron.expiration_date.isoformat() if patron.expiration_date else None
                ),
                current_checkouts=patron.current_checkouts,
                borrowing_limit=patron.borrowing_limit,
                outstanding_fines=round(patron.outstanding_fines, 2),
                can_checkout=patron.can_checkout,
                preferred_genres=patron.preferred_genres,
            )
            for patron in result.items
        ]
        if patrons:
            summary = (
                f"Found {result.total} matching patron account(s). "
                "Use the masked contact hint to confirm the right person."
            )
        else:
            summary = (
                "No patron account matched that name or contact detail. "
                "Try a full name, email address, or phone digits."
            )
        return PatronSearchResponse(
            summary=summary,
            patrons=patrons,
            total_matches=result.total,
        )
    except ToolError:
        raise
    except Exception as exc:
        logger.exception("Patron account search failed")
        raise ToolError("Unable to search patron accounts right now.") from exc


__all__ = [
    "PatronMatch",
    "PatronSearchResponse",
    "find_patron",
    "mask_email",
    "mask_phone",
]
