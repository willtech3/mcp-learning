"""Bulk import tool for loading books from CSV or JSON files.

This module demonstrates MCP progress notifications by providing real-time
updates during large-scale import operations.

Security note: imports are confined to the server's data/ directory. A
remote MCP client must never be able to point a file-reading tool at an
arbitrary filesystem path (path traversal), so every requested path is
resolved and checked against the allowed root before opening.
"""

import csv
import json
import logging
import time
from pathlib import Path
from typing import Annotated, Any

import anyio
from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field
from sqlalchemy.exc import IntegrityError

from database.schema import Author as AuthorDB
from database.schema import Book as BookDB
from database.session import session_scope

logger = logging.getLogger(__name__)

# Only files under the project's data/ directory may be imported.
ALLOWED_IMPORT_ROOT = (Path(__file__).parent.parent / "data").resolve()


def _confine_to_import_root(file_path: str) -> Path:
    """Resolve a user-supplied path and require it to live under data/.

    Rejects absolute paths outside the root and ../ traversal. Relative
    paths are interpreted relative to the import root for convenience.
    """
    candidate = Path(file_path)
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (ALLOWED_IMPORT_ROOT / candidate).resolve()
    )
    if not resolved.is_relative_to(ALLOWED_IMPORT_ROOT):
        raise ToolError(
            f"Import files must live under the server's data directory "
            f"({ALLOWED_IMPORT_ROOT}). Got: {file_path}"
        )
    return resolved


def _format_eta(seconds: float) -> str:
    """Format ETA in human-readable format."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        minutes = int(seconds / 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    hours = int(seconds / 3600)
    minutes = int((seconds % 3600) / 60)
    return f"{hours}h {minutes}m"


async def bulk_import_books(
    file_path: Annotated[
        str,
        Field(
            description=(
                "Path to a CSV or JSON file under the server's data/ directory, "
                "e.g. 'samples/books_sample.csv'"
            ),
            min_length=1,
        ),
    ],
    ctx: Context,
    batch_size: Annotated[int, Field(description="Books to process per batch", ge=1, le=1000)] = 50,
) -> dict[str, Any]:
    """Import books in bulk from a CSV or JSON file, with live progress.

    CSV headers: isbn, title, author_name, genre, publication_year,
    available_copies. JSON: an array of objects with the same fields.
    Progress notifications stream batch-by-batch with an ETA.
    """
    path = _confine_to_import_root(file_path)

    # anyio.Path performs the stat in a worker thread, keeping the event loop free.
    if not await anyio.Path(path).exists():
        raise ToolError(f"Import file not found: {file_path}")

    file_type = path.suffix.lower()
    if file_type not in [".csv", ".json"]:
        raise ToolError(f"Unsupported file type: {file_type}. Use .csv or .json")

    await ctx.info(f"Starting import from {path.name}")

    # Read and parse the file
    books_data = _read_csv_file(path) if file_type == ".csv" else _read_json_file(path)

    total_books = len(books_data)
    await ctx.info(f"Found {total_books} books to import")

    # Process books in batches
    successful = 0
    failed = 0
    errors = []
    start_time = time.time()

    with session_scope() as session:
        for i in range(0, total_books, batch_size):
            batch = books_data[i : i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total_books + batch_size - 1) // batch_size

            await ctx.info(f"Processing batch {batch_num}/{total_batches}")

            for j, book_data in enumerate(batch):
                current_book = i + j + 1

                # Calculate ETA
                elapsed_time = time.time() - start_time
                if current_book > 1 and elapsed_time > 0:
                    avg_time_per_book = elapsed_time / (current_book - 1)
                    remaining_books = total_books - current_book + 1
                    eta_seconds = avg_time_per_book * remaining_books
                    eta_str = f" - ETA: {_format_eta(eta_seconds)}"
                else:
                    eta_str = ""

                # Report progress with ETA
                await ctx.report_progress(
                    progress=current_book,
                    total=total_books,
                    message=f"Importing book {current_book}/{total_books}{eta_str}",
                )

                try:
                    # Each book gets its own SAVEPOINT so one bad row
                    # (e.g. duplicate ISBN) can't poison the whole batch.
                    with session.begin_nested():
                        _create_book_in_db(session, book_data)
                    successful += 1

                except ValueError as e:
                    failed += 1
                    error_msg = f"Book {current_book}: Validation error - {e!s}"
                    errors.append(error_msg)
                    await ctx.warning(error_msg)

                except IntegrityError:
                    failed += 1
                    error_msg = f"Book {current_book}: Database error - Book may already exist"
                    errors.append(error_msg)
                    await ctx.warning(error_msg)

                except Exception as e:
                    failed += 1
                    error_msg = f"Book {current_book}: Unexpected error - {e!s}"
                    errors.append(error_msg)
                    await ctx.error(error_msg)

            # Commit batch
            try:
                session.commit()
                await ctx.debug(f"Committed batch {batch_num}")
            except Exception as e:
                session.rollback()
                batch_failed = len(batch)
                failed += batch_failed
                successful -= batch_failed
                error_msg = f"Failed to commit batch {batch_num}: {e!s}"
                errors.append(error_msg)
                await ctx.error(error_msg)

    # Final progress report
    await ctx.report_progress(progress=total_books, total=total_books, message="Import completed")

    # Generate summary
    summary = {
        "total_books": total_books,
        "successful_imports": successful,
        "failed_imports": failed,
        "success_rate": f"{(successful / total_books) * 100:.1f}%" if total_books > 0 else "0%",
        "errors": errors[:10] if errors else [],  # Limit errors in response
        "errors_truncated": len(errors) > 10,
    }

    if failed > 0:
        await ctx.warning(f"Import completed with {failed} errors")
    else:
        await ctx.info("Import completed successfully")

    return summary


def _read_csv_file(path: Path) -> list[dict[str, Any]]:
    """Read books data from a CSV file."""
    books = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert year to int if present
            if row.get("publication_year"):
                try:
                    row["publication_year"] = int(row["publication_year"])
                except ValueError:
                    pass

            # Convert available_copies to int if present
            if row.get("available_copies"):
                try:
                    row["available_copies"] = int(row["available_copies"])
                except ValueError:
                    row["available_copies"] = 1
            else:
                row["available_copies"] = 1

            books.append(row)
    return books


def _read_json_file(path: Path) -> list[dict[str, Any]]:
    """Read books data from a JSON file."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise TypeError("JSON file must contain an array of book objects")

    return data


def _create_book_in_db(session, data: dict[str, Any]) -> None:
    """Create a book in the database, handling author creation/lookup."""
    # Handle author name variations
    author_name = (
        data.get("author_name") or data.get("author") or data.get("authors", "Unknown Author")
    )

    # Ensure required fields
    if not data.get("isbn"):
        raise ValueError("ISBN is required")
    if not data.get("title"):
        raise ValueError("Title is required")

    # Find or create author
    author = session.query(AuthorDB).filter_by(name=author_name).first()
    if not author:
        # Create a simple author ID based on the name
        author_id = f"author_{author_name.lower().replace(' ', '_')[:20]}"
        # Check if this ID already exists
        existing = session.query(AuthorDB).filter_by(id=author_id).first()
        if existing:
            # Add a number suffix to make it unique
            counter = 1
            while session.query(AuthorDB).filter_by(id=f"{author_id}_{counter}").first():
                counter += 1
            author_id = f"{author_id}_{counter}"

        author = AuthorDB(
            id=author_id,
            name=author_name,
            biography=f"Author of {data.get('title', 'various works')}",
        )
        session.add(author)
        session.flush()  # Ensure author ID is available

    # Create the book
    book = BookDB(
        isbn=data["isbn"].replace("-", ""),  # Normalize ISBN
        title=data["title"],
        author_id=author.id,
        genre=data.get("genre", "General"),
        publication_year=data.get("publication_year"),
        available_copies=data.get("available_copies", 1),
        total_copies=data.get("total_copies", data.get("available_copies", 1)),
        description=data.get("description"),
    )
    session.add(book)
