"""Membership Tool - Interactive Renewal via Elicitation

The clearest demonstration of MCP elicitation (2025-11-25): the tool is
called with just a patron ID, then asks the USER — through the client —
which renewal term to apply. Shows:

- Enum elicitation: response_type=Literal[...] renders as a select list
  (SEP-1330 standardized enum schemas in the 2025-11-25 revision)
- The accept / decline / cancel action triple
- A declined elicitation as a normal outcome, not an error
"""

import logging
from datetime import date, datetime, timedelta
from typing import Annotated, Literal, cast

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

from database.patron_repository import PatronRepository, PatronUpdateSchema
from database.session import get_session
from models.patron import PatronStatus

logger = logging.getLogger(__name__)

RenewalTerm = Literal["6 months", "12 months", "24 months"]
TERM_DAYS = {"6 months": 182, "12 months": 365, "24 months": 730}


class RenewalResult(BaseModel):
    """Structured outcome of a renewal attempt."""

    patron_id: str
    patron_name: str
    renewed: bool
    term: str | None = None
    previous_expiration: str | None = None
    new_expiration: str | None = None
    status: str
    message: str


async def renew_membership(
    patron_id: Annotated[
        str,
        Field(
            description="Patron identifier, e.g. 'patron_00042'",
            pattern=r"^patron_[a-zA-Z0-9_]{5,}$",
        ),
    ],
    ctx: Context,
) -> RenewalResult:
    """Renew a patron's library membership interactively.

    The renewal term is not a tool argument by design: the server elicits
    it from the user mid-execution, demonstrating how MCP tools can gather
    input progressively instead of requiring everything upfront.
    """
    with get_session() as session:
        patron = PatronRepository(session).get_by_id(patron_id)
    if patron is None:
        raise ToolError(f"Patron {patron_id} not found.")

    current_expiration = patron.expiration_date

    try:
        answer = await ctx.elicit(
            f"Renew membership for {patron.name} "
            f"(current expiration: {current_expiration or 'none on file'}). "
            "Which term should be applied?",
            response_type=RenewalTerm,
        )
    except Exception as e:
        # No elicitation capability on this client: the term genuinely
        # cannot be collected, so surface a actionable tool error.
        raise ToolError(
            "This client does not support elicitation; call the tool from a "
            "client that does, or update the patron's expiration directly."
        ) from e

    if answer.action != "accept":
        logger.info("Renewal %s by user for %s", answer.action, patron_id)
        return RenewalResult(
            patron_id=patron_id,
            patron_name=patron.name,
            renewed=False,
            status=str(patron.status),
            message=f"Renewal {answer.action}ed by the user — no changes made.",
        )

    term = cast("RenewalTerm", answer.data)
    today = datetime.now().date()
    base: date = max(current_expiration, today) if current_expiration else today
    new_expiration = base + timedelta(days=TERM_DAYS[term])

    update_fields: dict = {"expiration_date": new_expiration}
    if patron.status == PatronStatus.EXPIRED:
        # A lapsed membership becomes active again upon renewal.
        update_fields["status"] = PatronStatus.ACTIVE
    with get_session() as session:
        repo = PatronRepository(session)
        updated = repo.update(patron_id, PatronUpdateSchema(**update_fields))

    message = (
        f"Renewed {updated.name}'s membership for {term}: now expires {new_expiration.isoformat()}."
    )
    logger.info("renew_membership_success | patron=%s term=%s", patron_id, term)
    return RenewalResult(
        patron_id=patron_id,
        patron_name=updated.name,
        renewed=True,
        term=term,
        previous_expiration=current_expiration.isoformat() if current_expiration else None,
        new_expiration=new_expiration.isoformat(),
        status=str(updated.status),
        message=message,
    )
