#!/usr/bin/env python3
"""
Initialize the Virtual Library database.

This script:
1. Creates all database tables
2. Optionally loads sample data
3. Verifies the database is ready for MCP server use

Usage:
    python scripts/init_database.py [--drop-existing] [--sample-data]
"""

import argparse
import logging
import sys
from pathlib import Path

# Add the src directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_db_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point for database initialization."""
    parser = argparse.ArgumentParser(
        description="Initialize the Virtual Library MCP Server database"
    )
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="Drop existing tables before creating new ones",
    )
    parser.add_argument(
        "--sample-data",
        action="store_true",
        help="Load sample data after creating tables",
    )
    parser.add_argument(
        "--database-url",
        help="Override default database URL",
    )

    args = parser.parse_args()

    # Initialize database manager
    logger.info("Initializing database manager...")
    db_manager = get_db_manager(args.database_url)

    # Verify connection
    if not db_manager.verify_connection():
        logger.error("Failed to connect to database")
        sys.exit(1)

    # Initialize schema
    try:
        logger.info("Creating database schema...")
        db_manager.init_database(drop_existing=args.drop_existing)
        logger.info("✅ Database schema created successfully!")

        if args.sample_data:
            logger.info("Loading sample data...")
            load_sample_data(db_manager)
            logger.info("✅ Sample data loaded successfully!")

        # Verify tables were created
        with db_manager.session_scope() as session:
            from sqlalchemy import text

            # Use raw SQL to check tables exist
            result = session.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            )
            tables = [row[0] for row in result]

            logger.info(f"Created tables: {', '.join(tables)}")

            expected_tables = {
                "authors",
                "books",
                "patrons",
                "checkout_records",
                "return_records",
                "reservation_records",
            }

            missing_tables = expected_tables - set(tables)
            if missing_tables:
                logger.error(f"Missing expected tables: {missing_tables}")
                sys.exit(1)

        logger.info("✅ Database initialization complete!")
        logger.info("The Virtual Library MCP Server is ready to use.")

    except Exception as e:
        logger.exception(f"Database initialization failed: {e}")
        sys.exit(1)
    finally:
        db_manager.close()


def load_sample_data(db_manager):
    """
    Load sample data for testing the MCP server.

    This creates:
    - A few authors
    - Several books
    - Some patrons
    - Example checkouts and reservations
    """
    from datetime import date, datetime, timedelta

    from database import (
        Author,
        Book,
        CheckoutRecord,
        Patron,
        PatronStatusEnum,
        ReservationRecord,
    )

    with db_manager.session_scope() as session:
        # Create authors
        authors = [
            Author(
                id="author_fitzgerald01",
                name="F. Scott Fitzgerald",
                biography="F. Scott Fitzgerald (1896-1940) was an American novelist, essayist, and short story writer.",
                birth_date=date(1896, 9, 24),
                death_date=date(1940, 12, 21),
                nationality="American",
            ),
            Author(
                id="author_lee_harper",
                name="Harper Lee",
                biography="Harper Lee (1926-2016) was an American novelist best known for To Kill a Mockingbird.",
                birth_date=date(1926, 4, 28),
                death_date=date(2016, 2, 19),
                nationality="American",
            ),
            Author(
                id="author_orwell01",
                name="George Orwell",
                biography="George Orwell (1903-1950) was an English novelist, essayist, journalist and critic.",
                birth_date=date(1903, 6, 25),
                death_date=date(1950, 1, 21),
                nationality="British",
            ),
        ]
        session.add_all(authors)
        session.flush()  # Ensure authors are available for books

        # Create books
        books = [
            Book(
                isbn="9780743273565",
                title="The Great Gatsby",
                author_id="author_fitzgerald01",
                genre="Fiction",
                publication_year=1925,
                available_copies=2,
                total_copies=3,
                description="A classic American novel set in the Jazz Age on Long Island.",
            ),
            Book(
                isbn="9780061120084",
                title="To Kill a Mockingbird",
                author_id="author_lee_harper",
                genre="Fiction",
                publication_year=1960,
                available_copies=1,
                total_copies=2,
                description="A gripping tale of racial injustice in the American South.",
            ),
            Book(
                isbn="9780452284234",
                title="1984",
                author_id="author_orwell01",
                genre="Science Fiction",
                publication_year=1949,
                available_copies=0,
                total_copies=2,
                description="A dystopian social science fiction novel and cautionary tale.",
            ),
        ]
        session.add_all(books)
        session.flush()

        # Create patrons
        patrons = [
            Patron(
                id="patron_smith001",
                name="John Smith",
                email="john.smith@example.com",
                phone="5551234567",
                membership_date=date(2023, 1, 15),
                status=PatronStatusEnum.ACTIVE,
                borrowing_limit=5,
                current_checkouts=1,
            ),
            Patron(
                id="patron_doe_jane",
                name="Jane Doe",
                email="jane.doe@example.com",
                phone="5559876543",
                membership_date=date(2023, 6, 1),
                status=PatronStatusEnum.ACTIVE,
                borrowing_limit=3,
                current_checkouts=0,
            ),
        ]
        session.add_all(patrons)
        session.flush()

        # Create an active checkout
        checkout = CheckoutRecord(
            id="checkout_202401150001",
            patron_id="patron_smith001",
            book_isbn="9780452284234",
            checkout_date=datetime.now() - timedelta(days=7),
            due_date=date.today() + timedelta(days=7),
        )
        session.add(checkout)

        # Create a reservation
        reservation = ReservationRecord(
            id="reservation_202401150001",
            patron_id="patron_doe_jane",
            book_isbn="9780452284234",
            reservation_date=datetime.now() - timedelta(days=2),
            expiration_date=date.today() + timedelta(days=30),
            queue_position=1,
        )
        session.add(reservation)

        logger.info(f"Created {len(authors)} authors")
        logger.info(f"Created {len(books)} books")
        logger.info(f"Created {len(patrons)} patrons")
        logger.info("Created 1 active checkout and 1 reservation")


if __name__ == "__main__":
    main()
