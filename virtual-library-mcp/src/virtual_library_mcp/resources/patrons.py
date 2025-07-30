"""Patron Resources for Virtual Library MCP Server

This module implements MCP resources for accessing patron data and history.
It demonstrates advanced MCP concepts including:
- URI templates with dynamic parameters
- Resource relationships (patron -> borrowing history)
- Aggregated data views

MCP ADVANCED RESOURCE CONCEPTS:
1. **URI Templates**: Resources can use {parameter} placeholders for dynamic routing
2. **Nested Resources**: Resources can represent relationships (e.g., /patrons/{id}/history)
3. **Aggregations**: Resources can provide computed views of data
4. **Filtering**: Resources support query parameters for filtering results

DESIGN DECISIONS:
- Using patron ID in URIs rather than email for privacy/security
- History resources show both active and completed transactions
- Aggregations are read-only computed views of the data
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from fastmcp import Context
from fastmcp.exceptions import ResourceError
from pydantic import BaseModel, Field

from ..database.circulation_repository import CirculationRepository
from ..database.patron_repository import PatronRepository, PatronSearchParams
from ..database.repository import PaginationParams
from ..database.session import session_scope
from ..models.patron import PatronStatus

logger = logging.getLogger(__name__)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def extract_patron_id_from_uri(uri: str) -> str:
    """Extract patron ID from library://patrons/{patron_id} URI.

    MCP URI PARSING:
    Similar to book ISBN extraction, but handles patron IDs which
    may contain underscores and alphanumeric characters.

    Args:
        uri: The full resource URI

    Returns:
        The extracted patron ID

    Raises:
        ValueError: If URI format is invalid
    """
    try:
        parsed = urlparse(uri)

        # Validate scheme
        if parsed.scheme != "library":
            raise ValueError(f"Invalid scheme '{parsed.scheme}', expected 'library'")

        # Reconstruct full path from netloc and path
        if parsed.netloc and parsed.path:
            full_path = f"{parsed.netloc}{parsed.path}"
        elif parsed.netloc:
            full_path = parsed.netloc
        elif parsed.path:
            full_path = parsed.path.lstrip("/")
        else:
            raise ValueError("No path information found in URI")

        # Split path and validate structure
        path_parts = full_path.split("/")
        if len(path_parts) < 2 or path_parts[0] != "patrons":
            raise ValueError(
                f"Invalid path structure, expected 'patrons/{{id}}' or 'patrons/{{id}}/resource', got '{full_path}'"
            )

        # Extract patron ID (second part)
        patron_id = path_parts[1]
        if not patron_id:
            raise ValueError("Missing patron ID in URI")

        return patron_id

    except Exception as e:
        raise ValueError(f"Invalid patron URI format '{uri}': {e}") from e


# =============================================================================
# RESOURCE SCHEMAS
# =============================================================================


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


async def get_patron_history_handler(
    uri: str,
    context: Context,  # noqa: ARG001
    params: PatronHistoryParams | None = None,
) -> dict[str, Any]:
    """Handle requests for patron borrowing history.

    MCP NESTED RESOURCES:
    This demonstrates how resources can represent relationships between entities.
    The URI pattern library://patrons/{id}/history shows that history "belongs to" a patron.

    This is more intuitive than a flat structure like library://history?patron_id={id}
    and follows RESTful design principles.

    Args:
        uri: The resource URI (e.g., "library://patrons/patron_smith001/history")
        context: FastMCP context
        params: Optional parameters for filtering history

    Returns:
        Dictionary containing the patron's borrowing history

    Raises:
        ResourceError: If patron not found or other errors
    """
    try:
        # Extract patron ID from URI
        patron_id = extract_patron_id_from_uri(uri.rsplit("/history", 1)[0])

        # Default parameters if none provided
        if params is None:
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


async def list_patrons_by_status_handler(
    uri: str,
    context: Context,  # noqa: ARG001
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Handle requests for patrons filtered by status.

    MCP QUERY PARAMETERS:
    Resources can accept query parameters through the URI query string.
    This handler demonstrates filtering based on patron status.

    Example URIs:
    - library://patrons/by-status/active
    - library://patrons/by-status/suspended?page=2

    Args:
        uri: The resource URI
        context: FastMCP context
        params: Query parameters (page, limit, etc.)

    Returns:
        Dictionary containing filtered patron list
    """
    try:
        # Extract status from URI
        parsed = urlparse(uri)
        path_parts = parsed.path.lstrip("/").split("/") if parsed.path else []

        if len(path_parts) < 3 or path_parts[1] != "by-status":
            raise ValueError("Invalid URI format for by-status resource")

        status_str = path_parts[2].upper()

        # Validate status
        try:
            status = PatronStatus[status_str]
        except KeyError as e:
            raise ResourceError(f"Invalid patron status: {status_str}") from e

        # Parse query parameters
        if params is None:
            params = {}

        page = int(params.get("page", 1))
        limit = min(int(params.get("limit", 20)), 100)  # Cap at 100

        logger.debug(
            "MCP Resource Request - patrons/by-status/%s: page=%d, limit=%d",
            status.value,
            page,
            limit,
        )

        with session_scope() as session:
            patron_repo = PatronRepository(session)

            # Search for patrons with specific status
            search_params = PatronSearchParams(status=status)
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
                "status_filter": status.value,
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


# =============================================================================
# MCP ADVANCED RESOURCES LEARNINGS
# =============================================================================

"""
KEY INSIGHTS FROM IMPLEMENTING ADVANCED MCP RESOURCES:

1. **URI TEMPLATE DESIGN**:
   - Use meaningful hierarchies: /patrons/{id}/history shows clear ownership
   - Status filters as path segments: /by-status/active is cleaner than ?status=active
   - Keep templates intuitive and self-documenting

2. **PARAMETER VALIDATION**:
   - Always validate extracted parameters before using them
   - Provide clear error messages for invalid parameters
   - Use Pydantic models for complex parameter sets

3. **RESOURCE RELATIONSHIPS**:
   - Nested resources show clear data relationships
   - Use consistent patterns across your API
   - Consider the natural hierarchy of your domain

4. **PERFORMANCE CONSIDERATIONS**:
   - Aggregate data at the database level when possible
   - Limit default result sizes to prevent overwhelming responses
   - Consider caching for expensive computations

5. **ERROR HANDLING**:
   - Return appropriate error codes for different scenarios
   - Include enough context in errors for debugging
   - Distinguish between client errors and server errors

NEXT STEPS:
- Add more aggregation resources (popular books, circulation stats)
- Implement recommendation algorithms
- Add filtering by multiple criteria
- Consider adding resource subscriptions for real-time updates
"""

