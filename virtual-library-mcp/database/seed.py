"""
Database seeding script for the Virtual Library MCP Server.

This script generates realistic test data to demonstrate all MCP protocol features:
- Resources: Queryable authors, books, and patrons
- Tools: Circulation records for checkout/return operations
- Subscriptions: State changes that trigger real-time updates
- Progress: Reports progress during generation for long operations

The generated data includes:
- 100+ unique authors with biographical information
- 1000+ books with valid ISBNs across multiple genres
- 50+ patrons with varying membership statuses
- Realistic circulation history showing checkouts, returns, and reservations
"""

import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

from faker import Faker
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Add the src directory to the path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from virtual_library_mcp.database.schema import (
    Author,
    Base,
    Book,
    CheckoutRecord,
    CirculationStatusEnum,
    Patron,
    PatronStatusEnum,
    ReservationRecord,
    ReservationStatusEnum,
    ReturnRecord,
)

# Initialize Faker for realistic data generation
fake = Faker()
Faker.seed(42)  # Consistent data across runs
random.seed(42)


class ProgressReporter:
    """Reports progress during data generation - demonstrates MCP progress notifications."""
    
    def __init__(self, total_steps: int) -> None:
        self.total_steps = total_steps
        self.current_step = 0
        self.current_task = ""
    
    def update(self, task: str, increment: int = 1) -> None:
        """Update progress with current task."""
        self.current_task = task
        self.current_step += increment
        percentage = (self.current_step / self.total_steps) * 100
        print(f"[{percentage:5.1f}%] {task}")


def generate_isbn13() -> str:
    """Generate a valid ISBN-13 number."""
    # ISBN-13 format: 978-X-XXXX-XXXX-X
    prefix = "978"
    group = str(random.randint(0, 9))
    publisher = str(random.randint(1000, 9999))
    title = str(random.randint(1000, 9999))
    
    # Calculate check digit
    isbn_without_check = f"{prefix}{group}{publisher}{title}"
    total = sum(
        int(digit) * (3 if i % 2 else 1)
        for i, digit in enumerate(isbn_without_check)
    )
    check_digit = (10 - (total % 10)) % 10
    
    return f"{isbn_without_check}{check_digit}"


def generate_authors(num_authors: int = 120) -> List[Author]:
    """
    Generate unique authors with realistic biographical information.
    
    MCP Integration:
    - Each author gets a unique ID following the pattern 'author_XXXXX'
    - Biographical data supports rich resource representations
    - Birth/death dates enable filtering and historical queries
    """
    authors = []
    nationalities = [
        "American", "British", "Canadian", "Australian", "Irish",
        "French", "German", "Italian", "Spanish", "Russian",
        "Japanese", "Chinese", "Indian", "Brazilian", "Mexican",
        "Swedish", "Norwegian", "Danish", "Dutch", "Belgian"
    ]
    
    for i in range(num_authors):
        # Generate birth date between 1850 and 2000
        birth_year = random.randint(1850, 2000)
        birth_date = fake.date_between(
            start_date=date(birth_year, 1, 1),
            end_date=date(birth_year, 12, 31)
        )
        
        # 20% chance of being deceased
        death_date = None
        if random.random() < 0.2 and birth_year < 1980:
            death_year = random.randint(birth_year + 30, 2024)
            death_date = fake.date_between(
                start_date=date(death_year, 1, 1),
                end_date=date(min(death_year, 2024), 12, 31)
            )
        
        author = Author(
            id=f"author_{i+1:05d}",
            name=fake.name(),
            biography=fake.text(max_nb_chars=500),
            birth_date=birth_date,
            death_date=death_date,
            nationality=random.choice(nationalities),
            photo_url=f"https://example.com/authors/author_{i+1:05d}.jpg" if random.random() > 0.3 else None,
            website=fake.url() if random.random() > 0.5 else None,
            created_at=fake.date_time_between(start_date="-2y", end_date="now"),
            updated_at=datetime.now()
        )
        authors.append(author)
    
    return authors


def generate_books(authors: List[Author], num_books: int = 1200) -> List[Book]:
    """
    Generate books with valid ISBNs distributed across multiple genres.
    
    MCP Integration:
    - ISBNs serve as unique resource identifiers
    - Available copies enable real-time availability tracking
    - Genre distribution supports filtering and recommendations
    """
    books = []
    
    genres = [
        "Fiction", "Mystery", "Science Fiction", "Fantasy", "Romance",
        "Thriller", "Horror", "Biography", "History", "Science",
        "Self-Help", "Business", "Psychology", "Philosophy", "Poetry",
        "Drama", "Comedy", "Adventure", "Children's", "Young Adult"
    ]
    
    # Genre weights for realistic distribution
    genre_weights = [
        20, 15, 12, 12, 10,  # Popular fiction genres
        8, 5, 8, 10, 8,      # Mix of fiction and non-fiction
        6, 6, 5, 5, 3,       # Non-fiction
        4, 3, 5, 8, 10       # Other categories
    ]
    
    for _ in range(num_books):
        author = random.choice(authors)
        genre = random.choices(genres, weights=genre_weights)[0]
        
        # Generate publication year based on author's lifetime
        if author.death_date is not None:
            max_year = author.death_date.year
        else:
            max_year = 2024
        
        min_year = author.birth_date.year + 20  # Authors typically start publishing after 20
        publication_year = random.randint(min(min_year, 2023), min(max_year, 2024))
        
        # Total copies: more for popular genres
        if genre in ["Fiction", "Mystery", "Thriller", "Romance"]:
            total_copies = random.randint(3, 10)
        else:
            total_copies = random.randint(1, 5)
        
        # Available copies: some books are checked out
        available_copies = random.randint(0, total_copies)
        
        book = Book(
            isbn=generate_isbn13(),
            title=fake.catch_phrase().title() + ": " + fake.bs().title(),
            author_id=author.id,
            genre=genre,
            publication_year=publication_year,
            available_copies=available_copies,
            total_copies=total_copies,
            description=fake.text(max_nb_chars=800),
            cover_url=f"https://example.com/covers/{generate_isbn13()}.jpg" if random.random() > 0.2 else None,
            created_at=fake.date_time_between(start_date="-2y", end_date="now"),
            updated_at=datetime.now()
        )
        books.append(book)
    
    return books


def generate_patrons(num_patrons: int = 60) -> List[Patron]:
    """
    Generate library patrons with varying membership statuses.
    
    MCP Integration:
    - Patron IDs enable user-specific tool operations
    - Status variations demonstrate access control in MCP
    - Borrowing limits show tool constraints
    """
    patrons = []
    
    status_weights = {
        PatronStatusEnum.ACTIVE: 70,
        PatronStatusEnum.SUSPENDED: 10,
        PatronStatusEnum.EXPIRED: 15,
        PatronStatusEnum.PENDING: 5
    }
    
    for i in range(num_patrons):
        # Membership date: between 5 years ago and today
        membership_date = fake.date_between(start_date="-5y", end_date="today")
        
        # Status affects other fields
        status = random.choices(
            list(status_weights.keys()),
            weights=list(status_weights.values())
        )[0]
        
        # Expiration date based on status
        if status == PatronStatusEnum.EXPIRED:
            # For expired patrons, expiration date is in the past
            # Ensure we have a valid date range
            min_expiration = membership_date + timedelta(days=365)
            today = date.today()
            if min_expiration < today:
                expiration_date = fake.date_between(
                    start_date=min_expiration,
                    end_date=today - timedelta(days=1)  # At least 1 day ago
                )
            else:
                # If membership is too recent, set expiration to yesterday
                expiration_date = today - timedelta(days=1)
        elif status == PatronStatusEnum.ACTIVE:
            # Active patrons have future expiration dates
            expiration_date = fake.date_between(
                start_date=date.today() + timedelta(days=1),
                end_date="+2y"
            )
        else:
            # Suspended or pending patrons may not have expiration dates
            expiration_date = None
        
        # Borrowing limit varies by patron type
        borrowing_limit = random.choice([3, 5, 5, 5, 10, 10, 15])  # Most have 5 or 10
        
        # Current checkouts based on status
        if status == PatronStatusEnum.ACTIVE:
            current_checkouts = random.randint(0, min(borrowing_limit - 1, 5))
        else:
            current_checkouts = 0
        
        # Outstanding fines
        if status == PatronStatusEnum.SUSPENDED:
            outstanding_fines = round(random.uniform(10.0, 50.0), 2)
        elif random.random() < 0.1:  # 10% have small fines
            outstanding_fines = round(random.uniform(0.5, 9.99), 2)
        else:
            outstanding_fines = 0.0
        
        # Preferred genres (JSON array as string)
        num_preferred = random.randint(1, 5)
        preferred_genres = random.sample([
            "Fiction", "Mystery", "Science Fiction", "Fantasy", "Romance",
            "History", "Biography", "Science", "Philosophy"
        ], num_preferred)
        
        patron = Patron(
            id=f"patron_{i+1:05d}",
            name=fake.name(),
            email=fake.email(),
            phone=fake.phone_number()[:20],  # Limit length
            address=fake.address().replace('\n', ', '),
            membership_date=membership_date,
            expiration_date=expiration_date,
            status=status,
            borrowing_limit=borrowing_limit,
            current_checkouts=current_checkouts,
            total_checkouts=random.randint(current_checkouts, current_checkouts + 50),
            outstanding_fines=outstanding_fines,
            preferred_genres=str(preferred_genres),  # Store as string for SQLite
            notification_preferences='{"email": true, "sms": false}',
            created_at=membership_date,
            updated_at=datetime.now(),
            last_activity=fake.date_time_between(start_date="-30d", end_date="now") if status == PatronStatusEnum.ACTIVE else None
        )
        patrons.append(patron)
    
    return patrons


def generate_circulation_history(
    patrons: List[Patron],
    books: List[Book],
    num_checkouts: int = 500
) -> tuple[List[CheckoutRecord], List[ReturnRecord], List[ReservationRecord]]:
    """
    Generate realistic circulation history including checkouts, returns, and reservations.
    
    MCP Integration:
    - Demonstrates stateful operations across multiple tables
    - Shows how tools create and update related records
    - Provides data for subscription-based notifications
    """
    checkouts = []
    returns = []
    reservations = []
    
    # Get only active patrons for checkouts
    active_patrons = [p for p in patrons if p.status == PatronStatusEnum.ACTIVE]
    
    # Track books currently checked out by each patron
    patron_checkouts: Dict[str, List[str]] = {p.id: [] for p in patrons}
    
    # Generate historical checkouts (80% returned)
    for i in range(int(num_checkouts * 0.8)):
        patron = random.choice(active_patrons)
        book = random.choice(books)
        
        # Checkout date: between 2 years ago and 2 months ago
        checkout_date = fake.date_time_between(start_date="-2y", end_date="-2M")
        due_date = (checkout_date + timedelta(days=21)).date()
        
        # Return date: usually before due date, sometimes late
        if random.random() < 0.8:  # 80% returned on time
            return_date = fake.date_time_between(
                start_date=checkout_date,
                end_date=due_date
            )
            late_days = 0
            fine_amount = 0.0
        else:  # 20% returned late
            late_days = random.randint(1, 30)
            return_date = checkout_date + timedelta(days=21 + late_days)
            fine_amount = late_days * 0.25  # $0.25 per day
        
        checkout = CheckoutRecord(
            id=f"checkout_{i+1:06d}",
            patron_id=patron.id,
            book_isbn=book.isbn,
            checkout_date=checkout_date,
            due_date=due_date,
            return_date=return_date,
            status=CirculationStatusEnum.COMPLETED,
            renewal_count=random.randint(0, 2),
            fine_amount=fine_amount,
            fine_paid=random.random() < 0.9,  # 90% of fines are paid
            notes=fake.sentence() if random.random() < 0.1 else None,
            created_at=checkout_date,
            updated_at=return_date
        )
        checkouts.append(checkout)
        
        # Create corresponding return record
        return_record = ReturnRecord(
            id=f"return_{i+1:06d}",
            checkout_id=checkout.id,
            patron_id=patron.id,
            book_isbn=book.isbn,
            return_date=return_date,
            condition=random.choice(["excellent", "good", "good", "good", "fair"]),
            late_days=late_days,
            fine_assessed=fine_amount,
            fine_paid=fine_amount if checkout.fine_paid else 0.0,
            notes=fake.sentence() if random.random() < 0.05 else None,
            processed_by="Library Staff",
            created_at=return_date
        )
        returns.append(return_record)
    
    # Generate current checkouts (20% of total)
    checkout_counter = len(checkouts)
    for i in range(int(num_checkouts * 0.2)):
        patron = random.choice(active_patrons)
        
        # Skip if patron is at checkout limit
        if len(patron_checkouts[patron.id]) >= patron.borrowing_limit:
            continue
        
        book = random.choice(books)
        
        # Skip if book has no available copies
        if book.available_copies <= 0:
            continue
        
        # Recent checkout: within last 3 weeks
        checkout_date = fake.date_time_between(start_date="-3w", end_date="now")
        due_date = (checkout_date + timedelta(days=21)).date()
        
        # Determine if overdue
        if due_date < date.today():
            status = CirculationStatusEnum.OVERDUE
            late_days = (date.today() - due_date).days
            fine_amount = late_days * 0.25
        else:
            status = CirculationStatusEnum.ACTIVE
            fine_amount = 0.0
        
        checkout = CheckoutRecord(
            id=f"checkout_{checkout_counter+i+1:06d}",
            patron_id=patron.id,
            book_isbn=book.isbn,
            checkout_date=checkout_date,
            due_date=due_date,
            return_date=None,
            status=status,
            renewal_count=random.randint(0, 1),
            fine_amount=fine_amount,
            fine_paid=False,
            notes=None,
            created_at=checkout_date,
            updated_at=checkout_date
        )
        checkouts.append(checkout)
        patron_checkouts[patron.id].append(book.isbn)
        
        # Update book availability (in memory only for generation)
        book.available_copies -= 1
    
    # Generate reservations for popular books with no copies
    unavailable_books = [b for b in books if b.available_copies == 0]
    reservation_counter = 0
    
    for book in random.sample(unavailable_books, min(50, len(unavailable_books))):
        # 1-5 patrons waiting for each unavailable book
        num_reservations = random.randint(1, 5)
        waiting_patrons = random.sample(active_patrons, min(num_reservations, len(active_patrons)))
        
        for position, patron in enumerate(waiting_patrons, 1):
            reservation_date = fake.date_time_between(start_date="-1M", end_date="now")
            
            reservation = ReservationRecord(
                id=f"reservation_{reservation_counter+1:05d}",
                patron_id=patron.id,
                book_isbn=book.isbn,
                reservation_date=reservation_date,
                expiration_date=(reservation_date + timedelta(days=90)).date(),
                notification_date=None,
                pickup_deadline=None,
                status=ReservationStatusEnum.PENDING,
                queue_position=position,
                notes=None,
                created_at=reservation_date,
                updated_at=reservation_date
            )
            reservations.append(reservation)
            reservation_counter += 1
    
    return checkouts, returns, reservations


def seed_database(database_url: str = "sqlite:///library.db"):
    """
    Main function to seed the database with generated data.
    
    This demonstrates:
    - Progress reporting for long operations (MCP progress feature)
    - Transactional data insertion
    - Relationship management across tables
    """
    # Calculate total steps for progress reporting
    total_steps = 7  # Major operations
    progress = ProgressReporter(total_steps)
    
    # Create engine and tables
    engine = create_engine(database_url)
    Base.metadata.drop_all(engine)  # Clean slate
    Base.metadata.create_all(engine)
    progress.update("Database tables created")
    
    # Create session
    session = Session(engine)
    
    try:
        # Generate authors
        print("\nGenerating authors...")
        authors = generate_authors(120)
        session.add_all(authors)
        session.commit()
        progress.update(f"Generated {len(authors)} authors")
        
        # Generate books
        print("\nGenerating books...")
        books = generate_books(authors, 1200)
        session.add_all(books)
        session.commit()
        progress.update(f"Generated {len(books)} books")
        
        # Generate patrons
        print("\nGenerating patrons...")
        patrons = generate_patrons(60)
        session.add_all(patrons)
        session.commit()
        progress.update(f"Generated {len(patrons)} patrons")
        
        # Generate circulation history
        print("\nGenerating circulation history...")
        checkouts, returns, reservations = generate_circulation_history(patrons, books, 500)
        
        session.add_all(checkouts)
        session.commit()
        progress.update(f"Generated {len(checkouts)} checkout records")
        
        session.add_all(returns)
        session.commit()
        progress.update(f"Generated {len(returns)} return records")
        
        session.add_all(reservations)
        session.commit()
        progress.update(f"Generated {len(reservations)} reservation records")
        
        # Print summary statistics
        print("\n" + "="*50)
        print("DATABASE SEEDING COMPLETE")
        print("="*50)
        print(f"Authors:       {len(authors):,}")
        print(f"Books:         {len(books):,}")
        print(f"Patrons:       {len(patrons):,}")
        print(f"  - Active:    {sum(1 for p in patrons if p.status == PatronStatusEnum.ACTIVE)}")
        print(f"  - Suspended: {sum(1 for p in patrons if p.status == PatronStatusEnum.SUSPENDED)}")
        print(f"  - Expired:   {sum(1 for p in patrons if p.status == PatronStatusEnum.EXPIRED)}")
        print(f"Checkouts:     {len(checkouts):,}")
        print(f"  - Active:    {sum(1 for c in checkouts if c.status == CirculationStatusEnum.ACTIVE)}")
        print(f"  - Completed: {sum(1 for c in checkouts if c.status == CirculationStatusEnum.COMPLETED)}")
        print(f"  - Overdue:   {sum(1 for c in checkouts if c.status == CirculationStatusEnum.OVERDUE)}")
        print(f"Returns:       {len(returns):,}")
        print(f"Reservations:  {len(reservations):,}")
        print("="*50)
        
    except Exception as e:
        session.rollback()
        print(f"\nError during seeding: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    # Use the project's database location
    db_path = Path(__file__).parent.parent / "data" / "library.db"
    db_path.parent.mkdir(exist_ok=True)
    
    print("Starting Virtual Library MCP Server database seeding...")
    print(f"Database location: {db_path}")
    
    seed_database(f"sqlite:///{db_path}")