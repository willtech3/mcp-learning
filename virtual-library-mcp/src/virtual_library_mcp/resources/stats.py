"""Statistics Resources - Library Analytics

Exposes aggregated library metrics and analytics.
Clients use these to understand usage patterns and popular content.

Resources:
- library://stats/popular/{days}/{limit} - Most borrowed books
- library://stats/genres/{days} - Checkout distribution by genre
- library://stats/circulation - Current circulation metrics
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from fastmcp.exceptions import ResourceError
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import joinedload

from ..database.schema import Book as BookDB
from ..database.schema import CheckoutRecord as CheckoutDB
from ..database.schema import CirculationStatusEnum
from ..database.session import session_scope

logger = logging.getLogger(__name__)


class PopularBookEntry(BaseModel):
    """Entry in the popular books list."""

    rank: int = Field(..., description="Popularity rank (1 = most popular)")
    isbn: str = Field(..., description="Book ISBN")
    title: str = Field(..., description="Book title")
    author: str = Field(..., description="Book author")
    checkout_count: int = Field(..., description="Number of checkouts in period")
    unique_borrowers: int = Field(..., description="Number of unique patrons who borrowed")
    avg_loan_days: float = Field(..., description="Average days book was kept")
    currently_available: bool = Field(..., description="Whether copies are available now")


class GenreDistributionEntry(BaseModel):
    """Entry in genre distribution stats."""

    genre: str = Field(..., description="Genre name")
    book_count: int = Field(..., description="Total books in this genre")
    checkout_count: int = Field(..., description="Total checkouts in period")
    percentage: float = Field(..., description="Percentage of total checkouts")
    avg_checkouts_per_book: float = Field(..., description="Average checkouts per book in genre")


class CirculationStatsResponse(BaseModel):
    """Current circulation statistics."""

    timestamp: str = Field(..., description="When stats were calculated (ISO format)")

    # Current state
    total_books: int = Field(..., description="Total books in library")
    total_copies: int = Field(..., description="Total physical copies")
    available_copies: int = Field(..., description="Copies currently available")
    checked_out_copies: int = Field(..., description="Copies currently checked out")

    # Activity metrics
    checkouts_today: int = Field(..., description="Checkouts processed today")
    checkouts_this_week: int = Field(..., description="Checkouts in last 7 days")
    checkouts_this_month: int = Field(..., description="Checkouts in last 30 days")

    returns_today: int = Field(..., description="Returns processed today")
    returns_this_week: int = Field(..., description="Returns in last 7 days")
    returns_this_month: int = Field(..., description="Returns in last 30 days")

    # Overdue metrics
    overdue_count: int = Field(..., description="Number of overdue checkouts")
    overdue_1_7_days: int = Field(..., description="Overdue by 1-7 days")
    overdue_8_14_days: int = Field(..., description="Overdue by 8-14 days")
    overdue_15_plus_days: int = Field(..., description="Overdue by 15+ days")

    # Utilization metrics
    circulation_rate: float = Field(..., description="Percentage of collection checked out")
    avg_loan_duration_days: float = Field(..., description="Average days books are kept")


async def get_popular_books_handler(days: str, limit: str) -> dict[str, Any]:
    """Returns most borrowed books in the specified time period.

    Client requests library://stats/popular/{days}/{limit} to discover
    trending books based on checkout frequency.
    """
    try:
        # Convert string parameters to integers with validation
        days_int = int(days)
        limit_int = int(limit)

        # Validate ranges (same as Pydantic model)
        if not 1 <= days_int <= 365:
            raise ResourceError("days must be between 1 and 365")
        if not 1 <= limit_int <= 50:
            raise ResourceError("limit must be between 1 and 50")

        logger.debug("MCP Resource Request - stats/popular: days=%d, limit=%d", days_int, limit_int)

        # Calculate date range
        start_date = datetime.now() - timedelta(days=days_int)

        with session_scope() as session:
            # Query to get checkout counts by book
            # This demonstrates SQL aggregation within MCP resources
            checkout_stats = session.execute(
                select(
                    CheckoutDB.book_isbn,
                    func.count(CheckoutDB.id).label("checkout_count"),
                    func.count(func.distinct(CheckoutDB.patron_id)).label("unique_borrowers"),
                    func.avg(
                        func.julianday(
                            func.coalesce(CheckoutDB.return_date, func.current_timestamp())
                        )
                        - func.julianday(CheckoutDB.checkout_date)
                    ).label("avg_loan_days"),
                )
                .where(CheckoutDB.checkout_date >= start_date)
                .group_by(CheckoutDB.book_isbn)
                .having(func.count(CheckoutDB.id) >= 1)  # Minimum checkouts threshold
                .order_by(desc("checkout_count"))
                .limit(limit_int)
            ).all()

            # Get book details for the popular books
            popular_books = []
            rank = 1

            for stat in checkout_stats:
                # Get book details with author joined
                book = session.execute(
                    select(BookDB)
                    .where(BookDB.isbn == stat.book_isbn)
                    .options(joinedload(BookDB.author))
                ).scalar_one_or_none()

                if book:
                    popular_books.append(
                        PopularBookEntry(
                            rank=rank,
                            isbn=book.isbn,
                            title=book.title,
                            author=book.author.name if book.author else "Unknown",
                            checkout_count=stat.checkout_count,
                            unique_borrowers=stat.unique_borrowers,
                            avg_loan_days=round(stat.avg_loan_days or 0, 1),
                            currently_available=book.available_copies > 0,
                        )
                    )
                    rank += 1

            return {
                "analysis_period_days": days_int,
                "analysis_start_date": start_date.date().isoformat(),
                "analysis_end_date": datetime.now().date().isoformat(),
                "total_results": len(popular_books),
                "min_checkouts_threshold": 1,
                "books": [book.model_dump() for book in popular_books],
            }

    except Exception as e:
        logger.exception("Error in stats/popular resource")
        raise ResourceError(f"Failed to calculate popular books: {e!s}") from e


async def get_genre_distribution_handler(days: str) -> dict[str, Any]:
    """Returns checkout distribution across genres.

    Client requests library://stats/genres/{days} to analyze
    reading preferences and genre popularity trends.
    """
    try:
        # Convert and validate parameter
        days_int = int(days)
        if not 1 <= days_int <= 365:
            raise ResourceError("days must be between 1 and 365")

        logger.debug("MCP Resource Request - stats/genres: days=%d", days_int)

        start_date = datetime.now() - timedelta(days=days_int)

        with session_scope() as session:
            # Get all books with genres
            all_books = session.execute(
                select(BookDB.genre, func.count(BookDB.isbn).label("book_count"))
                .group_by(BookDB.genre)
                .order_by(BookDB.genre)
            ).all()

            # Build genre inventory
            genre_stats = {
                genre: {"book_count": count, "checkout_count": 0, "books_checked_out": set()}
                for genre, count in all_books
            }

            # Get checkout counts by genre
            checkouts_by_genre = session.execute(
                select(
                    BookDB.genre,
                    func.count(CheckoutDB.id).label("checkout_count"),
                    func.count(func.distinct(CheckoutDB.book_isbn)).label("unique_books"),
                )
                .select_from(CheckoutDB)
                .join(BookDB, CheckoutDB.book_isbn == BookDB.isbn)
                .where(CheckoutDB.checkout_date >= start_date)
                .group_by(BookDB.genre)
            ).all()

            # Update stats with checkout data
            total_checkouts = 0
            for genre, checkout_count, unique_books in checkouts_by_genre:
                if genre in genre_stats:
                    genre_stats[genre]["checkout_count"] = checkout_count
                    genre_stats[genre]["unique_books_checked_out"] = unique_books
                    total_checkouts += checkout_count

            # Calculate percentages and build response
            distribution = []
            for genre, stats in sorted(genre_stats.items()):
                if stats["book_count"] > 0:  # Only include genres with books
                    percentage = (
                        (stats["checkout_count"] / total_checkouts * 100)
                        if total_checkouts > 0
                        else 0
                    )
                    avg_per_book = stats["checkout_count"] / stats["book_count"]

                    distribution.append(
                        GenreDistributionEntry(
                            genre=genre,
                            book_count=stats["book_count"],
                            checkout_count=stats["checkout_count"],
                            percentage=round(percentage, 1),
                            avg_checkouts_per_book=round(avg_per_book, 2),
                        )
                    )

            # Sort by checkout count descending
            distribution.sort(key=lambda x: x.checkout_count, reverse=True)

            return {
                "analysis_period_days": days_int,
                "analysis_start_date": start_date.date().isoformat(),
                "analysis_end_date": datetime.now().date().isoformat(),
                "total_checkouts_analyzed": total_checkouts,
                "genres": [entry.model_dump() for entry in distribution],
            }

    except Exception as e:
        logger.exception("Error in stats/genres resource")
        raise ResourceError(f"Failed to calculate genre distribution: {e!s}") from e


async def get_circulation_stats_handler() -> dict[str, Any]:
    """Returns real-time library circulation metrics.

    Client requests library://stats/circulation for current
    checkout activity, overdue items, and utilization rates.
    """
    try:
        logger.debug("MCP Resource Request - stats/circulation")

        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)
        month_start = now - timedelta(days=30)

        with session_scope() as session:
            # Get book inventory stats
            total_books = session.execute(select(func.count(BookDB.isbn))).scalar() or 0

            total_copies = session.execute(select(func.sum(BookDB.total_copies))).scalar() or 0

            available_copies = (
                session.execute(select(func.sum(BookDB.available_copies))).scalar() or 0
            )

            checked_out_copies = total_copies - available_copies

            # Get checkout activity stats
            checkouts_today = (
                session.execute(
                    select(func.count(CheckoutDB.id)).where(CheckoutDB.checkout_date >= today_start)
                ).scalar()
                or 0
            )

            checkouts_week = (
                session.execute(
                    select(func.count(CheckoutDB.id)).where(CheckoutDB.checkout_date >= week_start)
                ).scalar()
                or 0
            )

            checkouts_month = (
                session.execute(
                    select(func.count(CheckoutDB.id)).where(CheckoutDB.checkout_date >= month_start)
                ).scalar()
                or 0
            )

            # Get return activity stats
            returns_today = (
                session.execute(
                    select(func.count(CheckoutDB.id)).where(
                        and_(
                            CheckoutDB.return_date >= today_start,
                            CheckoutDB.status == CirculationStatusEnum.COMPLETED,
                        )
                    )
                ).scalar()
                or 0
            )

            returns_week = (
                session.execute(
                    select(func.count(CheckoutDB.id)).where(
                        and_(
                            CheckoutDB.return_date >= week_start,
                            CheckoutDB.status == CirculationStatusEnum.COMPLETED,
                        )
                    )
                ).scalar()
                or 0
            )

            returns_month = (
                session.execute(
                    select(func.count(CheckoutDB.id)).where(
                        and_(
                            CheckoutDB.return_date >= month_start,
                            CheckoutDB.status == CirculationStatusEnum.COMPLETED,
                        )
                    )
                ).scalar()
                or 0
            )

            # Get overdue stats
            overdue_checkouts = session.execute(
                select(CheckoutDB.id, CheckoutDB.due_date).where(
                    and_(
                        CheckoutDB.status == CirculationStatusEnum.ACTIVE,
                        CheckoutDB.due_date < now.date(),
                    )
                )
            ).all()

            # Categorize overdue by severity
            overdue_1_7 = 0
            overdue_8_14 = 0
            overdue_15_plus = 0

            for _checkout_id, due_date in overdue_checkouts:
                days_overdue = (now.date() - due_date).days
                if days_overdue <= 7:
                    overdue_1_7 += 1
                elif days_overdue <= 14:
                    overdue_8_14 += 1
                else:
                    overdue_15_plus += 1

            # Calculate average loan duration for completed checkouts
            avg_duration_result = session.execute(
                select(
                    func.avg(
                        func.julianday(CheckoutDB.return_date)
                        - func.julianday(CheckoutDB.checkout_date)
                    )
                ).where(
                    and_(
                        CheckoutDB.status == CirculationStatusEnum.COMPLETED,
                        CheckoutDB.return_date.isnot(None),
                    )
                )
            ).scalar()

            avg_loan_duration = round(avg_duration_result or 14.0, 1)

            # Build response
            response = CirculationStatsResponse(
                timestamp=now.isoformat(),
                # Inventory
                total_books=total_books,
                total_copies=total_copies,
                available_copies=available_copies,
                checked_out_copies=checked_out_copies,
                # Activity
                checkouts_today=checkouts_today,
                checkouts_this_week=checkouts_week,
                checkouts_this_month=checkouts_month,
                returns_today=returns_today,
                returns_this_week=returns_week,
                returns_this_month=returns_month,
                # Overdue
                overdue_count=len(overdue_checkouts),
                overdue_1_7_days=overdue_1_7,
                overdue_8_14_days=overdue_8_14,
                overdue_15_plus_days=overdue_15_plus,
                # Utilization
                circulation_rate=round(
                    (checked_out_copies / total_copies * 100) if total_copies > 0 else 0, 1
                ),
                avg_loan_duration_days=avg_loan_duration,
            )

            return response.model_dump()

    except Exception as e:
        logger.exception("Error in stats/circulation resource")
        raise ResourceError(f"Failed to calculate circulation stats: {e!s}") from e


stats_resources: list[dict[str, Any]] = [
    {
        "uri_template": "library://stats/popular/{days}/{limit}",
        "name": "Popular Books",
        "description": (
            "Get the most borrowed books for a specified time period. "
            "URI format: library://stats/popular/{days}/{limit} where "
            "days is 1-365 and limit is 1-50."
        ),
        "mime_type": "application/json",
        "handler": get_popular_books_handler,
    },
    {
        "uri_template": "library://stats/genres/{days}",
        "name": "Genre Distribution",
        "description": (
            "Analyze the distribution of checkouts across different genres. "
            "URI format: library://stats/genres/{days} where "
            "days is 1-365."
        ),
        "mime_type": "application/json",
        "handler": get_genre_distribution_handler,
    },
    {
        "uri": "library://stats/circulation",
        "name": "Circulation Statistics",
        "description": (
            "Get current circulation metrics including checkouts, returns, overdue items, "
            "and utilization rates. Provides a real-time snapshot of library operations."
        ),
        "mime_type": "application/json",
        "handler": get_circulation_stats_handler,
    },
]
