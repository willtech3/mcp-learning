"""Regression tests for author and genre URI-template resources."""

import json
from unittest.mock import Mock, patch

import pytest
from fastmcp.exceptions import ResourceError

from database.book_repository import BookSortOptions
from database.repository import PaginatedResponse
from models.author import Author
from models.book import Book
from resources.advanced_books import (
    get_books_by_author_handler,
    get_books_by_genre_handler,
)


@pytest.fixture
def catalog_book():
    return Book(
        isbn="9780134685991",
        title="The Available Book",
        author_id="author_test001",
        genre="Fiction",
        publication_year=2020,
        available_copies=2,
        total_copies=3,
        description="A realistic catalog description.",
    )


@pytest.fixture
def catalog_page(catalog_book):
    return PaginatedResponse(
        items=[catalog_book],
        total=1,
        page=1,
        page_size=20,
        total_pages=1,
        has_next=False,
        has_previous=False,
    )


@pytest.fixture
def catalog_author():
    return Author(id="author_test001", name="Test Author")


@pytest.mark.asyncio
async def test_books_by_author_uses_author_identifier_and_real_fields(catalog_page, catalog_author):
    with (
        patch("resources.advanced_books.session_scope") as session_scope,
        patch("resources.advanced_books.BookRepository") as book_repository,
        patch("resources.advanced_books.AuthorRepository") as author_repository,
    ):
        session_scope.return_value.__enter__.return_value = Mock()
        book_repository.return_value.get_by_author.return_value = catalog_page
        author_repository.return_value.get_by_id.return_value = catalog_author

        result = await get_books_by_author_handler("author_test001")

    book_repository.return_value.get_by_author.assert_called_once()
    call = book_repository.return_value.get_by_author.call_args.kwargs
    assert call["author_id"] == "author_test001"
    assert result["books"][0]["author"] == "Test Author"
    assert result["books"][0]["is_available"] is True
    assert "average_rating" not in result["books"][0]
    json.dumps(result)


@pytest.mark.asyncio
async def test_books_by_genre_uses_supported_sort_and_real_fields(catalog_page, catalog_author):
    with (
        patch("resources.advanced_books.session_scope") as session_scope,
        patch("resources.advanced_books.BookRepository") as book_repository,
        patch("resources.advanced_books.AuthorRepository") as author_repository,
    ):
        session_scope.return_value.__enter__.return_value = Mock()
        book_repository.return_value.get_by_genre.return_value = catalog_page
        author_repository.return_value.get_by_id.return_value = catalog_author

        result = await get_books_by_genre_handler("Fiction")

    call = book_repository.return_value.get_by_genre.call_args.kwargs
    assert call["genre"] == "Fiction"
    assert call["sort_by"] == BookSortOptions.TITLE
    assert result["books"][0]["author"] == "Test Author"
    assert "publisher" not in result["books"][0]
    json.dumps(result)


@pytest.mark.asyncio
async def test_advanced_resource_repository_failure_is_protocol_error():
    with (
        patch("resources.advanced_books.session_scope") as session_scope,
        patch("resources.advanced_books.BookRepository") as book_repository,
    ):
        session_scope.return_value.__enter__.return_value = Mock()
        book_repository.return_value.get_by_author.side_effect = RuntimeError(
            "database unavailable"
        )

        with pytest.raises(ResourceError, match="Failed to retrieve books by author"):
            await get_books_by_author_handler("author_test001")
