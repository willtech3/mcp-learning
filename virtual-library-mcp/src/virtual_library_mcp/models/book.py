"""
Book model for the Virtual Library MCP Server.

This model represents a book in the library catalog. In the MCP architecture,
books will be exposed as resources (read-only data endpoints) that can be
accessed via URIs like:
- library://books/list
- library://books/{isbn}

The model follows MCP best practices:
1. Complete type hints for protocol compliance
2. Pydantic v2 for automatic JSON serialization
3. Validation rules for data integrity
4. Rich field descriptions for API documentation
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Book(BaseModel):
    """
    Represents a book in the library catalog.

    This model serves as the core data structure for book resources in the MCP
    server. Books can be retrieved, searched, and referenced by other models
    like checkouts and reservations.
    """

    isbn: str = Field(
        ...,
        description="International Standard Book Number (ISBN-13 format)",
        pattern=r"^\d{3}-\d{1,5}-\d{1,7}-\d{1,7}-\d{1}$|^\d+$",
        examples=["978-0-134-68547-9", "9780134685479"],
    )

    title: str = Field(
        ...,
        description="The title of the book",
        min_length=1,
        max_length=500,
        examples=["The Great Gatsby", "To Kill a Mockingbird"],
    )

    author_id: str = Field(
        ...,
        description="Unique identifier for the book's author",
        pattern=r"^author_[a-zA-Z0-9_]{6,}$",
        examples=["author_fitzgerald01", "author_lee_harper"],
    )

    genre: str = Field(
        ...,
        description="Literary genre or category of the book",
        examples=["Fiction", "Non-Fiction", "Science Fiction", "Biography"],
    )

    publication_year: int = Field(
        ...,
        description="Year the book was published",
        ge=1450,  # After Gutenberg printing press
        le=datetime.now().year + 1,  # Allow pre-publication for upcoming books
        examples=[1925, 1960, 2023],
    )

    available_copies: int = Field(
        default=1,
        description="Number of copies currently available for checkout",
        ge=0,
        examples=[0, 1, 5],
    )

    total_copies: int = Field(
        ...,
        description="Total number of copies owned by the library",
        ge=1,
        examples=[1, 3, 10],
    )

    description: str | None = Field(
        None,
        description="Brief description or summary of the book",
        max_length=2000,
        examples=[
            "A classic American novel set in the Jazz Age...",
            "A gripping tale of racial injustice in the American South...",
        ],
    )

    cover_url: str | None = Field(
        None,
        description="URL to the book's cover image",
        pattern=r"^https?://.*\.(jpg|jpeg|png|webp)$",
        examples=[
            "https://covers.library.org/isbn/9780134685479.jpg",
            "https://example.com/covers/great-gatsby.png",
        ],
    )

    # Timestamps for tracking
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the book was added to the catalog",
    )

    updated_at: datetime = Field(
        default=None,
        description="Timestamp when the book record was last updated",
    )

    @field_validator("isbn")
    @classmethod
    def normalize_isbn(cls, v: str) -> str:
        """Normalize ISBN by removing hyphens for consistent storage."""
        # Remove hyphens for storage but accept both formats
        normalized = v.replace("-", "")
        if len(normalized) != 13:
            raise ValueError("ISBN must be 13 digits")
        return normalized

    @field_validator("available_copies")
    @classmethod
    def validate_available_copies(cls, v: int) -> int:
        """Validate available copies is non-negative."""
        # Just validate the value itself here
        return v

    @field_validator("genre")
    @classmethod
    def normalize_genre(cls, v: str) -> str:
        """Normalize genre to title case for consistency."""
        return v.strip().title()

    @model_validator(mode="after")
    def validate_copies(self) -> "Book":
        """Ensure available copies doesn't exceed total copies."""
        if self.available_copies > self.total_copies:
            raise ValueError("Available copies cannot exceed total copies")
        return self

    def model_post_init(self, __context) -> None:
        """Initialize updated_at to match created_at on creation."""
        if self.updated_at is None:
            self.updated_at = self.created_at

    @property
    def is_available(self) -> bool:
        """Check if the book has any available copies."""
        return self.available_copies > 0

    @property
    def checked_out_copies(self) -> int:
        """Calculate number of copies currently checked out."""
        return self.total_copies - self.available_copies

    def checkout(self) -> None:
        """
        Mark a copy as checked out.

        Raises:
            ValueError: If no copies are available
        """
        if not self.is_available:
            raise ValueError(f"No copies of '{self.title}' are available")
        self.available_copies -= 1
        self.updated_at = datetime.now()

    def return_copy(self) -> None:
        """Mark a copy as returned."""
        if self.available_copies >= self.total_copies:
            raise ValueError("All copies are already returned")
        self.available_copies += 1
        self.updated_at = datetime.now()

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "isbn": "9780134685479",
                "title": "The Great Gatsby",
                "author_id": "author_fitzgerald01",
                "genre": "Fiction",
                "publication_year": 1925,
                "available_copies": 2,
                "total_copies": 3,
                "description": "A classic American novel set in the Jazz Age...",
                "cover_url": "https://covers.library.org/isbn/9780134685479.jpg",
            }
        }
    )
