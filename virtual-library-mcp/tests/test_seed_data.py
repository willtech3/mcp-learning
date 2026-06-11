"""
Integrity tests for the curated seed catalog and the seeding pipeline.

The catalog is hand-curated JSON, so these tests are the safety net that
keeps a typo'd date or rogue genre from ever reaching a seeded database:

1. Every curated author/book must satisfy the same Pydantic models the MCP
   resources serve, so anything the seeder writes is something the API can read.
2. The full seed pipeline must produce an internally consistent database —
   availability, checkout counts, and fines all derived from the same records.
"""

import json
import sqlite3

import pytest

from database.seed import (
    author_id_for,
    build_authors_and_books,
    isbn13_for,
    isbn_check_digit,
    load_catalog,
    seed_database,
)
from models.author import Author as AuthorModel
from models.book import Book as BookModel

# The genre vocabulary used across the curated catalog. Title-case stable
# (Book.normalize_genre runs str.title()) and apostrophe-free by design.
EXPECTED_GENRES = {
    "Fiction",
    "Historical Fiction",
    "Science Fiction",
    "Fantasy",
    "Dystopian",
    "Mystery",
    "Thriller",
    "Horror",
    "Romance",
    "Adventure",
    "Young Adult",
    "Children",
    "Biography",
    "Memoir",
    "History",
    "Science",
    "Psychology",
    "Philosophy",
    "Self-Help",
    "Business",
    "Poetry",
    "Drama",
    "True Crime",
    "Essays",
}


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def test_catalog_is_substantial(catalog):
    """The library should feel like a library, not a test fixture."""
    books = [b for a in catalog for b in a["books"]]
    assert len(catalog) >= 150
    assert len(books) >= 300


def test_every_author_validates_against_model(catalog):
    used_ids: set[str] = set()
    for entry in catalog:
        author = AuthorModel(
            id=author_id_for(entry["name"], used_ids),
            name=entry["name"],
            biography=entry.get("biography"),
            birth_date=entry.get("birth_date"),
            death_date=entry.get("death_date"),
            nationality=entry.get("nationality"),
        )
        assert author.name == entry["name"]


def test_every_book_validates_against_model(catalog):
    used_isbns: set[str] = set()
    used_ids: set[str] = set()
    for entry in catalog:
        author_id = author_id_for(entry["name"], used_ids)
        for book in entry["books"]:
            model = BookModel(
                isbn=isbn13_for(book["title"], entry["name"], used_isbns),
                title=book["title"],
                author_id=author_id,
                genre=book["genre"],
                publication_year=book["year"],
                total_copies=1,
                available_copies=1,
                description=book["description"],
            )
            assert model.title == book["title"]


def test_genres_use_known_vocabulary(catalog):
    """Catch genre typos that would fragment by-genre browsing."""
    seen = {b["genre"] for a in catalog for b in a["books"]}
    unknown = seen - EXPECTED_GENRES
    assert not unknown, f"unexpected genres in catalog: {unknown}"


def test_popularity_in_range(catalog):
    for entry in catalog:
        for book in entry["books"]:
            assert 1 <= book.get("popularity", 2) <= 5, book["title"]


def test_no_duplicate_books(catalog):
    keys = [(b["title"], a["name"]) for a in catalog for b in a["books"]]
    assert len(keys) == len(set(keys)), "duplicate title+author pair in catalog"


def test_isbns_are_unique_and_checksum_valid(catalog):
    _authors, books = build_authors_and_books(catalog)
    isbns = [b.isbn for b in books]
    assert len(isbns) == len(set(isbns))
    for isbn in isbns:
        assert len(isbn) == 13
        assert isbn.startswith("978")
        assert isbn[12] == isbn_check_digit(isbn[:12])


@pytest.mark.slow
def test_seed_database_end_to_end(tmp_path):
    """Seed a real database file and verify cross-table consistency in SQL."""
    db_path = tmp_path / "seeded.db"
    seed_database(f"sqlite:///{db_path}")

    conn = sqlite3.connect(db_path)
    try:
        # Book availability must equal total copies minus open checkouts.
        drift = conn.execute(
            """
            SELECT COUNT(*) FROM books b
            WHERE b.available_copies != b.total_copies - (
                SELECT COUNT(*) FROM checkout_records c
                WHERE c.book_isbn = b.isbn AND c.return_date IS NULL
            )
            """
        ).fetchone()[0]
        assert drift == 0

        # Patron aggregates must match their checkout records.
        mismatched = conn.execute(
            """
            SELECT COUNT(*) FROM patrons p
            WHERE p.current_checkouts != (
                SELECT COUNT(*) FROM checkout_records c
                WHERE c.patron_id = p.id AND c.return_date IS NULL
            )
            OR p.total_checkouts != (
                SELECT COUNT(*) FROM checkout_records c WHERE c.patron_id = p.id
            )
            """
        ).fetchone()[0]
        assert mismatched == 0

        # Preferred genres are stored as parseable JSON arrays.
        for (raw,) in conn.execute(
            "SELECT preferred_genres FROM patrons WHERE preferred_genres IS NOT NULL"
        ):
            assert isinstance(json.loads(raw), list)

        # Reservations only exist for books with no available copies.
        bad_reservations = conn.execute(
            """
            SELECT COUNT(*) FROM reservation_records r
            JOIN books b ON b.isbn = r.book_isbn
            WHERE r.status = 'PENDING' AND b.available_copies > 0
            """
        ).fetchone()[0]
        assert bad_reservations == 0
    finally:
        conn.close()
