"""Bulk import tool for loading books from CSV or JSON files.

This module demonstrates MCP progress notifications by providing real-time
updates during large-scale import operations.
"""

import csv
import json
import logging
from pathlib import Path
from typing import Any

from fastmcp import Context
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from database.schema import Author as AuthorDB, Book as BookDB
from database.session import session_scope

logger = logging.getLogger(__name__)


class BulkImportInput(BaseModel):
    """Input schema for the bulk_import_books tool."""
    
    file_path: str = Field(
        description="Path to the CSV or JSON file containing books to import",
        min_length=1,
        examples=["/tmp/books.csv", "/data/import/catalog.json"]
    )
    
    batch_size: int = Field(
        default=50,
        description="Number of books to process in each batch",
        ge=1,
        le=1000
    )


async def import_books_from_file(
    file_path: str, ctx: Context, batch_size: int = 50
) -> dict[str, Any]:
    """Import books from a CSV or JSON file with progress reporting.
    
    Supports CSV files with headers:
    - isbn, title, author_name, genre, publication_year, available_copies
    
    Or JSON files with an array of book objects.
    
    Args:
        file_path: Path to the import file
        batch_size: Number of books to process in each batch
        ctx: MCP context for progress reporting
        
    Returns:
        Import summary with counts and any errors
    """
    # Validate file exists and determine type
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Import file not found: {file_path}")
    
    file_type = path.suffix.lower()
    if file_type not in ['.csv', '.json']:
        raise ValueError(f"Unsupported file type: {file_type}. Use .csv or .json")
    
    await ctx.info(f"Starting import from {path.name}")
    
    # Read and parse the file
    if file_type == '.csv':
        books_data = _read_csv_file(path)
    else:
        books_data = _read_json_file(path)
    
    total_books = len(books_data)
    await ctx.info(f"Found {total_books} books to import")
    
    # Process books in batches
    successful = 0
    failed = 0
    errors = []
    
    with session_scope() as session:
        
        for i in range(0, total_books, batch_size):
            batch = books_data[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total_books + batch_size - 1) // batch_size
            
            await ctx.info(f"Processing batch {batch_num}/{total_batches}")
            
            for j, book_data in enumerate(batch):
                current_book = i + j + 1
                
                # Report progress
                await ctx.report_progress(
                    progress=current_book,
                    total=total_books,
                    message=f"Importing book {current_book}/{total_books}"
                )
                
                try:
                    # Validate and create book
                    _create_book_in_db(session, book_data, current_book)
                    successful += 1
                    
                except ValueError as e:
                    failed += 1
                    error_msg = f"Book {current_book}: Validation error - {str(e)}"
                    errors.append(error_msg)
                    await ctx.warning(error_msg)
                    
                except IntegrityError as e:
                    failed += 1
                    error_msg = f"Book {current_book}: Database error - Book may already exist"
                    errors.append(error_msg)
                    await ctx.warning(error_msg)
                    session.rollback()
                    
                except Exception as e:
                    failed += 1
                    error_msg = f"Book {current_book}: Unexpected error - {str(e)}"
                    errors.append(error_msg)
                    await ctx.error(error_msg)
                    session.rollback()
            
            # Commit batch
            try:
                session.commit()
                await ctx.debug(f"Committed batch {batch_num}")
            except Exception as e:
                session.rollback()
                batch_failed = len(batch)
                failed += batch_failed
                successful -= batch_failed
                error_msg = f"Failed to commit batch {batch_num}: {str(e)}"
                errors.append(error_msg)
                await ctx.error(error_msg)
    
    # Final progress report
    await ctx.report_progress(
        progress=total_books,
        total=total_books,
        message="Import completed"
    )
    
    # Generate summary
    summary = {
        "total_books": total_books,
        "successful_imports": successful,
        "failed_imports": failed,
        "success_rate": f"{(successful/total_books)*100:.1f}%" if total_books > 0 else "0%",
        "errors": errors[:10] if errors else []  # Limit errors in response
    }
    
    if failed > 0:
        await ctx.warning(f"Import completed with {failed} errors")
    else:
        await ctx.info("Import completed successfully")
    
    return summary


def _read_csv_file(path: Path) -> list[dict[str, Any]]:
    """Read books data from a CSV file."""
    books = []
    with open(path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert year to int if present
            if 'publication_year' in row and row['publication_year']:
                try:
                    row['publication_year'] = int(row['publication_year'])
                except ValueError:
                    pass
            
            # Convert available_copies to int if present
            if 'available_copies' in row and row['available_copies']:
                try:
                    row['available_copies'] = int(row['available_copies'])
                except ValueError:
                    row['available_copies'] = 1
            else:
                row['available_copies'] = 1
                
            books.append(row)
    return books


def _read_json_file(path: Path) -> list[dict[str, Any]]:
    """Read books data from a JSON file."""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    if not isinstance(data, list):
        raise ValueError("JSON file must contain an array of book objects")
        
    return data


def _create_book_in_db(session, data: dict[str, Any], book_num: int) -> None:
    """Create a book in the database, handling author creation/lookup."""
    # Handle author name variations
    author_name = (
        data.get('author_name') or 
        data.get('author') or 
        data.get('authors', 'Unknown Author')
    )
    
    # Ensure required fields
    if not data.get('isbn'):
        raise ValueError(f"ISBN is required")
    if not data.get('title'):
        raise ValueError(f"Title is required")
    
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
            biography=f"Author of {data.get('title', 'various works')}"
        )
        session.add(author)
        session.flush()  # Ensure author ID is available
    
    # Create the book
    book = BookDB(
        isbn=data['isbn'].replace('-', ''),  # Normalize ISBN
        title=data['title'],
        author_id=author.id,
        genre=data.get('genre', 'General'),
        publication_year=data.get('publication_year'),
        available_copies=data.get('available_copies', 1),
        total_copies=data.get('total_copies', data.get('available_copies', 1)),
        description=data.get('description')
    )
    session.add(book)


async def bulk_import_books_handler(arguments: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """Handler for the bulk_import_books tool.
    
    Accepts file path and batch size, performs import with progress notifications.
    """
    try:
        # Validate input
        try:
            params = BulkImportInput.model_validate(arguments)
        except Exception as e:
            logger.warning("Invalid import parameters: %s", e)
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Invalid import parameters: {e}"}],
            }
        
        # Execute import
        try:
            result = await import_books_from_file(
                file_path=params.file_path,
                ctx=ctx,
                batch_size=params.batch_size
            )
            
            # Format successful response
            summary_text = (
                f"Import completed: {result['successful_imports']}/{result['total_books']} "
                f"books imported successfully ({result['success_rate']})"
            )
            
            if result['failed_imports'] > 0:
                summary_text += f"\n{result['failed_imports']} imports failed."
                if result['errors']:
                    summary_text += "\nFirst few errors:\n" + "\n".join(result['errors'][:5])
            
            return {
                "content": [{"type": "text", "text": summary_text}],
                "data": result
            }
            
        except FileNotFoundError as e:
            return {
                "isError": True,
                "content": [{"type": "text", "text": str(e)}],
            }
        except ValueError as e:
            return {
                "isError": True,
                "content": [{"type": "text", "text": str(e)}],
            }
        except Exception as e:
            logger.exception("Import execution failed")
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Import failed: {e!s}"}],
            }
            
    except Exception as e:
        logger.exception("Unexpected error in bulk_import_books tool")
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"An unexpected error occurred: {e!s}"}],
        }


bulk_import_books = {
    "name": "bulk_import_books",
    "description": (
        "Import books from a CSV or JSON file with real-time progress updates. "
        "CSV files should have headers: isbn, title, author_name, genre, "
        "publication_year, available_copies. JSON files should contain an array "
        "of book objects. Validates data, processes in batches, and reports errors."
    ),
    "inputSchema": BulkImportInput.model_json_schema(),
    "handler": bulk_import_books_handler,
}