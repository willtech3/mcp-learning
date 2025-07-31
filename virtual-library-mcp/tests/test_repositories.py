"""
Basic tests for repository functionality.

These tests demonstrate how the repository pattern integrates with
the MCP server architecture.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.database import (
    AuthorRepository,
    Base,
    BookRepository,
    CirculationRepository,
    PaginationParams,
    PatronRepository,
)
from src.database.author_repository import (
    AuthorCreateSchema,
    AuthorSearchParams,
)
from src.database.book_repository import (
    BookCreateSchema,
    BookSearchParams,
    BookUpdateSchema,
)
from src.database.circulation_repository import (
    CheckoutCreateSchema,
    ReservationCreateSchema,
    ReturnProcessSchema,
)
from src.database.patron_repository import (
    PatronCreateSchema,
    PatronSearchParams,
)


@pytest.fixture
def test_session():
    """Create a test database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def repositories(test_session):
    """Create repository instances."""
    return {
        "book": BookRepository(test_session),
        "author": AuthorRepository(test_session),
        "patron": PatronRepository(test_session),
        "circulation": CirculationRepository(test_session),
    }


def test_author_repository_crud(repositories):
    """Test basic CRUD operations for authors."""
    author_repo = repositories["author"]

    # Create author
    author_data = AuthorCreateSchema(
        name="F. Scott Fitzgerald",
        biography="American novelist",
        birth_date=date(1896, 9, 24),
        nationality="American",
    )
    author = author_repo.create(author_data)

    assert author.id.startswith("author_")
    assert author.name == "F. Scott Fitzgerald"
    assert author.is_living is True

    # Get by ID
    fetched = author_repo.get_by_id(author.id)
    assert fetched is not None
    assert fetched.name == author.name

    # Get all with pagination
    pagination = PaginationParams(page=1, page_size=10)
    result = author_repo.get_all(pagination=pagination)
    assert result.total == 1
    assert len(result.items) == 1


def test_book_repository_search(repositories):
    """Test book search functionality."""
    author_repo = repositories["author"]
    book_repo = repositories["book"]

    # Create author first
    author = author_repo.create(AuthorCreateSchema(name="Test Author"))

    # Create books
    book1 = BookCreateSchema(
        isbn="9780134685479",
        title="The Great Gatsby",
        author_id=author.id,
        genre="Fiction",
        publication_year=1925,
        total_copies=3,
        available_copies=2,
    )
    book_repo.create(book1)

    book2 = BookCreateSchema(
        isbn="9780061120084",
        title="To Kill a Mockingbird",
        author_id=author.id,
        genre="Fiction",
        publication_year=1960,
        total_copies=2,
        available_copies=0,
    )
    book_repo.create(book2)

    # Search tests
    search_params = BookSearchParams(genre="Fiction", available_only=True)
    results = book_repo.search(search_params)
    assert results.total == 1
    assert results.items[0].title == "The Great Gatsby"

    # Search by title
    search_params = BookSearchParams(title="mockingbird")
    results = book_repo.search(search_params)
    assert results.total == 1
    assert results.items[0].isbn == "9780061120084"


def test_circulation_workflow(repositories):
    """Test complete circulation workflow."""
    # Create test data
    author = repositories["author"].create(AuthorCreateSchema(name="Test Author"))

    book = repositories["book"].create(
        BookCreateSchema(
            isbn="9780134685479",
            title="Test Book",
            author_id=author.id,
            genre="Fiction",
            publication_year=2024,
            total_copies=1,
            available_copies=1,
        )
    )

    patron = repositories["patron"].create(
        PatronCreateSchema(name="John Doe", email="john@example.com", borrowing_limit=5)
    )

    circulation_repo = repositories["circulation"]

    # Test checkout
    checkout_data = CheckoutCreateSchema(patron_id=patron.id, book_isbn=book.isbn)
    checkout = circulation_repo.checkout_book(checkout_data)

    assert checkout.status == "active"
    assert checkout.patron_id == patron.id
    assert checkout.book_isbn == book.isbn

    # Verify book availability decreased
    updated_book = repositories["book"].get_by_isbn(book.isbn)
    assert updated_book.available_copies == 0

    # Verify patron checkout count increased
    updated_patron = repositories["patron"].get_by_id(patron.id)
    assert updated_patron.current_checkouts == 1

    # Get active checkouts
    active = circulation_repo.get_active_checkouts(patron_id=patron.id)
    assert active.total == 1
    assert active.items[0].id == checkout.id


def test_pagination(repositories):
    """Test pagination functionality."""
    author_repo = repositories["author"]

    # Create multiple authors
    for i in range(25):
        author_repo.create(AuthorCreateSchema(name=f"Author {i:02d}"))

    # Test different pages
    page1 = author_repo.get_all(PaginationParams(page=1, page_size=10))
    assert len(page1.items) == 10
    assert page1.total == 25
    assert page1.has_next is True
    assert page1.has_previous is False

    page2 = author_repo.get_all(PaginationParams(page=2, page_size=10))
    assert len(page2.items) == 10
    assert page2.has_next is True
    assert page2.has_previous is True

    page3 = author_repo.get_all(PaginationParams(page=3, page_size=10))
    assert len(page3.items) == 5
    assert page3.has_next is False
    assert page3.has_previous is True


def test_book_update(repositories):
    """Test book update functionality."""
    author_repo = repositories["author"]
    book_repo = repositories["book"]

    # Create test data
    author1 = author_repo.create(AuthorCreateSchema(name="Author One"))
    author2 = author_repo.create(AuthorCreateSchema(name="Author Two"))

    book = book_repo.create(
        BookCreateSchema(
            isbn="9780134685479",
            title="Original Title",
            author_id=author1.id,
            genre="Fiction",
            publication_year=2020,
            total_copies=5,
            available_copies=5,
        )
    )

    # Test update with new title
    update_data = BookUpdateSchema(title="Updated Title")
    updated = book_repo.update(book.isbn, update_data)
    assert updated.title == "Updated Title"
    assert updated.author_id == author1.id  # Unchanged

    # Test update with new author
    update_data = BookUpdateSchema(author_id=author2.id)
    updated = book_repo.update(book.isbn, update_data)
    assert updated.author_id == author2.id

    # Test update with non-existent author (should fail)
    update_data = BookUpdateSchema(author_id="nonexistent_author")
    with pytest.raises(Exception, match="not found"):
        book_repo.update(book.isbn, update_data)


def test_patron_edge_cases(repositories):
    """Test patron repository edge cases."""
    patron_repo = repositories["patron"]

    # Test duplicate email
    patron1 = patron_repo.create(PatronCreateSchema(name="John Doe", email="john@example.com"))

    # Try to create another patron with same email
    with pytest.raises(Exception, match="already exists"):
        patron_repo.create(PatronCreateSchema(name="Jane Doe", email="john@example.com"))

    # Test patron search with multiple filters
    search_params = PatronSearchParams(email="john", has_checkouts=False, has_fines=False)
    results = patron_repo.search(search_params)
    assert results.total == 1
    assert results.items[0].id == patron1.id


def test_circulation_edge_cases(repositories):
    """Test circulation edge cases and error handling."""
    # Create test data
    author = repositories["author"].create(AuthorCreateSchema(name="Test Author"))

    book = repositories["book"].create(
        BookCreateSchema(
            isbn="9780134685479",
            title="Test Book",
            author_id=author.id,
            genre="Fiction",
            publication_year=2024,
            total_copies=1,
            available_copies=1,
        )
    )

    patron1 = repositories["patron"].create(
        PatronCreateSchema(name="Patron One", email="patron1@example.com", borrowing_limit=1)
    )

    patron2 = repositories["patron"].create(
        PatronCreateSchema(name="Patron Two", email="patron2@example.com")
    )

    circulation_repo = repositories["circulation"]

    # Test successful checkout
    circulation_repo.checkout_book(CheckoutCreateSchema(patron_id=patron1.id, book_isbn=book.isbn))

    # Test checkout when no copies available
    with pytest.raises(Exception, match="(No copies|available)"):
        circulation_repo.checkout_book(
            CheckoutCreateSchema(patron_id=patron2.id, book_isbn=book.isbn)
        )

    # Test checkout when patron at limit
    book2 = repositories["book"].create(
        BookCreateSchema(
            isbn="9780134685480",
            title="Another Book",
            author_id=author.id,
            genre="Fiction",
            publication_year=2024,
            total_copies=1,
            available_copies=1,
        )
    )

    with pytest.raises(Exception, match="borrowing limit"):
        circulation_repo.checkout_book(
            CheckoutCreateSchema(patron_id=patron1.id, book_isbn=book2.isbn)
        )

    # Test reservation creation
    reservation = circulation_repo.create_reservation(
        ReservationCreateSchema(patron_id=patron2.id, book_isbn=book.isbn)
    )
    assert reservation.queue_position == 1
    assert reservation.status == "pending"


def test_return_with_fines(repositories):
    """Test return process with fine calculation."""

    # Create test data
    author = repositories["author"].create(AuthorCreateSchema(name="Test Author"))

    book = repositories["book"].create(
        BookCreateSchema(
            isbn="9780134685479",
            title="Test Book",
            author_id=author.id,
            genre="Fiction",
            publication_year=2024,
            total_copies=1,
            available_copies=1,
        )
    )

    patron = repositories["patron"].create(
        PatronCreateSchema(name="Test Patron", email="test@example.com")
    )

    circulation_repo = repositories["circulation"]

    # Create a normal checkout
    checkout = circulation_repo.checkout_book(
        CheckoutCreateSchema(patron_id=patron.id, book_isbn=book.isbn)
    )

    # Manually update the due date in the database to simulate an overdue book
    # This is a test-only operation to simulate time passing
    repositories["circulation"].session.execute(
        text("UPDATE checkout_records SET due_date = :due_date WHERE id = :id"),
        {"due_date": date.today() - timedelta(days=5), "id": checkout.id},
    )
    repositories["circulation"].session.commit()

    # Process return
    return_record, updated_checkout = circulation_repo.return_book(
        ReturnProcessSchema(checkout_id=checkout.id, condition="good")
    )

    # Verify fine calculation (5 days * $0.25 = $1.25)
    assert return_record.late_days == 5
    assert return_record.fine_assessed == 1.25
    assert updated_checkout.fine_amount == 1.25

    # Verify patron fines updated
    updated_patron = repositories["patron"].get_by_id(patron.id)
    assert updated_patron.outstanding_fines == 1.25


def test_sorting_and_filtering(repositories):
    """Test advanced sorting and filtering options."""
    author_repo = repositories["author"]
    book_repo = repositories["book"]

    # Create multiple authors with different nationalities
    american = author_repo.create(
        AuthorCreateSchema(
            name="American Author", nationality="American", birth_date=date(1950, 1, 1)
        )
    )

    british = author_repo.create(
        AuthorCreateSchema(
            name="British Author", nationality="British", birth_date=date(1960, 1, 1)
        )
    )

    # Create books with different genres
    for i, (author, genre) in enumerate(
        [(american, "Fiction"), (american, "Mystery"), (british, "Fiction"), (british, "Romance")]
    ):
        book_repo.create(
            BookCreateSchema(
                isbn=f"978013468547{i}",
                title=f"{genre} Book by {author.name}",
                author_id=author.id,
                genre=genre,
                publication_year=2020 + i,
                total_copies=2,
                available_copies=1 if i % 2 == 0 else 0,
            )
        )

    # Test author search by nationality
    search_params = AuthorSearchParams(nationality="American")
    results = author_repo.search(search_params)
    assert results.total == 1
    assert results.items[0].id == american.id

    # Test book search by genre with availability filter
    search_params = BookSearchParams(genre="Fiction", available_only=True)
    results = book_repo.search(search_params)
    assert results.total == 2  # Both Fiction books have available copies
    # Check that we got both Fiction books
    author_ids = {book.author_id for book in results.items}
    assert author_ids == {american.id, british.id}

    # Test get available genres
    genres = book_repo.get_available_genres()
    assert set(genres) == {"Fiction", "Mystery", "Romance"}

    # Test get nationalities
    nationalities = author_repo.get_nationalities()
    assert set(nationalities) == {"American", "British"}
