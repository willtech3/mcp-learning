"""
Author model for the Virtual Library MCP Server.

This model represents an author in the library system. In the MCP architecture,
authors will be exposed as resources that can be accessed via URIs like:
- library://authors/list
- library://authors/{author_id}

Authors maintain relationships with books and provide biographical information
for library patrons.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class Author(BaseModel):
    """
    Represents an author in the library system.

    Authors are linked to books through the author_id field in the Book model.
    This allows for efficient querying of all books by a specific author.
    """

    id: str = Field(
        ...,
        description="Unique identifier for the author",
        pattern=r"^author_[a-zA-Z0-9_]{6,}$",
        examples=["author_fitzgerald01", "author_lee_harper"],
    )

    name: str = Field(
        ...,
        description="Full name of the author",
        min_length=2,
        max_length=200,
        examples=["F. Scott Fitzgerald", "Harper Lee", "George Orwell"],
    )

    biography: str | None = Field(
        None,
        description="Brief biography of the author",
        max_length=5000,
        examples=[
            "F. Scott Fitzgerald (1896-1940) was an American novelist...",
            "Harper Lee (1926-2016) was an American novelist best known for...",
        ],
    )

    birth_date: date | None = Field(
        None,
        description="Author's date of birth",
        examples=["1896-09-24", "1926-04-28"],
    )

    death_date: date | None = Field(
        None,
        description="Author's date of death (if applicable)",
        examples=["1940-12-21", "2016-02-19"],
    )

    nationality: str | None = Field(
        None,
        description="Author's nationality",
        max_length=100,
        examples=["American", "British", "French"],
    )

    book_ids: list[str] = Field(
        default_factory=list,
        description="List of ISBN identifiers for books written by this author",
        examples=[["9780134685479", "9780743273565"], ["9780061120084"]],
    )

    # Additional metadata
    photo_url: str | None = Field(
        None,
        description="URL to the author's photograph",
        pattern=r"^https?://.*\.(jpg|jpeg|png|webp)$",
        examples=[
            "https://library.org/authors/fitzgerald.jpg",
            "https://example.com/authors/harper-lee.png",
        ],
    )

    website: str | None = Field(
        None,
        description="Author's official website or memorial page",
        pattern=r"^https?://.*",
        examples=[
            "https://www.fscottfitzgerald.org/",
            "https://harperlee.com/",
        ],
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the author was added to the system",
    )

    updated_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the author record was last updated",
    )

    @field_validator("birth_date", "death_date")
    @classmethod
    def validate_dates(cls, v: date | None, info: ValidationInfo) -> date | None:
        """Validate birth and death dates."""
        if v is None:
            return v

        # Check if date is not in the future
        if v > date.today():
            raise ValueError("Date cannot be in the future")

        # If validating death_date, ensure it's after birth_date
        if info.field_name == "death_date" and "birth_date" in info.data:
            birth_date = info.data["birth_date"]
            if birth_date and v < birth_date:
                raise ValueError("Death date cannot be before birth date")

        return v

    @field_validator("nationality")
    @classmethod
    def normalize_nationality(cls, v: str | None) -> str | None:
        """Normalize nationality to title case."""
        if v is None:
            return v
        return v.strip().title()

    @field_validator("book_ids")
    @classmethod
    def validate_book_ids(cls, v: list[str]) -> list[str]:
        """Ensure all book IDs are valid ISBN format."""
        normalized_ids: list[str] = []
        for book_id in v:
            # Remove hyphens and validate length
            normalized = book_id.replace("-", "")
            if len(normalized) != 13 or not normalized.isdigit():
                raise ValueError(f"Invalid ISBN format: {book_id}")
            normalized_ids.append(normalized)
        return normalized_ids

    @property
    def is_living(self) -> bool:
        """Check if the author is still living."""
        return self.death_date is None

    @property
    def age(self) -> int | None:
        """Calculate the author's age (current or at death)."""
        if self.birth_date is None:
            return None

        end_date = self.death_date or date.today()
        age = end_date.year - self.birth_date.year

        # Adjust for birthday not yet reached in the year
        if (end_date.month, end_date.day) < (self.birth_date.month, self.birth_date.day):
            age -= 1

        return age

    @property
    def book_count(self) -> int:
        """Get the number of books by this author."""
        return len(self.book_ids)

    def add_book(self, isbn: str) -> None:
        """
        Add a book to the author's collection.

        Args:
            isbn: The ISBN of the book to add

        Raises:
            ValueError: If the ISBN is invalid or already exists
        """
        # Normalize ISBN
        normalized_isbn = isbn.replace("-", "")
        if len(normalized_isbn) != 13 or not normalized_isbn.isdigit():
            raise ValueError(f"Invalid ISBN format: {isbn}")

        if normalized_isbn in self.book_ids:
            raise ValueError(f"Book {isbn} already associated with author")

        self.book_ids.append(normalized_isbn)
        self.updated_at = datetime.now()

    def remove_book(self, isbn: str) -> None:
        """
        Remove a book from the author's collection.

        Args:
            isbn: The ISBN of the book to remove

        Raises:
            ValueError: If the book is not found
        """
        normalized_isbn = isbn.replace("-", "")
        if normalized_isbn not in self.book_ids:
            raise ValueError(f"Book {isbn} not found for author")

        self.book_ids.remove(normalized_isbn)
        self.updated_at = datetime.now()

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "author_fitzgerald01",
                "name": "F. Scott Fitzgerald",
                "biography": "F. Scott Fitzgerald (1896-1940) was an American novelist...",
                "birth_date": "1896-09-24",
                "death_date": "1940-12-21",
                "nationality": "American",
                "book_ids": ["9780134685479", "9780743273565"],
                "photo_url": "https://library.org/authors/fitzgerald.jpg",
                "website": "https://www.fscottfitzgerald.org/",
            }
        }
    )
