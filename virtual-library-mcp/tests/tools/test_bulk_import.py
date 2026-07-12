"""Tests for bulk import: path confinement, parsing, and progress.

The path-confinement tests are security tests: a remote MCP client must
never be able to point this tool at an arbitrary server path.
"""

import csv
import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import server
import tools.bulk_import as bulk_import_module
from database.schema import Book as BookDB


@pytest.fixture
def import_root(tmp_path, monkeypatch, library):
    """Point the allowed import root at a temp directory."""
    root = tmp_path.resolve()
    monkeypatch.setattr(bulk_import_module, "ALLOWED_IMPORT_ROOT", root)
    return root


def _write_csv(path, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "isbn",
                "title",
                "author_name",
                "genre",
                "publication_year",
                "available_copies",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


SAMPLE_ROWS = [
    {
        "isbn": "9781111111111",
        "title": "Imported Book One",
        "author_name": "New Author",
        "genre": "Fiction",
        "publication_year": 2020,
        "available_copies": 2,
    },
    {
        "isbn": "9782222222222",
        "title": "Imported Book Two",
        "author_name": "New Author",
        "genre": "Science",
        "publication_year": 2021,
        "available_copies": 1,
    },
]


class TestPathConfinement:
    async def test_absolute_path_outside_root_rejected(self, import_root):
        async with Client(server.mcp) as client:
            with pytest.raises(ToolError, match="data directory"):
                await client.call_tool("bulk_import_books", {"file_path": "/etc/hosts"})

    async def test_traversal_outside_root_rejected(self, import_root):
        async with Client(server.mcp) as client:
            with pytest.raises(ToolError, match="data directory"):
                await client.call_tool("bulk_import_books", {"file_path": "../../../etc/passwd"})

    async def test_missing_file_inside_root_is_clean_error(self, import_root):
        async with Client(server.mcp) as client:
            with pytest.raises(ToolError, match="not found"):
                await client.call_tool("bulk_import_books", {"file_path": "nope.csv"})

    async def test_unsupported_extension_rejected(self, import_root):
        (import_root / "books.xml").write_text("<books/>")
        async with Client(server.mcp) as client:
            with pytest.raises(ToolError, match="Unsupported file type"):
                await client.call_tool("bulk_import_books", {"file_path": "books.xml"})


class TestImportBehavior:
    async def test_csv_import_creates_books_and_authors(self, import_root, library):
        _write_csv(import_root / "books.csv", SAMPLE_ROWS)

        async with Client(server.mcp) as client:
            result = await client.call_tool("bulk_import_books", {"file_path": "books.csv"})

        data = result.structured_content
        assert data["successful_imports"] == 2
        assert data["failed_imports"] == 0
        assert library.get(BookDB, "9781111111111").title == "Imported Book One"

    async def test_json_import_with_relative_path(self, import_root, library):
        (import_root / "books.json").write_text(json.dumps(SAMPLE_ROWS))

        async with Client(server.mcp) as client:
            result = await client.call_tool("bulk_import_books", {"file_path": "books.json"})

        assert result.structured_content["successful_imports"] == 2

    async def test_duplicate_isbn_counts_as_failure(self, import_root, library):
        rows = [dict(SAMPLE_ROWS[0]), dict(SAMPLE_ROWS[0])]  # same ISBN twice
        _write_csv(import_root / "dupes.csv", rows)

        async with Client(server.mcp) as client:
            result = await client.call_tool("bulk_import_books", {"file_path": "dupes.csv"})

        data = result.structured_content
        assert data["successful_imports"] == 1
        assert data["failed_imports"] == 1

    async def test_progress_notifications_emitted(self, import_root, library):
        _write_csv(import_root / "books.csv", SAMPLE_ROWS)
        updates: list[tuple] = []

        async def on_progress(progress, total, message):
            updates.append((progress, total, message))

        async with Client(server.mcp) as client:
            await client.call_tool(
                "bulk_import_books",
                {"file_path": "books.csv"},
                progress_handler=on_progress,
            )

        assert updates, "expected progress notifications during import"
        final = updates[-1]
        assert final[0] == final[1]  # progress == total at completion
