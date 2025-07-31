"""Circulation Tools - Library Transaction Management

Modifies library state through checkout, return, and reservation operations.
Clients use these tools to manage book loans and patron interactions.

Tools:
- checkout_book: Loan a book to a patron
- return_book: Process book returns with fines
- reserve_book: Queue management for unavailable books
"""

import logging
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field, field_validator

from database.circulation_repository import (
    CheckoutCreateSchema,
    CirculationRepository,
    ReservationCreateSchema,
    ReturnProcessSchema,
)
from database.repository import NotFoundError, RepositoryException
from database.session import get_session

logger = logging.getLogger(__name__)


def _format_error_response(error_type: str, details: str) -> dict[str, Any]:
    """Format error responses consistently across all tools."""
    return {"isError": True, "content": [{"type": "text", "text": f"{error_type}: {details}"}]}


def _log_operation(operation: str, **kwargs) -> None:
    """Log operation details for audit trail."""
    logger.info(
        "Operation: %s | Details: %s", operation, " | ".join(f"{k}={v}" for k, v in kwargs.items())
    )


class CheckoutBookInput(BaseModel):
    """Input schema for book checkout operations."""

    patron_id: str = Field(
        ...,
        description="Unique identifier of the patron borrowing the book",
        pattern=r"^patron_[a-zA-Z0-9_]{6,}$",
        examples=["patron_smith001", "patron_doe_jane", "patron_wilson_robert"],
    )

    book_isbn: str = Field(
        ...,
        description="ISBN-13 of the book to checkout",
        pattern=r"^\d{13}$",
        examples=["9780134685479", "9780061120084", "9780062316097"],
    )

    due_date: date | None = Field(
        default=None,
        description="Optional custom due date. If not provided, uses standard 14-day loan period",
        examples=["2024-02-15", "2024-03-01"],
    )

    notes: str | None = Field(
        default=None,
        description="Optional notes about this checkout (e.g., 'Book club selection')",
        max_length=500,
        examples=["Book club reading", "Research for thesis", "Recommended by librarian"],
    )

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, v: date | None) -> date | None:
        """Ensure due date is not in the past."""
        if v is not None and v < datetime.now().date():
            raise ValueError("Due date cannot be in the past")
        return v


async def checkout_book_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    """Process book checkout request.

    Validates patron eligibility, book availability, and creates loan record.
    Returns checkout confirmation with due date or error details.

    Client calls: tool.call("checkout_book", {"patron_id": "...", "book_isbn": "..."})
    """
    try:
        try:
            params = CheckoutBookInput.model_validate(arguments)
        except Exception as e:
            logger.warning("Invalid checkout parameters: %s", e)
            return _format_error_response("Invalid parameters", str(e))

        _log_operation(
            "checkout_book_start",
            patron_id=params.patron_id,
            book_isbn=params.book_isbn,
            due_date=params.due_date,
            has_notes=bool(params.notes),
        )

        with get_session() as session:
            try:
                repo = CirculationRepository(session)
                checkout_data = CheckoutCreateSchema(
                    patron_id=params.patron_id,
                    book_isbn=params.book_isbn,
                    due_date=params.due_date,
                    notes=params.notes,
                )

                checkout = repo.checkout_book(checkout_data)

            except NotFoundError as e:
                logger.info("Checkout failed - entity not found: %s", e)
                _log_operation(
                    "checkout_book_failed",
                    patron_id=params.patron_id,
                    book_isbn=params.book_isbn,
                    error_type="not_found",
                    error_details=str(e),
                )
                return _format_error_response("Not found", str(e))

            except RepositoryException as e:
                # MCP ERROR PATTERN: Business rule violation
                # Return specific error for checkout restrictions
                logger.info("Checkout failed - business rule: %s", e)
                _log_operation(
                    "checkout_book_failed",
                    patron_id=params.patron_id,
                    book_isbn=params.book_isbn,
                    error_type="business_rule",
                    error_details=str(e),
                )
                return _format_error_response("Operation failed", str(e))

            except Exception as e:
                # MCP ERROR PATTERN: Unexpected database error
                logger.exception("Checkout database error")
                _log_operation(
                    "checkout_book_failed",
                    patron_id=params.patron_id,
                    book_isbn=params.book_isbn,
                    error_type="database_error",
                    error_details=str(e),
                )
                return _format_error_response("Database error", f"Checkout failed: {e!s}")

        # STEP 3: Format successful response
        # MCP RESPONSE FORMAT: Tools return structured content
        # The response includes both human-readable text and structured data
        message = (
            f"Successfully checked out book '{checkout.book_isbn}' "
            f"to patron '{checkout.patron_id}'. "
            f"Due date: {checkout.due_date.strftime('%B %d, %Y')}"
        )

        if checkout.loan_period_days == 14:
            message += " (standard 14-day loan)"
        else:
            message += f" ({checkout.loan_period_days}-day loan)"

        # Log successful operation
        _log_operation(
            "checkout_book_success",
            checkout_id=checkout.id,
            patron_id=checkout.patron_id,
            book_isbn=checkout.book_isbn,
            due_date=checkout.due_date.isoformat(),
            loan_period_days=checkout.loan_period_days,
        )

        # Return MCP-compliant response
        return {
            "content": [{"type": "text", "text": message}],
            # Include structured data for client processing
            # WHY: LLMs can use this data for follow-up actions
            "data": {
                "checkout": {
                    "id": checkout.id,
                    "patron_id": checkout.patron_id,
                    "book_isbn": checkout.book_isbn,
                    "checkout_date": checkout.checkout_date.isoformat(),
                    "due_date": checkout.due_date.isoformat(),
                    "status": checkout.status,
                    "renewal_count": checkout.renewal_count,
                    "loan_period_days": checkout.loan_period_days,
                }
            },
        }

    except Exception as e:
        # MCP ERROR PATTERN: Catch-all for unexpected errors
        # This ensures the tool never crashes the server
        logger.exception("Unexpected error in checkout_book tool")
        return _format_error_response("Unexpected error", str(e))


class ReturnBookInput(BaseModel):
    """Input schema for book return operations."""

    checkout_id: str = Field(
        ...,
        description="ID of the checkout record to return",
        pattern=r"^checkout_[a-zA-Z0-9]{6,}$",
        examples=["checkout_202312150001", "checkout_202403201234"],
    )

    condition: str = Field(
        default="good",
        description="Condition of the returned book",
        pattern=r"^(excellent|good|fair|damaged|lost)$",
        examples=["excellent", "good", "fair", "damaged", "lost"],
    )

    notes: str | None = Field(
        default=None,
        description="Optional notes about the return (e.g., damage details)",
        max_length=500,
        examples=[
            "Minor water damage on cover",
            "Missing dust jacket",
            "Highlighted text on pages 45-67",
        ],
    )

    rating: int | None = Field(
        default=None,
        description="Optional patron rating of the book (1-5 stars)",
        ge=1,
        le=5,
        examples=[1, 2, 3, 4, 5],
    )

    review: str | None = Field(
        default=None,
        description="Optional patron review of the book",
        max_length=1000,
        examples=["Great read, highly recommend!", "Not what I expected but still enjoyable"],
    )


async def return_book_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    """Process book return request.

    Calculates late fines, updates book availability, and records condition.
    Returns confirmation with fine details if applicable.

    Client calls: tool.call("return_book", {"checkout_id": "..."})
    """
    try:
        # Validate input
        try:
            params = ReturnBookInput.model_validate(arguments)
        except Exception as e:
            logger.warning("Invalid return parameters: %s", e)
            return _format_error_response("Invalid parameters", str(e))

        # Log operation start
        _log_operation(
            "return_book_start",
            checkout_id=params.checkout_id,
            condition=params.condition,
            has_notes=bool(params.notes),
            has_rating=bool(params.rating),
            has_review=bool(params.review),
        )

        # Execute return
        with get_session() as session:
            try:
                repo = CirculationRepository(session)

                # Convert to repository schema
                return_data = ReturnProcessSchema(
                    checkout_id=params.checkout_id,
                    condition=params.condition,
                    notes=params.notes,
                    processed_by="mcp_tool",  # Track that this was an MCP operation
                )

                # Process return
                return_record, _ = repo.return_book(return_data)

                # If rating/review provided, we could store it
                # (future enhancement: add review system)
                if params.rating or params.review:
                    logger.info(
                        "Book review received - Rating: %s, Review: %s",
                        params.rating,
                        params.review[:100] if params.review else None,
                    )

            except NotFoundError as e:
                logger.info("Return failed - checkout not found: %s", e)
                _log_operation(
                    "return_book_failed",
                    checkout_id=params.checkout_id,
                    error_type="not_found",
                    error_details=str(e),
                )
                return _format_error_response("Not found", str(e))

            except RepositoryException as e:
                logger.info("Return failed - business rule: %s", e)
                _log_operation(
                    "return_book_failed",
                    checkout_id=params.checkout_id,
                    error_type="business_rule",
                    error_details=str(e),
                )
                return _format_error_response("Operation failed", str(e))

            except Exception as e:
                logger.exception("Return database error")
                _log_operation(
                    "return_book_failed",
                    checkout_id=params.checkout_id,
                    error_type="database_error",
                    error_details=str(e),
                )
                return _format_error_response("Database error", f"Return failed: {e!s}")

        # Format response with fine information
        message = f"Successfully returned book '{return_record.book_isbn}'."

        if return_record.late_days > 0:
            message += (
                f" Book was {return_record.late_days} days late. "
                f"Fine assessed: ${return_record.fine_assessed:.2f}"
            )
        else:
            message += " Returned on time - no fines."

        if params.condition != "good":
            message += f" Book condition noted as: {params.condition}"

        # Log successful operation
        _log_operation(
            "return_book_success",
            return_id=return_record.id,
            checkout_id=return_record.checkout_id,
            book_isbn=return_record.book_isbn,
            condition=return_record.condition,
            late_days=return_record.late_days,
            fine_assessed=return_record.fine_assessed,
        )

        return {
            "content": [{"type": "text", "text": message}],
            "data": {
                "return": {
                    "id": return_record.id,
                    "checkout_id": return_record.checkout_id,
                    "return_date": return_record.return_date.isoformat(),
                    "condition": return_record.condition,
                    "late_days": return_record.late_days,
                    "fine_assessed": return_record.fine_assessed,
                    "fine_paid": return_record.fine_paid,
                    "fine_outstanding": return_record.fine_outstanding,
                }
            },
        }

    except Exception as e:
        logger.exception("Unexpected error in return_book tool")
        return _format_error_response("Unexpected error", str(e))


class ReserveBookInput(BaseModel):
    """Input schema for book reservation operations."""

    patron_id: str = Field(
        ...,
        description="Unique identifier of the patron making the reservation",
        pattern=r"^patron_[a-zA-Z0-9_]{6,}$",
        examples=["patron_smith001", "patron_doe_jane"],
    )

    book_isbn: str = Field(
        ...,
        description="ISBN-13 of the book to reserve",
        pattern=r"^\d{13}$",
        examples=["9780134685479", "9780061120084"],
    )

    expiration_date: date | None = Field(
        default=None,
        description="Optional custom expiration date. Defaults to 30 days from now",
        examples=["2024-03-15", "2024-04-01"],
    )

    notes: str | None = Field(
        default=None,
        description="Optional notes about this reservation",
        max_length=500,
        examples=["Need for book club meeting on March 15", "Research deadline April 1"],
    )

    @field_validator("expiration_date")
    @classmethod
    def validate_expiration_date(cls, v: date | None) -> date | None:
        """Ensure expiration date is in the future and reasonable."""
        if v is not None:
            if v <= datetime.now().date():
                raise ValueError("Expiration date must be in the future")
            if v > datetime.now().date() + timedelta(days=90):
                raise ValueError("Expiration date cannot be more than 90 days in the future")
        return v


async def reserve_book_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    """Process book reservation request.

    Creates reservation in queue, provides position and estimated wait time.
    Returns reservation details with queue status.

    Client calls: tool.call("reserve_book", {"patron_id": "...", "book_isbn": "..."})
    """
    try:
        # Validate input
        try:
            params = ReserveBookInput.model_validate(arguments)
        except Exception as e:
            logger.warning("Invalid reservation parameters: %s", e)
            return _format_error_response("Invalid parameters", str(e))

        # Log operation start
        _log_operation(
            "reserve_book_start",
            patron_id=params.patron_id,
            book_isbn=params.book_isbn,
            expiration_date=params.expiration_date,
            has_notes=bool(params.notes),
        )

        # Execute reservation
        with get_session() as session:
            try:
                repo = CirculationRepository(session)

                # Convert to repository schema
                reservation_data = ReservationCreateSchema(
                    patron_id=params.patron_id,
                    book_isbn=params.book_isbn,
                    expiration_date=params.expiration_date,
                    notes=params.notes,
                )

                # Create reservation
                reservation = repo.create_reservation(reservation_data)

                # Get queue information for context
                queue_info = repo.get_reservation_queue_info(params.book_isbn)

            except NotFoundError as e:
                logger.info("Reservation failed - entity not found: %s", e)
                _log_operation(
                    "reserve_book_failed",
                    patron_id=params.patron_id,
                    book_isbn=params.book_isbn,
                    error_type="not_found",
                    error_details=str(e),
                )
                return _format_error_response("Not found", str(e))

            except RepositoryException as e:
                logger.info("Reservation failed - business rule: %s", e)
                _log_operation(
                    "reserve_book_failed",
                    patron_id=params.patron_id,
                    book_isbn=params.book_isbn,
                    error_type="business_rule",
                    error_details=str(e),
                )
                return _format_error_response("Operation failed", str(e))

            except Exception as e:
                logger.exception("Reservation database error")
                _log_operation(
                    "reserve_book_failed",
                    patron_id=params.patron_id,
                    book_isbn=params.book_isbn,
                    error_type="database_error",
                    error_details=str(e),
                )
                return _format_error_response("Database error", f"Reservation failed: {e!s}")

        # Format response with queue position
        message = (
            f"Successfully reserved book '{reservation.book_isbn}' "
            f"for patron '{reservation.patron_id}'. "
            f"Queue position: {reservation.queue_position}"
        )

        if queue_info.estimated_wait_days:
            message += f" (estimated wait: {queue_info.estimated_wait_days} days)"

        message += f". Reservation expires on {reservation.expiration_date.strftime('%B %d, %Y')}"

        # Log successful operation
        _log_operation(
            "reserve_book_success",
            reservation_id=reservation.id,
            patron_id=reservation.patron_id,
            book_isbn=reservation.book_isbn,
            queue_position=reservation.queue_position,
            estimated_wait_days=queue_info.estimated_wait_days,
            expiration_date=reservation.expiration_date.isoformat(),
        )

        return {
            "content": [{"type": "text", "text": message}],
            "data": {
                "reservation": {
                    "id": reservation.id,
                    "patron_id": reservation.patron_id,
                    "book_isbn": reservation.book_isbn,
                    "reservation_date": reservation.reservation_date.isoformat(),
                    "expiration_date": reservation.expiration_date.isoformat(),
                    "status": reservation.status,
                    "queue_position": reservation.queue_position,
                    "estimated_wait_days": queue_info.estimated_wait_days,
                    "total_in_queue": queue_info.total_reservations,
                }
            },
        }

    except Exception as e:
        logger.exception("Unexpected error in reserve_book tool")
        return _format_error_response("Unexpected error", str(e))


checkout_book = {
    "name": "checkout_book",
    "description": (
        "Check out a book to a patron. Creates a loan record, updates book availability, "
        "and sets the due date. Validates patron eligibility (active membership, within "
        "borrowing limits, no excessive fines) and book availability before processing."
    ),
    "inputSchema": CheckoutBookInput.model_json_schema(),
    "handler": checkout_book_handler,
}

return_book = {
    "name": "return_book",
    "description": (
        "Process a book return. Updates the checkout record, restores book availability, "
        "calculates any late fines, and records the book's condition. Optionally accepts "
        "patron ratings and reviews for the book."
    ),
    "inputSchema": ReturnBookInput.model_json_schema(),
    "handler": return_book_handler,
}

reserve_book = {
    "name": "reserve_book",
    "description": (
        "Reserve an unavailable book. Places the patron in a queue and provides queue "
        "position and estimated wait time. The reservation expires after a specified "
        "period if not fulfilled. Patrons are notified when their reserved book becomes available."
    ),
    "inputSchema": ReserveBookInput.model_json_schema(),
    "handler": reserve_book_handler,
}
