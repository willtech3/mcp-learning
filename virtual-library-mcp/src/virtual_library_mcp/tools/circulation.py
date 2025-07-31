"""
Circulation tools implementation for the Virtual Library MCP Server.

This module demonstrates MCP tools that modify library state through circulation operations:
1. checkout_book: Create a loan transaction and update availability
2. return_book: Process returns with fine calculation
3. reserve_book: Queue management for unavailable books

MCP TOOLS ARCHITECTURE:
Tools in the Model Context Protocol are the primary mechanism for LLMs to perform
actions with side effects. Unlike resources (read-only), tools can:
- Modify system state through create, update, delete operations
- Execute complex business logic with validation
- Return structured results or errors
- Support long-running operations with progress notifications

This implementation follows MCP best practices:
- Comprehensive input validation using Pydantic schemas
- Atomic operations with proper transaction handling
- Clear error messages for LLM interpretation
- Structured responses for further processing
"""

import logging
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ..database.circulation_repository import (
    CheckoutCreateSchema,
    CirculationRepository,
    ReservationCreateSchema,
    ReturnProcessSchema,
)
from ..database.repository import NotFoundError, RepositoryException
from ..database.session import get_session

logger = logging.getLogger(__name__)


# =============================================================================
# CHECKOUT TOOL IMPLEMENTATION
# =============================================================================

class CheckoutBookInput(BaseModel):
    """
    Input schema for the checkout_book tool.

    MCP SCHEMA DESIGN:
    The input schema serves multiple critical purposes in the MCP protocol:
    1. CLIENT DISCOVERY: Tells LLMs what parameters are available and required
    2. VALIDATION: Ensures inputs meet business rules before processing
    3. DOCUMENTATION: Self-documenting interface for tool capabilities
    4. TYPE SAFETY: Prevents runtime errors from invalid data types

    Each field includes comprehensive validation and examples to guide
    LLM usage and provide clear error messages when validation fails.
    """

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
    """
    Handler for the checkout_book tool.

    MCP TOOL LIFECYCLE:
    This handler demonstrates the complete MCP tool execution pattern:

    1. INPUT PHASE: Validate arguments against schema
    2. AUTHORIZATION: Check permissions (future enhancement)
    3. BUSINESS LOGIC: Execute core operation with validation
    4. STATE CHANGE: Modify system state atomically
    5. RESPONSE: Return structured result or error

    The handler coordinates multiple subsystems:
    - Database transactions for ACID compliance
    - Business rule validation (patron limits, availability)
    - State updates across multiple entities
    - Error handling with meaningful messages

    Args:
        arguments: Raw arguments from MCP tools/call request

    Returns:
        Structured response with checkout details or error information
    """
    try:
        # STEP 1: Validate and parse input
        # WHY: MCP requires strict input validation before processing
        # HOW: Pydantic validates types, patterns, and business rules
        # WHAT: This catches malformed requests early with clear errors
        try:
            params = CheckoutBookInput.model_validate(arguments)
        except Exception as e:
            logger.warning("Invalid checkout parameters: %s", e)
            return {
                "isError": True,
                "content": [{
                    "type": "text",
                    "text": f"Invalid checkout parameters: {e}"
                }]
            }

        # STEP 2: Execute checkout with repository
        # WHY: Business logic is encapsulated in the repository layer
        # HOW: Repository handles all database operations transactionally
        # WHAT: This ensures consistency across patron, book, and checkout records
        with get_session() as session:
            try:
                repo = CirculationRepository(session)

                # Convert to repository schema
                checkout_data = CheckoutCreateSchema(
                    patron_id=params.patron_id,
                    book_isbn=params.book_isbn,
                    due_date=params.due_date,
                    notes=params.notes,
                )

                # Execute checkout
                checkout = repo.checkout_book(checkout_data)

            except NotFoundError as e:
                # MCP ERROR PATTERN: Entity not found
                # Return specific error for missing patron or book
                logger.info("Checkout failed - entity not found: %s", e)
                return {
                    "isError": True,
                    "content": [{
                        "type": "text",
                        "text": str(e)
                    }]
                }

            except RepositoryException as e:
                # MCP ERROR PATTERN: Business rule violation
                # Return specific error for checkout restrictions
                logger.info("Checkout failed - business rule: %s", e)
                return {
                    "isError": True,
                    "content": [{
                        "type": "text",
                        "text": str(e)
                    }]
                }

            except Exception as e:
                # MCP ERROR PATTERN: Unexpected database error
                logger.exception("Checkout database error")
                return {
                    "isError": True,
                    "content": [{
                        "type": "text",
                        "text": f"Checkout failed: {e!s}"
                    }]
                }

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

        # Return MCP-compliant response
        return {
            "content": [{
                "type": "text",
                "text": message
            }],
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
            }
        }

    except Exception as e:
        # MCP ERROR PATTERN: Catch-all for unexpected errors
        # This ensures the tool never crashes the server
        logger.exception("Unexpected error in checkout_book tool")
        return {
            "isError": True,
            "content": [{
                "type": "text",
                "text": f"An unexpected error occurred: {e!s}"
            }]
        }


# =============================================================================
# RETURN TOOL IMPLEMENTATION
# =============================================================================

class ReturnBookInput(BaseModel):
    """
    Input schema for the return_book tool.

    MCP DESIGN CONSIDERATION:
    Return operations require minimal input (just the checkout ID) but
    support optional parameters for book condition and processing notes.
    This follows the MCP principle of progressive disclosure - simple
    cases are simple, complex cases are possible.
    """

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
        examples=["Minor water damage on cover", "Missing dust jacket", "Highlighted text on pages 45-67"],
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
    """
    Handler for the return_book tool.

    MCP PATTERN - STATEFUL OPERATIONS:
    This tool demonstrates handling operations that depend on existing state:
    1. Verify the checkout exists and is active
    2. Calculate derived values (fines for late returns)
    3. Update multiple related entities atomically
    4. Return comprehensive result including calculations

    The tool showcases MCP's ability to handle complex business logic
    while maintaining a simple interface for LLM interaction.
    """
    try:
        # Validate input
        try:
            params = ReturnBookInput.model_validate(arguments)
        except Exception as e:
            logger.warning("Invalid return parameters: %s", e)
            return {
                "isError": True,
                "content": [{
                    "type": "text",
                    "text": f"Invalid return parameters: {e}"
                }]
            }

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
                        params.review[:100] if params.review else None
                    )

            except NotFoundError as e:
                logger.info("Return failed - checkout not found: %s", e)
                return {
                    "isError": True,
                    "content": [{
                        "type": "text",
                        "text": str(e)
                    }]
                }

            except RepositoryException as e:
                logger.info("Return failed - business rule: %s", e)
                return {
                    "isError": True,
                    "content": [{
                        "type": "text",
                        "text": str(e)
                    }]
                }

            except Exception as e:
                logger.exception("Return database error")
                return {
                    "isError": True,
                    "content": [{
                        "type": "text",
                        "text": f"Return failed: {e!s}"
                    }]
                }

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

        return {
            "content": [{
                "type": "text",
                "text": message
            }],
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
            }
        }

    except Exception as e:
        logger.exception("Unexpected error in return_book tool")
        return {
            "isError": True,
            "content": [{
                "type": "text",
                "text": f"An unexpected error occurred: {e!s}"
            }]
        }


# =============================================================================
# RESERVATION TOOL IMPLEMENTATION
# =============================================================================

class ReserveBookInput(BaseModel):
    """
    Input schema for the reserve_book tool.

    MCP PATTERN - QUEUE MANAGEMENT:
    Reservations demonstrate MCP tools handling queue-based operations
    where the result depends on system state and other users' actions.
    This showcases tools that provide estimates rather than guarantees.
    """

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
    """
    Handler for the reserve_book tool.

    MCP ADVANCED PATTERN - ASYNCHRONOUS OUTCOMES:
    Reservations demonstrate tools where the immediate action (creating
    a reservation) has a delayed outcome (book becomes available).
    This pattern is common in real-world MCP implementations where
    tools initiate processes rather than complete them instantly.

    Future enhancements could include:
    - Progress notifications when moving up in queue
    - Subscription to availability updates
    - Automatic checkout when book becomes available
    """
    try:
        # Validate input
        try:
            params = ReserveBookInput.model_validate(arguments)
        except Exception as e:
            logger.warning("Invalid reservation parameters: %s", e)
            return {
                "isError": True,
                "content": [{
                    "type": "text",
                    "text": f"Invalid reservation parameters: {e}"
                }]
            }

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
                return {
                    "isError": True,
                    "content": [{
                        "type": "text",
                        "text": str(e)
                    }]
                }

            except RepositoryException as e:
                logger.info("Reservation failed - business rule: %s", e)
                return {
                    "isError": True,
                    "content": [{
                        "type": "text",
                        "text": str(e)
                    }]
                }

            except Exception as e:
                logger.exception("Reservation database error")
                return {
                    "isError": True,
                    "content": [{
                        "type": "text",
                        "text": f"Reservation failed: {e!s}"
                    }]
                }

        # Format response with queue position
        message = (
            f"Successfully reserved book '{reservation.book_isbn}' "
            f"for patron '{reservation.patron_id}'. "
            f"Queue position: {reservation.queue_position}"
        )

        if queue_info.estimated_wait_days:
            message += f" (estimated wait: {queue_info.estimated_wait_days} days)"

        message += f". Reservation expires on {reservation.expiration_date.strftime('%B %d, %Y')}"

        return {
            "content": [{
                "type": "text",
                "text": message
            }],
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
            }
        }

    except Exception as e:
        logger.exception("Unexpected error in reserve_book tool")
        return {
            "isError": True,
            "content": [{
                "type": "text",
                "text": f"An unexpected error occurred: {e!s}"
            }]
        }


# =============================================================================
# TOOL REGISTRATION
# =============================================================================

# Tool metadata for MCP server registration
# WHY: The server needs complete tool definitions for the tools/list response
# HOW: Each tool includes name, description, schema, and handler
# WHAT: These definitions enable LLM discovery and correct tool usage

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


# =============================================================================
# MCP PROTOCOL LEARNINGS
# =============================================================================

# Key Takeaways from Circulation Tools Implementation:
#
# 1. TOOLS ARE STATE MODIFIERS:
#    Unlike resources (read-only), tools are the primary mechanism for
#    LLMs to change system state. They must handle complex validation,
#    maintain data integrity, and provide clear feedback.
#
# 2. SCHEMA-DRIVEN DESIGN:
#    Input schemas serve triple duty: discovery (what can I do?),
#    validation (is this allowed?), and documentation (how do I use it?).
#    Rich schemas with examples guide LLM usage effectively.
#
# 3. ERROR HANDLING HIERARCHY:
#    Tools need multiple error levels:
#    - Validation errors (malformed input)
#    - Not found errors (missing entities)
#    - Business rule violations (patron limits, availability)
#    - System errors (database failures)
#    Each provides specific feedback for LLM adaptation.
#
# 4. TRANSACTION BOUNDARIES:
#    Tools often modify multiple entities atomically. The checkout tool
#    updates books, patrons, and creates records in one transaction.
#    This ensures consistency even if errors occur.
#
# 5. PROGRESSIVE DISCLOSURE:
#    Simple operations (return by ID) have minimal required parameters,
#    while supporting optional enhancements (condition, rating, review).
#    This makes tools approachable while enabling advanced usage.
#
# 6. STRUCTURED RESPONSES:
#    Tools return both human-readable messages and structured data.
#    This dual format serves both conversational UI and programmatic
#    processing by the LLM for follow-up actions.
#
# 7. QUEUE-BASED OPERATIONS:
#    The reservation tool demonstrates handling asynchronous outcomes
#    where the immediate action (reserve) has delayed fulfillment
#    (book available). This pattern is common in real-world systems.
#
# Next Steps:
# - Add renewal functionality to extend checkouts
# - Implement batch operations for multiple books
# - Add progress notifications for long operations
# - Create administrative tools for library staff
# - Implement fine payment processing
