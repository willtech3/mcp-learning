"""Catalog maintenance tool for regenerating indexes and statistics.

This module demonstrates multi-stage progress notifications during
long-running maintenance operations.
"""

import asyncio
import logging
from typing import Any

from fastmcp import Context
from fastmcp.tools import ToolResult
from sqlalchemy import func

from database.circulation_repository import CirculationRepository
from database.patron_repository import PatronRepository
from database.repository import PaginationParams
from database.schema import Author as AuthorDB
from database.schema import Book as BookDB
from database.schema import CheckoutRecord
from database.session import session_scope

# Observability is handled by middleware, not decorators

logger = logging.getLogger(__name__)


# The resource taken offline while its cache rebuilds (maintenance mode).
RECOMMENDATIONS_RESOURCE = "Personalized Book Recommendations"


async def regenerate_catalog(ctx: Context) -> ToolResult:
    """Perform full catalog maintenance with live progress reporting.

    Four stages, each reporting progress: data integrity (0-20%), search
    indexes (20-50%), circulation statistics (50-80%), and the
    recommendations cache (80-100%).

    MCP concepts on display:
    - Progress notifications across a long-running operation
    - notifications/resources/list_changed: the recommendations resource is
      disabled during the rebuild and re-enabled after, and FastMCP
      notifies connected clients of both visibility changes automatically
    - ToolResult: human-readable summary AND machine-readable structure
    - Background tasks (SEP-1686): registered with task support, so task-aware
      clients can run it asynchronously and poll for the result
    """
    await ctx.info("Starting catalog regeneration")

    # MAINTENANCE MODE: hide the recommendations template from this session
    # while its cache is being rebuilt. ctx.disable_components() and the
    # closing reset_visibility() each push a resources/list_changed
    # notification to the client, demonstrating live visibility changes.
    await ctx.disable_components(names={RECOMMENDATIONS_RESOURCE}, components={"template"})
    try:
        await ctx.info("Stage 1: Verifying data integrity")
        integrity_results = await _verify_data_integrity(ctx, 0, 20)

        await ctx.info("Stage 2: Rebuilding search indexes")
        index_results = await _rebuild_search_indexes(ctx, 20, 50)

        await ctx.info("Stage 3: Updating circulation statistics")
        stats_results = await _update_circulation_stats(ctx, 50, 80)

        await ctx.info("Stage 4: Generating recommendations cache")
        cache_results = await _generate_recommendations_cache(ctx, 80, 100)
    finally:
        await ctx.reset_visibility()

    await ctx.report_progress(progress=100, total=100, message="Catalog regeneration complete")
    await ctx.info("Catalog regeneration completed successfully")

    result = {
        "status": "completed",
        "integrity_check": integrity_results,
        "search_indexes": index_results,
        "circulation_stats": stats_results,
        "recommendations_cache": cache_results,
        "message": "Catalog regeneration completed successfully",
    }
    return ToolResult(content=_format_summary(result), structured_content=result)


def _format_summary(result: dict[str, Any]) -> str:
    """Human-readable maintenance report for the text content block."""
    lines = [
        "Catalog regeneration completed successfully!",
        "",
        f"- Data integrity: {result['integrity_check']['books_checked']} books checked",
        f"- Search indexes: {result['search_indexes']['books_indexed']} books, "
        f"{result['search_indexes']['authors_indexed']} authors, "
        f"{result['search_indexes']['genres_indexed']} genres indexed",
        f"- Circulation: {result['circulation_stats']['active_loans']} active loans, "
        f"{result['circulation_stats']['overdue_loans']} overdue",
        f"- Recommendations: {result['recommendations_cache']['patrons_processed']} patrons, "
        f"{result['recommendations_cache']['recommendations_generated']} recommendations",
    ]
    if result["integrity_check"]["orphaned_books"]:
        lines.append(f"- WARNING: {result['integrity_check']['orphaned_books']} orphaned books")
    if result["integrity_check"]["invalid_circulations"]:
        lines.append(
            f"- WARNING: {result['integrity_check']['invalid_circulations']} invalid circulations"
        )
    return "\n".join(lines)


async def _verify_data_integrity(
    ctx: Context, start_progress: int, end_progress: int
) -> dict[str, Any]:
    """Verify data integrity with progress reporting."""
    results = {
        "books_checked": 0,
        "orphaned_books": 0,
        "missing_authors": 0,
        "invalid_circulations": 0,
    }

    with session_scope() as session:
        # Count total books for progress
        total_books = session.query(func.count(BookDB.isbn)).scalar() or 0
        results["books_checked"] = total_books

        # Check for orphaned books (no author)
        await ctx.report_progress(
            progress=start_progress + 5, total=100, message="Checking for orphaned books"
        )

        orphaned = (
            session.query(func.count(BookDB.isbn)).filter(BookDB.author_id.is_(None)).scalar() or 0
        )
        results["orphaned_books"] = orphaned

        if orphaned > 0:
            await ctx.warning(f"Found {orphaned} books without authors")

        # Check for invalid circulations
        await ctx.report_progress(
            progress=start_progress + 10, total=100, message="Validating circulation records"
        )

        # Find circulations with non-existent books or patrons
        invalid_circs = (
            session.query(func.count(CheckoutRecord.id))
            .filter(~CheckoutRecord.book.has() | ~CheckoutRecord.patron.has())
            .scalar()
            or 0
        )
        results["invalid_circulations"] = invalid_circs

        if invalid_circs > 0:
            await ctx.warning(f"Found {invalid_circs} invalid circulation records")

        # Simulate additional checks
        await asyncio.sleep(0.2)  # Simulate processing time

        await ctx.report_progress(
            progress=end_progress, total=100, message="Data integrity check complete"
        )

    return results


async def _rebuild_search_indexes(
    ctx: Context, start_progress: int, end_progress: int
) -> dict[str, Any]:
    """Rebuild search indexes with progress reporting."""
    results = {"books_indexed": 0, "authors_indexed": 0, "genres_indexed": 0}

    with session_scope() as session:
        # Index books
        total_books = session.query(func.count(BookDB.isbn)).scalar() or 0
        results["books_indexed"] = total_books

        # Simulate indexing in batches
        batch_size = 100
        progress_range = end_progress - start_progress

        for i in range(0, total_books, batch_size):
            current_batch = min(i + batch_size, total_books)
            progress = start_progress + int((i / total_books) * progress_range * 0.6)

            await ctx.report_progress(
                progress=progress,
                total=100,
                message=f"Indexing books {i + 1}-{current_batch}/{total_books}",
            )

            # Simulate indexing time
            await asyncio.sleep(0.1)

        # Index authors
        await ctx.report_progress(
            progress=start_progress + int(progress_range * 0.7),
            total=100,
            message="Indexing authors",
        )

        total_authors = session.query(func.count(AuthorDB.id)).scalar() or 0
        results["authors_indexed"] = total_authors
        await asyncio.sleep(0.1)

        # Index genres
        await ctx.report_progress(
            progress=start_progress + int(progress_range * 0.9),
            total=100,
            message="Indexing genres",
        )

        unique_genres = session.query(func.count(func.distinct(BookDB.genre))).scalar() or 0
        results["genres_indexed"] = unique_genres
        await asyncio.sleep(0.1)

        await ctx.report_progress(
            progress=end_progress, total=100, message="Search indexes rebuilt"
        )

    await ctx.info(f"Indexed {total_books} books, {total_authors} authors, {unique_genres} genres")
    return results


async def _update_circulation_stats(
    ctx: Context, start_progress: int, end_progress: int
) -> dict[str, Any]:
    """Update circulation statistics with progress reporting."""
    results = {
        "active_loans": 0,
        "overdue_loans": 0,
        "total_circulations": 0,
        "popular_books_updated": 0,
    }

    with session_scope() as session:
        repo = CirculationRepository(session)

        # Count active and overdue loans from circulation statistics
        await ctx.report_progress(
            progress=start_progress + 5, total=100, message="Counting active loans"
        )

        stats = repo.get_circulation_stats()
        results["active_loans"] = stats.active_checkouts

        await ctx.report_progress(
            progress=start_progress + 10, total=100, message="Checking for overdue loans"
        )

        results["overdue_loans"] = stats.overdue_checkouts

        if results["overdue_loans"] > 0:
            await ctx.warning(f"Found {results['overdue_loans']} overdue loans")

        # Update total circulation count
        await ctx.report_progress(
            progress=start_progress + 20, total=100, message="Updating circulation totals"
        )

        total_circs = session.query(func.count(CheckoutRecord.id)).scalar() or 0
        results["total_circulations"] = total_circs

        # Simulate updating popular books cache
        await ctx.report_progress(
            progress=end_progress - 5, total=100, message="Updating popular books cache"
        )

        # In a real system, this would update a cache table
        results["popular_books_updated"] = 50  # Simulate top 50 books
        await asyncio.sleep(0.2)

        await ctx.report_progress(
            progress=end_progress, total=100, message="Circulation statistics updated"
        )

    return results


async def _generate_recommendations_cache(
    ctx: Context, start_progress: int, end_progress: int
) -> dict[str, Any]:
    """Generate recommendations cache with progress reporting."""
    results = {"patrons_processed": 0, "recommendations_generated": 0, "cache_size_kb": 0}

    with session_scope() as session:
        patron_repo = PatronRepository(session)

        # Get all patrons (paged API; one page is plenty for this library)
        all_patrons = patron_repo.get_all(pagination=PaginationParams(page=1, page_size=100))
        total_patrons = len(all_patrons.items)

        # Process patrons in batches
        batch_size = 10
        progress_range = end_progress - start_progress
        recommendations_count = 0

        for i in range(0, total_patrons, batch_size):
            batch_end = min(i + batch_size, total_patrons)
            batch = all_patrons.items[i:batch_end]

            progress = start_progress + int((i / total_patrons) * progress_range)

            await ctx.report_progress(
                progress=progress,
                total=100,
                message=f"Generating recommendations for patrons {i + 1}-{batch_end}/{total_patrons}",
            )

            # Simulate recommendation generation
            for _ in batch:
                # In a real system, this would generate actual recommendations
                recommendations_count += 5  # Assume 5 recommendations per patron

            await asyncio.sleep(0.1)  # Simulate processing time

        results["patrons_processed"] = total_patrons
        results["recommendations_generated"] = recommendations_count
        results["cache_size_kb"] = recommendations_count * 2  # Estimate 2KB per recommendation

        await ctx.report_progress(
            progress=end_progress, total=100, message="Recommendations cache generated"
        )

        await ctx.info(
            f"Generated {recommendations_count} recommendations for {total_patrons} patrons"
        )

    return results
