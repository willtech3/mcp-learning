"""
Tests for the Book model.

These tests verify that the Book model correctly:
1. Validates input data according to MCP requirements
2. Serializes to/from JSON for protocol compliance
3. Handles edge cases and invalid data appropriately
4. Maintains data integrity through its methods
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.models.book import Book


class TestBookModel:
    """Test suite for the Book model."""

    def test_create_valid_book(self):
        """Test creating a book with valid data."""
        book = Book(
            isbn="978-0-134-68547-9",
            title="The Great Gatsby",
            author_id="author_fitzgerald01",
            genre="Fiction",
            publication_year=1925,
            available_copies=2,
            total_copies=3,
            description="A classic American novel",
            cover_url="https://example.com/cover.jpg",
        )

        assert book.isbn == "9780134685479"  # Normalized without hyphens
        assert book.title == "The Great Gatsby"
        assert book.author_id == "author_fitzgerald01"
        assert book.genre == "Fiction"
        assert book.publication_year == 1925
        assert book.available_copies == 2
        assert book.total_copies == 3
        assert book.is_available is True
        assert book.checked_out_copies == 1

    def test_isbn_normalization(self):
        """Test that ISBNs are normalized by removing hyphens."""
        book1 = Book(
            isbn="978-0-134-68547-9",
            title="Test Book",
            author_id="author_test12345",
            genre="Fiction",
            publication_year=2020,
            total_copies=1,
        )

        book2 = Book(
            isbn="9780134685479",
            title="Test Book",
            author_id="author_test12345",
            genre="Fiction",
            publication_year=2020,
            total_copies=1,
        )

        assert book1.isbn == book2.isbn == "9780134685479"

    def test_invalid_isbn_format(self):
        """Test that invalid ISBN formats are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            Book(
                isbn="123-456",  # Too short
                title="Test Book",
                author_id="author_test12345",
                genre="Fiction",
                publication_year=2020,
                total_copies=1,
            )

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("isbn",) for error in errors)

    def test_isbn_wrong_length(self):
        """Test that ISBNs with wrong length are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            Book(
                isbn="123456789012",  # 12 digits instead of 13
                title="Test Book",
                author_id="author_test12345",
                genre="Fiction",
                publication_year=2020,
                total_copies=1,
            )

        errors = exc_info.value.errors()
        assert any("13 digits" in str(error) for error in errors)

    def test_genre_normalization(self):
        """Test that genres are normalized to title case."""
        book = Book(
            isbn="9780134685479",
            title="Test Book",
            author_id="author_test12345",
            genre="science fiction",  # lowercase
            publication_year=2020,
            total_copies=1,
        )

        assert book.genre == "Science Fiction"

    def test_publication_year_validation(self):
        """Test publication year boundaries."""
        # Valid: current year
        book = Book(
            isbn="9780134685479",
            title="Current Book",
            author_id="author_test12345",
            genre="Fiction",
            publication_year=datetime.now().year,
            total_copies=1,
        )
        assert book.publication_year == datetime.now().year

        # Valid: future year (pre-publication)
        book = Book(
            isbn="9780134685479",
            title="Future Book",
            author_id="author_test12345",
            genre="Fiction",
            publication_year=datetime.now().year + 1,
            total_copies=1,
        )
        assert book.publication_year == datetime.now().year + 1

        # Invalid: too far in future
        with pytest.raises(ValidationError):
            Book(
                isbn="9780134685479",
                title="Far Future Book",
                author_id="author_test12345",
                genre="Fiction",
                publication_year=datetime.now().year + 2,
                total_copies=1,
            )

        # Invalid: before printing press
        with pytest.raises(ValidationError):
            Book(
                isbn="9780134685479",
                title="Ancient Book",
                author_id="author_test12345",
                genre="Fiction",
                publication_year=1449,
                total_copies=1,
            )

    def test_available_copies_validation(self):
        """Test that available copies cannot exceed total copies."""
        # Valid
        book = Book(
            isbn="9780134685479",
            title="Test Book",
            author_id="author_test12345",
            genre="Fiction",
            publication_year=2020,
            available_copies=3,
            total_copies=3,
        )
        assert book.available_copies == 3

        # Invalid
        with pytest.raises(ValidationError) as exc_info:
            Book(
                isbn="9780134685479",
                title="Test Book",
                author_id="author_test12345",
                genre="Fiction",
                publication_year=2020,
                available_copies=5,
                total_copies=3,
            )

        errors = exc_info.value.errors()
        assert any("exceed total copies" in str(error) for error in errors)

    def test_checkout_method(self):
        """Test the checkout method."""
        book = Book(
            isbn="9780134685479",
            title="Test Book",
            author_id="author_test12345",
            genre="Fiction",
            publication_year=2020,
            available_copies=2,
            total_copies=3,
        )

        # Successful checkout
        book.checkout()
        assert book.available_copies == 1
        assert book.checked_out_copies == 2

        # Checkout when one copy left
        book.checkout()
        assert book.available_copies == 0
        assert book.is_available is False

        # Attempt checkout when no copies available
        with pytest.raises(ValueError, match="No copies"):
            book.checkout()

    def test_return_copy_method(self):
        """Test the return_copy method."""
        book = Book(
            isbn="9780134685479",
            title="Test Book",
            author_id="author_test12345",
            genre="Fiction",
            publication_year=2020,
            available_copies=0,
            total_copies=3,
        )

        # Return copies
        book.return_copy()
        assert book.available_copies == 1

        book.return_copy()
        book.return_copy()
        assert book.available_copies == 3

        # Attempt to return when all copies are already returned
        with pytest.raises(ValueError, match="already returned"):
            book.return_copy()

    def test_json_serialization(self):
        """Test that the model can be serialized to JSON."""
        book = Book(
            isbn="978-0-134-68547-9",
            title="The Great Gatsby",
            author_id="author_fitzgerald01",
            genre="Fiction",
            publication_year=1925,
            available_copies=2,
            total_copies=3,
            description="A classic American novel",
            cover_url="https://example.com/cover.jpg",
        )

        # Convert to JSON
        json_data = book.model_dump_json()
        assert isinstance(json_data, str)
        assert "9780134685479" in json_data  # Normalized ISBN
        assert "The Great Gatsby" in json_data

        # Convert to dict
        dict_data = book.model_dump()
        assert dict_data["isbn"] == "9780134685479"
        assert dict_data["title"] == "The Great Gatsby"
        assert dict_data["available_copies"] == 2

    def test_json_deserialization(self):
        """Test that the model can be created from JSON data."""
        json_data = {
            "isbn": "978-0-134-68547-9",
            "title": "The Great Gatsby",
            "author_id": "author_fitzgerald01",
            "genre": "Fiction",
            "publication_year": 1925,
            "available_copies": 2,
            "total_copies": 3,
            "description": "A classic American novel",
            "cover_url": "https://example.com/cover.jpg",
        }

        book = Book.model_validate(json_data)
        assert book.isbn == "9780134685479"
        assert book.title == "The Great Gatsby"
        assert book.is_available is True

    def test_optional_fields(self):
        """Test that optional fields work correctly."""
        # Minimal book without optional fields
        book = Book(
            isbn="9780134685479",
            title="Minimal Book",
            author_id="author_test12345",
            genre="Fiction",
            publication_year=2020,
            total_copies=1,
        )

        assert book.description is None
        assert book.cover_url is None
        assert book.available_copies == 1  # Default value

    def test_cover_url_validation(self):
        """Test that cover URLs must be valid image URLs."""
        # Valid URLs
        valid_urls = [
            "https://example.com/cover.jpg",
            "https://example.com/cover.jpeg",
            "https://example.com/cover.png",
            "https://example.com/cover.webp",
            "http://example.com/cover.jpg",
        ]

        for url in valid_urls:
            book = Book(
                isbn="9780134685479",
                title="Test Book",
                author_id="author_test12345",
                genre="Fiction",
                publication_year=2020,
                total_copies=1,
                cover_url=url,
            )
            assert book.cover_url == url

        # Invalid URLs
        invalid_urls = [
            "https://example.com/cover.gif",  # Wrong format
            "https://example.com/cover",  # No extension
            "not-a-url",  # Not a URL
            "ftp://example.com/cover.jpg",  # Wrong protocol
        ]

        for url in invalid_urls:
            with pytest.raises(ValidationError):
                Book(
                    isbn="9780134685479",
                    title="Test Book",
                    author_id="author_test12345",
                    genre="Fiction",
                    publication_year=2020,
                    total_copies=1,
                    cover_url=url,
                )

    def test_timestamps(self):
        """Test that timestamps are set correctly."""
        before = datetime.now()

        book = Book(
            isbn="9780134685479",
            title="Test Book",
            author_id="author_test12345",
            genre="Fiction",
            publication_year=2020,
            total_copies=1,
        )

        after = datetime.now()

        # Check that timestamps are set
        assert before <= book.created_at <= after
        assert before <= book.updated_at <= after
        assert book.created_at == book.updated_at  # Should be equal on creation
