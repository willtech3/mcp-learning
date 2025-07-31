"""Patron Resources - Library Member Management

Exposes patron records, borrowing history, and membership analytics.
Clients use these to view member details and track borrowing patterns.

Resources:
- library://patrons/list - All library members with filtering
- library://patrons/{id} - Individual patron details
- library://patrons/{id}/history - Borrowing history for a patron
- library://patrons/by-status/{status} - Members filtered by status
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from fastmcp.exceptions import ResourceError
from pydantic import BaseModel, Field

from database.circulation_repository import CirculationRepository
from database.patron_repository import PatronRepository, PatronSearchParams
from database.repository import PaginationParams
from database.session import session_scope
from models.patron import PatronStatus

logger = logging.getLogger(__name__)


class PatronHistoryParams(BaseModel):
    """Parameters for patron history resource.

    WHY: MCP resources can accept parameters to control the response.
    This allows clients to request specific time ranges or transaction types.
    """

    days: int = Field(default=90, ge=1, le=365, description="Number of days of history to show")
    include_active: bool = Field(default=True, description="Include active checkouts")
    include_completed: bool = Field(default=True, description="Include completed transactions")
    include_fines: bool = Field(default=True, description="Include fine information")


class PatronHistoryEntry(BaseModel):
    """Single entry in patron's borrowing history."""

    transaction_type: str = Field(
        ..., description="Type of transaction (checkout/return/reservation)"
    )
    transaction_id: str = Field(..., description="ID of the transaction")
    book_isbn: str = Field(..., description="ISBN of the book")
    book_title: str = Field(..., description="Title of the book")
    date: str = Field(..., description="Transaction date (ISO format)")
    status: str = Field(..., description="Current status")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Additional transaction details"
    )


class PatronHistoryResponse(BaseModel):
    """Response schema for patron history resource."""

    patron_id: str = Field(..., description="Patron ID")
    patron_name: str = Field(..., description="Patron name")
    history_period_days: int = Field(..., description="Number of days included in history")
    total_transactions: int = Field(..., description="Total number of transactions in period")
    active_checkouts: int = Field(..., description="Current number of active checkouts")
    history: list[PatronHistoryEntry] = Field(..., description="Transaction history entries")


# =============================================================================
# RESOURCE HANDLERS
# =============================================================================


async def get_patron_history_handler(patron_id: str) -> dict[str, Any]:
    """Handle requests for patron borrowing history.

    MCP NESTED RESOURCES:
    This demonstrates how resources can represent relationships between entities.
    The URI pattern library://patrons/{id}/history shows that history "belongs to" a patron.

    This is more intuitive than a flat structure like library://history?patron_id={id}
    and follows RESTful design principles.

    Args:
        patron_id: The patron ID from the URI template

    Returns:
        Dictionary containing the patron's borrowing history

    Raises:
        ResourceError: If patron not found or other errors
    """
    try:
        # Use default parameters for history filtering
        params = PatronHistoryParams()

        logger.debug(
            "MCP Resource Request - patrons/%s/history: days=%d, include_active=%s",
            patron_id,
            params.days,
            params.include_active,
        )

        with session_scope() as session:
            # Get patron details
            patron_repo = PatronRepository(session)
            patron = patron_repo.get_with_activity(patron_id)

            if patron is None:
                raise ResourceError(f"Patron not found: {patron_id}")

            # Get circulation history
            circ_repo = CirculationRepository(session)
            history_entries = []

            # Calculate date range
            cutoff_date = datetime.now() - timedelta(days=params.days)

            # Get checkouts in date range
            checkouts = circ_repo.get_patron_checkouts(
                patron_id=patron_id,
                include_active=params.include_active,
                include_completed=params.include_completed,
                since_date=cutoff_date,
            )

            # Convert checkouts to history entries
            for checkout in checkouts:
                entry = PatronHistoryEntry(
                    transaction_type="checkout",
                    transaction_id=checkout.id,
                    book_isbn=checkout.book_isbn,
                    book_title=checkout.book.title if hasattr(checkout, "book") else "Unknown",
                    date=checkout.checkout_date.isoformat(),
                    status=checkout.status.value,
                    details={
                        "due_date": checkout.due_date.isoformat(),
                        "renewal_count": checkout.renewal_count,
                        "is_overdue": checkout.is_overdue,
                        "days_overdue": checkout.days_overdue if checkout.is_overdue else 0,
                    },
                )

                if params.include_fines and checkout.fine_amount > 0:
                    entry.details["fine_amount"] = checkout.fine_amount
                    entry.details["fine_paid"] = checkout.fine_paid

                history_entries.append(entry)

            # Sort by date descending (most recent first)
            history_entries.sort(key=lambda x: x.date, reverse=True)

            # Build response
            response = PatronHistoryResponse(
                patron_id=patron.id,
                patron_name=patron.name,
                history_period_days=params.days,
                total_transactions=len(history_entries),
                active_checkouts=patron.current_checkouts,
                history=history_entries,
            )

            return response.model_dump()

    except ResourceError:
        raise
    except Exception as e:
        logger.exception("Error in patrons/{id}/history resource")
        raise ResourceError(f"Failed to retrieve patron history: {e!s}") from e


async def list_patrons_by_status_handler(status: str) -> dict[str, Any]:
    """Handle requests for patrons filtered by status.

    MCP URI TEMPLATES:
    This handler receives the status parameter directly from the URI template
    library://patrons/by-status/{status}. FastMCP 2.0 extracts and passes
    the parameter automatically.

    Example URIs:
    - library://patrons/by-status/active
    - library://patrons/by-status/suspended

    Args:
        status: The patron status from the URI template

    Returns:
        Dictionary containing filtered patron list
    """
    try:
        # Convert status string to enum (case-insensitive)
        status_str = status.upper()

        # Validate status
        try:
            patron_status = PatronStatus[status_str]
        except KeyError as e:
            raise ResourceError(f"Invalid patron status: {status}") from e

        # Use default pagination parameters
        page = 1
        limit = 20

        logger.debug(
            "MCP Resource Request - patrons/by-status/%s: page=%d, limit=%d",
            patron_status.value,
            page,
            limit,
        )

        with session_scope() as session:
            patron_repo = PatronRepository(session)

            # Search for patrons with specific status
            search_params = PatronSearchParams(status=patron_status)
            result = patron_repo.search(
                search_params=search_params, pagination=PaginationParams(page=page, page_size=limit)
            )

            # Build response with patron summaries
            patrons_data = []
            for patron in result.items:
                patrons_data.append(
                    {
                        "id": patron.id,
                        "name": patron.name,
                        "email": patron.email,
                        "membership_date": patron.membership_date.isoformat(),
                        "expiration_date": patron.expiration_date.isoformat()
                        if patron.expiration_date
                        else None,
                        "current_checkouts": patron.current_checkouts,
                        "borrowing_limit": patron.borrowing_limit,
                        "outstanding_fines": patron.outstanding_fines,
                        "is_active": patron.is_active,
                        "can_checkout": patron.can_checkout,
                    }
                )

            return {
                "status_filter": patron_status.value,
                "patrons": patrons_data,
                "total": result.total,
                "page": result.page,
                "page_size": result.page_size,
                "total_pages": result.total_pages,
                "has_next": result.has_next,
                "has_previous": result.has_previous,
            }

    except ResourceError:
        raise
    except Exception as e:
        logger.exception("Error in patrons/by-status resource")
        raise ResourceError(f"Failed to retrieve patrons by status: {e!s}") from e


# =============================================================================
# RESOURCE REGISTRATION
# =============================================================================

# Define patron resources for FastMCP registration
patron_resources: list[dict[str, Any]] = [
    {
        "uri_template": "library://patrons/{patron_id}/history",
        "name": "Patron Borrowing History",
        "description": (
            "Get the borrowing history for a specific patron, including active checkouts, "
            "returns, and fines. Supports filtering by date range and transaction type."
        ),
        "mime_type": "application/json",
        "handler": get_patron_history_handler,
    },
    {
        "uri_template": "library://patrons/by-status/{status}",
        "name": "Patrons by Status",
        "description": (
            "List all patrons with a specific membership status (active, suspended, expired, pending). "
            "Useful for administrative tasks and membership management."
        ),
        "mime_type": "application/json",
        "handler": list_patrons_by_status_handler,
    },
]
