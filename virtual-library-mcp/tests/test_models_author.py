"""
Tests for the Author model.

These tests verify that the Author model correctly:
1. Validates biographical and relationship data
2. Handles book associations properly
3. Calculates derived properties correctly
4. Maintains data integrity
"""

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from models.author import Author


class TestAuthorModel:
    """Test suite for the Author model."""

    def test_create_valid_author(self):
        """Test creating an author with valid data."""
        author = Author(
            id="author_fitzgerald01",
            name="F. Scott Fitzgerald",
            biography="American novelist of the Jazz Age",
            birth_date=date(1896, 9, 24),
            death_date=date(1940, 12, 21),
            nationality="American",
            book_ids=["978-0-134-68547-9", "9780743273565"],
            photo_url="https://example.com/fitzgerald.jpg",
            website="https://www.fscottfitzgerald.org/",
        )

        assert author.id == "author_fitzgerald01"
        assert author.name == "F. Scott Fitzgerald"
        assert author.nationality == "American"
        assert author.book_ids == ["9780134685479", "9780743273565"]  # Normalized
        assert author.is_living is False
        assert author.book_count == 2

    def test_author_id_validation(self):
        """Test that author IDs follow the required pattern."""
        # Valid IDs
        valid_ids = [
            "author_smith001",
            "author_doe_jane",
            "author_fitzgerald01",
            "author_12345678",
            "author_00001",  # 5 digits (minimum allowed)
            "author_12345",  # 5 characters exactly
        ]

        for author_id in valid_ids:
            author = Author(
                id=author_id,
                name="Test Author",
            )
            assert author.id == author_id

        # Invalid IDs
        invalid_ids = [
            "smith001",  # Missing prefix
            "author_123",  # Too short (less than 5 chars after prefix)
            "AUTHOR_smith001",  # Wrong case
            "author-smith001",  # Wrong separator
        ]

        for author_id in invalid_ids:
            with pytest.raises(ValidationError):
                Author(id=author_id, name="Test Author")

    def test_living_author(self):
        """Test properties for a living author."""
        author = Author(
            id="author_king01",
            name="Stephen King",
            birth_date=date(1947, 9, 21),
            nationality="American",
        )

        assert author.is_living is True
        assert author.death_date is None
        assert author.age is not None
        assert author.age >= 76  # Born in 1947

    def test_deceased_author(self):
        """Test properties for a deceased author."""
        author = Author(
            id="author_fitzgerald01",
            name="F. Scott Fitzgerald",
            birth_date=date(1896, 9, 24),
            death_date=date(1940, 12, 21),
        )

        assert author.is_living is False
        assert author.age == 44  # Age at death

    def test_age_calculation(self):
        """Test accurate age calculation."""
        # Test with specific dates
        author = Author(
            id="author_test01",
            name="Test Author",
            birth_date=date(1980, 6, 15),
            death_date=date(2020, 6, 14),  # Day before birthday
        )
        assert author.age == 39  # Not yet 40

        author = Author(
            id="author_test02",
            name="Test Author",
            birth_date=date(1980, 6, 15),
            death_date=date(2020, 6, 15),  # On birthday
        )
        assert author.age == 40

        # Test without death date (living author)
        today = date.today()
        author = Author(
            id="author_test03",
            name="Test Author",
            birth_date=date(today.year - 30, today.month, today.day),
        )
        assert author.age == 30

    def test_date_validation(self):
        """Test birth and death date validation."""
        # Death date before birth date
        with pytest.raises(ValidationError) as exc_info:
            Author(
                id="author_test01",
                name="Test Author",
                birth_date=date(1900, 1, 1),
                death_date=date(1899, 12, 31),
            )
        assert "before birth date" in str(exc_info.value)

        # Future dates
        future_date = date.today().replace(year=date.today().year + 1)

        with pytest.raises(ValidationError) as exc_info:
            Author(
                id="author_test01",
                name="Test Author",
                birth_date=future_date,
            )
        assert "future" in str(exc_info.value)

        with pytest.raises(ValidationError) as exc_info:
            Author(
                id="author_test01",
                name="Test Author",
                birth_date=date(1900, 1, 1),
                death_date=future_date,
            )
        assert "future" in str(exc_info.value)

    def test_nationality_normalization(self):
        """Test that nationality is normalized to title case."""
        author = Author(
            id="author_test01",
            name="Test Author",
            nationality="american",
        )
        assert author.nationality == "American"

        author = Author(
            id="author_test02",
            name="Test Author",
            nationality="BRITISH",
        )
        assert author.nationality == "British"

        author = Author(
            id="author_test03",
            name="Test Author",
            nationality="south african",
        )
        assert author.nationality == "South African"

    def test_book_ids_validation(self):
        """Test validation and normalization of book IDs."""
        # With hyphens - should be normalized
        author = Author(
            id="author_test01",
            name="Test Author",
            book_ids=["978-0-134-68547-9", "978-0-7432-7356-5"],
        )
        assert author.book_ids == ["9780134685479", "9780743273565"]

        # Invalid ISBN
        with pytest.raises(ValidationError) as exc_info:
            Author(
                id="author_test01",
                name="Test Author",
                book_ids=["123456"],  # Too short
            )
        assert "Invalid ISBN" in str(exc_info.value)

        # Non-numeric ISBN
        with pytest.raises(ValidationError) as exc_info:
            Author(
                id="author_test01",
                name="Test Author",
                book_ids=["978013468547X"],  # Contains letter
            )
        assert "Invalid ISBN" in str(exc_info.value)

    def test_add_book_method(self):
        """Test adding books to an author."""
        author = Author(
            id="author_test01",
            name="Test Author",
            book_ids=["9780134685479"],
        )

        # Add a new book
        author.add_book("978-0-7432-7356-5")
        assert "9780743273565" in author.book_ids
        assert author.book_count == 2

        # Try to add the same book again
        with pytest.raises(ValueError, match="already associated"):
            author.add_book("9780743273565")

        # Try to add invalid ISBN
        with pytest.raises(ValueError, match="Invalid ISBN"):
            author.add_book("invalid-isbn")

    def test_remove_book_method(self):
        """Test removing books from an author."""
        author = Author(
            id="author_test01",
            name="Test Author",
            book_ids=["9780134685479", "9780743273565"],
        )

        # Remove a book
        author.remove_book("978-0-134-68547-9")
        assert "9780134685479" not in author.book_ids
        assert author.book_count == 1

        # Try to remove a non-existent book
        with pytest.raises(ValueError, match="not found"):
            author.remove_book("9780134685479")

    def test_photo_url_validation(self):
        """Test validation of photo URLs."""
        # Valid URLs
        valid_urls = [
            "https://example.com/photo.jpg",
            "https://example.com/photo.jpeg",
            "https://example.com/photo.png",
            "https://example.com/photo.webp",
            "http://example.com/photo.jpg",
        ]

        for url in valid_urls:
            author = Author(
                id="author_test01",
                name="Test Author",
                photo_url=url,
            )
            assert author.photo_url == url

        # Invalid URLs
        invalid_urls = [
            "https://example.com/photo.gif",
            "https://example.com/photo",
            "not-a-url",
            "ftp://example.com/photo.jpg",
        ]

        for url in invalid_urls:
            with pytest.raises(ValidationError):
                Author(
                    id="author_test01",
                    name="Test Author",
                    photo_url=url,
                )

    def test_website_validation(self):
        """Test validation of website URLs."""
        # Valid URLs
        valid_urls = [
            "https://example.com",
            "http://example.com",
            "https://www.example.com/author",
        ]

        for url in valid_urls:
            author = Author(
                id="author_test01",
                name="Test Author",
                website=url,
            )
            assert author.website == url

        # Invalid URLs
        with pytest.raises(ValidationError):
            Author(
                id="author_test01",
                name="Test Author",
                website="not-a-url",
            )

    def test_json_serialization(self):
        """Test JSON serialization and deserialization."""
        author = Author(
            id="author_fitzgerald01",
            name="F. Scott Fitzgerald",
            biography="American novelist",
            birth_date=date(1896, 9, 24),
            death_date=date(1940, 12, 21),
            nationality="American",
            book_ids=["978-0-134-68547-9"],
        )

        # Serialize to dict
        data = author.model_dump()
        assert data["id"] == "author_fitzgerald01"
        assert data["book_ids"] == ["9780134685479"]

        # Serialize to JSON
        json_str = author.model_dump_json()
        assert "author_fitzgerald01" in json_str
        assert "9780134685479" in json_str

        # Deserialize from dict
        author2 = Author.model_validate(data)
        assert author2.id == author.id
        assert author2.book_ids == author.book_ids

    def test_optional_fields(self):
        """Test that optional fields work correctly."""
        # Minimal author
        author = Author(
            id="author_test01",
            name="Test Author",
        )

        assert author.biography is None
        assert author.birth_date is None
        assert author.death_date is None
        assert author.nationality is None
        assert author.book_ids == []
        assert author.photo_url is None
        assert author.website is None
        assert author.age is None
        assert author.is_living is True
        assert author.book_count == 0

    def test_timestamps(self):
        """Test timestamp handling."""
        before = datetime.now()

        author = Author(
            id="author_test01",
            name="Test Author",
        )

        after = datetime.now()

        assert before <= author.created_at <= after
        assert before <= author.updated_at <= after

        # Test that updated_at changes when modifying
        original_updated = author.updated_at
        author.add_book("9780134685479")
        assert author.updated_at > original_updated
