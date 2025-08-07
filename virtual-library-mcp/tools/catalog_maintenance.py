"""Catalog maintenance tool for regenerating indexes and statistics.

This module demonstrates multi-stage progress notifications during
long-running maintenance operations.
"""

import asyncio
import logging
from typing import Any

from fastmcp import Context
from sqlalchemy import func

from database.circulation_repository import CirculationRepository
from database.patron_repository import PatronRepository
from database.schema import Author as AuthorDB
from database.schema import Book as BookDB
from database.schema import CheckoutRecord
from database.session import session_scope
# Observability is handled by middleware, not decorators

logger = logging.getLogger(__name__)


async def regenerate_catalog(ctx: Context) -> dict[str, Any]:
    """Regenerate catalog indexes and statistics with progress reporting.

    This simulates a multi-stage maintenance operation:
    1. Verify data integrity (0-20%)
    2. Rebuild search indexes (20-50%)
    3. Update circulation statistics (50-80%)
    4. Generate recommendations cache (80-100%)

    Args:
        ctx: MCP context for progress reporting

    Returns:
        Maintenance summary with statistics
    """
    await ctx.info("Starting catalog regeneration")

    # Stage 1: Verify data integrity (0-20%)
    await ctx.info("Stage 1: Verifying data integrity")
    integrity_results = await _verify_data_integrity(ctx, 0, 20)

    # Stage 2: Rebuild search indexes (20-50%)
    await ctx.info("Stage 2: Rebuilding search indexes")
    index_results = await _rebuild_search_indexes(ctx, 20, 50)

    # Stage 3: Update circulation statistics (50-80%)
    await ctx.info("Stage 3: Updating circulation statistics")
    stats_results = await _update_circulation_stats(ctx, 50, 80)

    # Stage 4: Generate recommendations cache (80-100%)
    await ctx.info("Stage 4: Generating recommendations cache")
    cache_results = await _generate_recommendations_cache(ctx, 80, 100)

    # Final completion
    await ctx.report_progress(progress=100, total=100, message="Catalog regeneration complete")
    await ctx.info("Catalog regeneration completed successfully")

    return {
        "status": "completed",
        "integrity_check": integrity_results,
        "search_indexes": index_results,
        "circulation_stats": stats_results,
        "recommendations_cache": cache_results,
        "message": "Catalog regeneration completed successfully",
    }


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

        # Count active loans
        await ctx.report_progress(
            progress=start_progress + 5, total=100, message="Counting active loans"
        )

        active_loans = repo.get_active_loans()
        results["active_loans"] = len(active_loans)

        # Count overdue loans
        await ctx.report_progress(
            progress=start_progress + 10, total=100, message="Checking for overdue loans"
        )

        overdue_loans = repo.get_overdue_loans()
        results["overdue_loans"] = len(overdue_loans)

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

        # Get all active patrons
        all_patrons = patron_repo.list(limit=1000)
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


async def regenerate_catalog_handler(_: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """Handler for the regenerate_catalog tool.

    No input parameters needed - performs full catalog maintenance.
    """
    try:
        # Execute catalog regeneration
        result = await regenerate_catalog(ctx)

        # Format response
        summary_lines = [
            "Catalog regeneration completed successfully!",
            "",
            f"✓ Data Integrity: {result['integrity_check']['books_checked']} books checked",
        ]

        if result["integrity_check"]["orphaned_books"] > 0:
            summary_lines.append(
                f"  ⚠ {result['integrity_check']['orphaned_books']} orphaned books found"
            )
        if result["integrity_check"]["invalid_circulations"] > 0:
            summary_lines.append(
                f"  ⚠ {result['integrity_check']['invalid_circulations']} invalid circulations found"
            )

        summary_lines.extend(
            [
                "",
                f"✓ Search Indexes: {result['search_indexes']['books_indexed']} books, "
                f"{result['search_indexes']['authors_indexed']} authors, "
                f"{result['search_indexes']['genres_indexed']} genres indexed",
                "",
                f"✓ Circulation Stats: {result['circulation_stats']['active_loans']} active loans, "
                f"{result['circulation_stats']['overdue_loans']} overdue",
                "",
                f"✓ Recommendations: Generated for {result['recommendations_cache']['patrons_processed']} patrons "
                f"({result['recommendations_cache']['recommendations_generated']} total recommendations)",
            ]
        )

        return {"content": [{"type": "text", "text": "\n".join(summary_lines)}], "data": result}

    except Exception as e:
        logger.exception("Unexpected error in regenerate_catalog tool")
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Catalog regeneration failed: {e!s}"}],
        }


regenerate_catalog_tool = {
    "name": "regenerate_catalog",
    "description": (
        "Perform comprehensive catalog maintenance with progress tracking. "
        "This includes: data integrity checks, search index rebuilding, "
        "circulation statistics updates, and recommendation cache generation. "
        "Progress is reported in real-time through multiple stages."
    ),
    "inputSchema": {"type": "object", "properties": {}, "required": []},
    "handler": regenerate_catalog_handler,
}
