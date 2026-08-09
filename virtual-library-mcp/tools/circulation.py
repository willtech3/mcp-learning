"""Circulation Tools - Library Transaction Management

Modifies library state through checkout, return, and reservation operations.

MCP concepts demonstrated:
- Typed parameters -> rich input schemas (the LLM sees real field names,
  patterns, and constraints instead of an opaque object).
- Structured output via Pydantic return models (outputSchema +
  structuredContent on every call).
- Elicitation (MCP 2025-11-25): checkout_book pauses mid-execution to ask
  the user for confirmation when the patron carries outstanding fines —
  a server-initiated request that flows through the client to a human.
- Tool execution errors (SEP-1303): business-rule violations raise
  ToolError so the model can recover, instead of opaque protocol errors.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

from database.circulation_repository import (
    CheckoutCreateSchema,
    CirculationRepository,
    ReservationCreateSchema,
    ReturnProcessSchema,
)
from database.patron_repository import PatronRepository
from database.repository import NotFoundError, RepositoryException
from database.session import get_session

from .interaction import ElicitationUnavailableError, elicit_with_timeout

logger = logging.getLogger(__name__)

PATRON_ID_FIELD = Field(
    description="Patron identifier, e.g. 'patron_00042'",
    pattern=r"^patron_[a-zA-Z0-9_]{5,}$",
)
ISBN_FIELD = Field(description="ISBN-13 of the book (13 digits)", pattern=r"^\d{13}$")


def _log_operation(operation: str, **kwargs) -> None:
    """Audit-trail logging for every state-changing operation."""
    logger.info(
        "Operation: %s | Details: %s", operation, " | ".join(f"{k}={v}" for k, v in kwargs.items())
    )


# ---------------------------------------------------------------------------
# Structured output models — these become each tool's outputSchema
# ---------------------------------------------------------------------------


class CheckoutResult(BaseModel):
    """Confirmation details for a successful checkout."""

    checkout_id: str
    patron_id: str
    book_isbn: str
    checkout_date: str
    due_date: str
    status: str
    loan_period_days: int
    replayed: bool = False
    message: str


class ReturnResult(BaseModel):
    """Confirmation details for a processed return, including fines."""

    return_id: str
    checkout_id: str
    book_isbn: str
    return_date: str
    condition: str
    late_days: int
    fine_assessed: float
    fine_outstanding: float
    replayed: bool = False
    message: str


class ReservationResult(BaseModel):
    """Confirmation details for a reservation, including queue status."""

    reservation_id: str
    patron_id: str
    book_isbn: str
    reservation_date: str
    expiration_date: str
    status: str
    queue_position: int
    estimated_wait_days: int | None
    total_in_queue: int
    replayed: bool = False
    message: str


def _checkout_result(checkout, *, replayed: bool) -> CheckoutResult:
    if replayed:
        message = (
            f"This checkout was already completed as {checkout.id}; no second loan "
            f"was created. '{checkout.book_isbn}' is due "
            f"{checkout.due_date.strftime('%B %d, %Y')}."
        )
    else:
        message = (
            f"Checked out '{checkout.book_isbn}' to {checkout.patron_id}. "
            f"Due {checkout.due_date.strftime('%B %d, %Y')} "
            f"({checkout.loan_period_days}-day loan)."
        )
    return CheckoutResult(
        checkout_id=checkout.id,
        patron_id=checkout.patron_id,
        book_isbn=checkout.book_isbn,
        checkout_date=checkout.checkout_date.isoformat(),
        due_date=checkout.due_date.isoformat(),
        status=str(checkout.status),
        loan_period_days=checkout.loan_period_days,
        replayed=replayed,
        message=message,
    )


# ---------------------------------------------------------------------------
# checkout_book — demonstrates elicitation (server-initiated user input)
# ---------------------------------------------------------------------------


async def checkout_book(
    patron_id: Annotated[str, PATRON_ID_FIELD],
    book_isbn: Annotated[str, ISBN_FIELD],
    ctx: Context,
    fines_acknowledged: Annotated[
        bool,
        Field(
            description=(
                "Set true only after the user explicitly agrees to proceed despite "
                "the patron's outstanding fines. Leave false for the normal flow."
            )
        ),
    ] = False,
    due_date: Annotated[
        date | None,
        Field(description="Custom due date (defaults to a 14-day loan)"),
    ] = None,
    notes: Annotated[
        str | None,
        Field(description="Optional notes, e.g. 'Book club selection'", max_length=500),
    ] = None,
) -> CheckoutResult:
    """Complete a checkout only after the user explicitly asks to borrow the book.

    Validates patron eligibility and book availability, creates the loan
    record, and updates availability. If the patron has outstanding fines,
    the user is asked to confirm before proceeding (elicitation).

    Do not use this tool for questions such as "Can I check this out?" Use
    ``checkout_readiness_app`` for those read-only eligibility questions.
    """
    if due_date is not None and due_date < datetime.now().date():
        raise ToolError("Due date cannot be in the past.")

    _log_operation("checkout_book_start", patron_id=patron_id, book_isbn=book_isbn)

    # ELICITATION (MCP 2025-11-25): when a patron carries fines but is still
    # allowed to borrow, defer the judgment call to the human. The request
    # travels server -> client -> user and execution pauses for the answer.
    with get_session() as session:
        patron = PatronRepository(session).get_by_id(patron_id)
        existing_checkout = CirculationRepository(session).get_active_checkout_for_book(
            patron_id, book_isbn
        )
    if existing_checkout is not None:
        _log_operation(
            "checkout_book_reconciled",
            checkout_id=existing_checkout.id,
            patron_id=patron_id,
            book_isbn=book_isbn,
        )
        return _checkout_result(existing_checkout, replayed=True)

    if patron is not None and 0 < patron.outstanding_fines <= 10.0 and not fines_acknowledged:
        try:
            answer = await elicit_with_timeout(
                ctx,
                f"{patron.name} has ${patron.outstanding_fines:.2f} in outstanding "
                "fines. Proceed with this checkout anyway?",
                response_type=bool,
                response_title="Proceed with checkout",
                response_description=(
                    "Confirm that the patron may borrow this book despite the listed fines."
                ),
            )
        except ElicitationUnavailableError as exc:
            raise ToolError(
                f"Confirmation required: {patron.name} has "
                f"${patron.outstanding_fines:.2f} in outstanding fines. Ask the "
                "user whether to proceed, then retry this same checkout with "
                "fines_acknowledged=true. No checkout was created."
            ) from exc
        except Exception as exc:
            raise ToolError(
                f"Confirmation required before checkout because {patron.name} has "
                f"${patron.outstanding_fines:.2f} in outstanding fines. Ask the "
                "user, then retry with fines_acknowledged=true. No checkout was created."
            ) from exc

        if answer.action != "accept" or not answer.data:
            _log_operation("checkout_book_declined", patron_id=patron_id, action=answer.action)
            raise ToolError(
                "Checkout cancelled: the user did not approve proceeding while "
                f"the patron has ${patron.outstanding_fines:.2f} in fines."
            )

    with get_session() as session:
        repo = CirculationRepository(session)
        try:
            checkout = repo.checkout_book(
                CheckoutCreateSchema(
                    patron_id=patron_id, book_isbn=book_isbn, due_date=due_date, notes=notes
                )
            )
        except NotFoundError as e:
            _log_operation("checkout_book_failed", patron_id=patron_id, error="not_found")
            raise ToolError(str(e)) from e
        except RepositoryException as e:
            _log_operation("checkout_book_failed", patron_id=patron_id, error="business_rule")
            raise ToolError(str(e)) from e

    _log_operation(
        "checkout_book_success",
        checkout_id=checkout.id,
        patron_id=checkout.patron_id,
        due_date=checkout.due_date.isoformat(),
    )
    return _checkout_result(checkout, replayed=False)


# ---------------------------------------------------------------------------
# Processing returns (fines, condition, availability)
# ---------------------------------------------------------------------------


async def return_book(
    checkout_id: Annotated[
        str,
        Field(
            description="ID of the checkout record being returned",
            pattern=r"^checkout_[a-zA-Z0-9]+$",
        ),
    ],
    condition: Annotated[
        Literal["excellent", "good", "fair", "damaged", "lost"],
        Field(description="Condition of the returned book"),
    ] = "good",
    notes: Annotated[
        str | None, Field(description="Notes about the return, e.g. damage details", max_length=500)
    ] = None,
    rating: Annotated[
        int | None, Field(description="Optional patron rating (1-5 stars)", ge=1, le=5)
    ] = None,
    review: Annotated[
        str | None, Field(description="Optional patron review text", max_length=1000)
    ] = None,
) -> ReturnResult:
    """Process a book return.

    Restores availability, calculates late fines at $0.25/day, and records
    the book's condition. Ratings and reviews are logged for future use.
    """
    _log_operation("return_book_start", checkout_id=checkout_id, condition=condition)

    with get_session() as session:
        repo = CirculationRepository(session)
        existing_return = repo.get_return_for_checkout(checkout_id)
        if existing_return is not None:
            return ReturnResult(
                return_id=existing_return.id,
                checkout_id=existing_return.checkout_id,
                book_isbn=existing_return.book_isbn,
                return_date=existing_return.return_date.isoformat(),
                condition=existing_return.condition,
                late_days=existing_return.late_days,
                fine_assessed=existing_return.fine_assessed,
                fine_outstanding=existing_return.fine_outstanding,
                replayed=True,
                message=(
                    f"This return was already processed as {existing_return.id}; "
                    "no second return or fine was created."
                ),
            )
        try:
            return_record, _ = repo.return_book(
                ReturnProcessSchema(
                    checkout_id=checkout_id,
                    condition=condition,
                    notes=notes,
                    processed_by="mcp_tool",
                )
            )
        except NotFoundError as e:
            raise ToolError(str(e)) from e
        except RepositoryException as e:
            raise ToolError(str(e)) from e

    if rating or review:
        logger.info("Review received | rating=%s review=%s", rating, (review or "")[:100])

    message = f"Returned '{return_record.book_isbn}'."
    if return_record.late_days > 0:
        message += (
            f" {return_record.late_days} day(s) late — fine assessed: "
            f"${return_record.fine_assessed:.2f}."
        )
    else:
        message += " Returned on time, no fines."
    if condition != "good":
        message += f" Condition noted: {condition}."

    _log_operation(
        "return_book_success",
        return_id=return_record.id,
        late_days=return_record.late_days,
        fine_assessed=return_record.fine_assessed,
    )
    return ReturnResult(
        return_id=return_record.id,
        checkout_id=return_record.checkout_id,
        book_isbn=return_record.book_isbn,
        return_date=return_record.return_date.isoformat(),
        condition=return_record.condition,
        late_days=return_record.late_days,
        fine_assessed=return_record.fine_assessed,
        fine_outstanding=return_record.fine_outstanding,
        replayed=False,
        message=message,
    )


# ---------------------------------------------------------------------------
# reserve_book
# ---------------------------------------------------------------------------


async def reserve_book(
    patron_id: Annotated[str, PATRON_ID_FIELD],
    book_isbn: Annotated[str, ISBN_FIELD],
    expiration_date: Annotated[
        date | None,
        Field(description="When the hold expires (defaults to 30 days out, max 90)"),
    ] = None,
    notes: Annotated[
        str | None, Field(description="Optional notes for the reservation", max_length=500)
    ] = None,
) -> ReservationResult:
    """Place a hold only after the user explicitly asks to reserve the book.

    Places the patron in the hold queue and reports their position and
    estimated wait. The reservation expires if not fulfilled in time.
    """
    today = datetime.now().date()
    if expiration_date is not None:
        if expiration_date <= today:
            raise ToolError("Expiration date must be in the future.")
        if expiration_date > today + timedelta(days=90):
            raise ToolError("Expiration date cannot be more than 90 days out.")

    _log_operation("reserve_book_start", patron_id=patron_id, book_isbn=book_isbn)

    with get_session() as session:
        repo = CirculationRepository(session)
        existing_reservation = repo.get_active_reservation_for_book(patron_id, book_isbn)
        if existing_reservation is not None:
            queue_info = repo.get_reservation_queue_info(book_isbn)
            return ReservationResult(
                reservation_id=existing_reservation.id,
                patron_id=existing_reservation.patron_id,
                book_isbn=existing_reservation.book_isbn,
                reservation_date=existing_reservation.reservation_date.isoformat(),
                expiration_date=existing_reservation.expiration_date.isoformat(),
                status=str(existing_reservation.status),
                queue_position=existing_reservation.queue_position,
                estimated_wait_days=queue_info.estimated_wait_days,
                total_in_queue=queue_info.total_reservations,
                replayed=True,
                message=(
                    f"This hold already exists as {existing_reservation.id}; "
                    "no duplicate reservation was created."
                ),
            )
        try:
            reservation = repo.create_reservation(
                ReservationCreateSchema(
                    patron_id=patron_id,
                    book_isbn=book_isbn,
                    expiration_date=expiration_date,
                    notes=notes,
                )
            )
            queue_info = repo.get_reservation_queue_info(book_isbn)
        except NotFoundError as e:
            raise ToolError(str(e)) from e
        except RepositoryException as e:
            raise ToolError(str(e)) from e

    message = (
        f"Reserved '{reservation.book_isbn}' for {reservation.patron_id}. "
        f"Queue position: {reservation.queue_position}"
    )
    if queue_info.estimated_wait_days:
        message += f" (estimated wait: {queue_info.estimated_wait_days} days)"
    message += f". Expires {reservation.expiration_date.strftime('%B %d, %Y')}."

    _log_operation(
        "reserve_book_success",
        reservation_id=reservation.id,
        queue_position=reservation.queue_position,
    )
    return ReservationResult(
        reservation_id=reservation.id,
        patron_id=reservation.patron_id,
        book_isbn=reservation.book_isbn,
        reservation_date=reservation.reservation_date.isoformat(),
        expiration_date=reservation.expiration_date.isoformat(),
        status=str(reservation.status),
        queue_position=reservation.queue_position,
        estimated_wait_days=queue_info.estimated_wait_days,
        total_in_queue=queue_info.total_reservations,
        replayed=False,
        message=message,
    )
