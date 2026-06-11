"""
Database seeding script for the Virtual Library MCP Server.

The catalog (authors and books) is curated, real-world data loaded from
JSON files in ``database/seed_data/``. Patrons and circulation history are
simulated on top of it with deterministic randomness (seeded Faker/random),
so every seeded database tells the same coherent story:

- Books are real titles with accurate authors, years, genres, and original
  one-paragraph descriptions. ISBNs are *synthetic but structurally valid*
  ISBN-13s (correct check digit) derived from a hash of title+author, so the
  catalog never misattributes a real publisher identifier.
- Circulation is simulated patron-by-patron, month-by-month. Every derived
  number (a book's available copies, a patron's current/total checkouts,
  outstanding fines, even suspended status) is computed FROM the simulated
  checkout records rather than rolled independently. MCP stats resources
  therefore always agree with the underlying circulation data.

MCP relevance: seeded data feeds Resources (catalog browsing), Tools
(checkout/return against real availability), Prompts and Sampling
(recommendations grounded in plausible reading history), and Subscriptions
(state changes against a believable baseline).
"""

import hashlib
import json
import random
import unicodedata
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import cast

from faker import Faker
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.schema import (
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

# Deterministic generation: same catalog + same seed = same library
# (relative to the run date, since circulation is simulated up to "today").
fake = Faker()
Faker.seed(42)
random.seed(42)

SEED_DATA_DIR = Path(__file__).parent / "seed_data"

# Circulation policy constants — keep in sync with CirculationRepository.
LOAN_DAYS = 14
FINE_PER_DAY = 0.25
SUSPENSION_FINE_THRESHOLD = 10.0
HISTORY_MONTHS = 24

# How many copies the library owns, by curated popularity tier (1-5).
COPIES_BY_POPULARITY = {1: (1, 2), 2: (1, 3), 3: (2, 4), 4: (3, 5), 5: (4, 6)}


# ---------------------------------------------------------------------------
# Catalog loading (curated data)
# ---------------------------------------------------------------------------


def load_catalog() -> list[dict]:
    """Load and merge every curated collection file in seed_data/."""
    authors: list[dict] = []
    for path in sorted(SEED_DATA_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            collection = json.load(f)
        authors.extend(collection["authors"])
    if not authors:
        raise FileNotFoundError(f"No seed collections found in {SEED_DATA_DIR}")
    return authors


def _ascii_slug(text: str) -> str:
    """Lowercase ASCII identifier fragment: 'García Márquez' -> 'garcia_marquez'."""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    cleaned = "".join(c if c.isalnum() else "_" for c in ascii_text.lower())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_")


def author_id_for(name: str, used: set[str]) -> str:
    """Readable, unique author ID: 'Jane Austen' -> 'author_austen_jane'."""
    parts = [p for p in (_ascii_slug(part) for part in name.split()) if p]
    base = f"{parts[-1]}_{parts[0]}" if len(parts) >= 2 else parts[0]
    # Model requires at least 5 chars after the 'author_' prefix.
    base = base.ljust(5, "0")
    candidate = f"author_{base}"
    suffix = 2
    while candidate in used:
        candidate = f"author_{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def isbn_check_digit(first_twelve: str) -> str:
    """Compute the ISBN-13 check digit (alternating 1/3 weights)."""
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first_twelve))
    return str((10 - (total % 10)) % 10)


def isbn13_for(title: str, author_name: str, used: set[str]) -> str:
    """Derive a stable, checksum-valid ISBN-13 from title + author.

    Hash-derived rather than random so the same book always gets the same
    ISBN across reseeds — handy for demos, bookmarks, and bug reports.
    """
    digest = hashlib.md5(f"{title}|{author_name}".encode()).hexdigest()
    body = f"{int(digest, 16) % 10**9:09d}"
    while True:
        first_twelve = f"978{body}"
        isbn = first_twelve + isbn_check_digit(first_twelve)
        if isbn not in used:
            used.add(isbn)
            return isbn
        body = f"{(int(body) + 1) % 10**9:09d}"


def build_authors_and_books(catalog: list[dict]) -> tuple[list[Author], list[Book]]:
    """Materialize curated catalog entries as ORM rows."""
    authors: list[Author] = []
    books: list[Book] = []
    used_author_ids: set[str] = set()
    used_isbns: set[str] = set()

    for entry in catalog:
        author_id = author_id_for(entry["name"], used_author_ids)
        catalogued_at = fake.date_time_between(start_date="-3y", end_date="-1y")
        authors.append(
            Author(
                id=author_id,
                name=entry["name"],
                biography=entry.get("biography"),
                birth_date=date.fromisoformat(entry["birth_date"])
                if entry.get("birth_date")
                else None,
                death_date=date.fromisoformat(entry["death_date"])
                if entry.get("death_date")
                else None,
                nationality=entry.get("nationality"),
                created_at=catalogued_at,
                updated_at=catalogued_at,
            )
        )

        for book in entry["books"]:
            popularity = book.get("popularity", 2)
            low, high = COPIES_BY_POPULARITY[popularity]
            total_copies = random.randint(low, high)
            added_at = fake.date_time_between(start_date="-3y", end_date="-6M")
            books.append(
                Book(
                    isbn=isbn13_for(book["title"], entry["name"], used_isbns),
                    title=book["title"],
                    author_id=author_id,
                    genre=book["genre"],
                    publication_year=book["year"],
                    total_copies=total_copies,
                    available_copies=total_copies,  # adjusted after simulation
                    description=book["description"],
                    created_at=added_at,
                    updated_at=added_at,
                )
            )

    return authors, books


# ---------------------------------------------------------------------------
# Patrons (simulated people; names/contact details are synthetic)
# ---------------------------------------------------------------------------

# Reading personas give patrons coherent tastes instead of uniform randomness.
PERSONAS: dict[str, list[str]] = {
    "literary": ["Fiction", "Historical Fiction", "Poetry", "Drama"],
    "speculative": ["Science Fiction", "Fantasy", "Dystopian", "Horror"],
    "page_turner": ["Mystery", "Thriller", "True Crime", "Romance"],
    "curious_mind": ["Science", "History", "Psychology", "Philosophy"],
    "self_improver": ["Self-Help", "Business", "Memoir", "Biography"],
    "young_at_heart": ["Young Adult", "Children", "Fantasy", "Adventure"],
}


def build_patrons(num_patrons: int = 60) -> tuple[list[Patron], dict[str, float]]:
    """Generate synthetic patrons with personas and unique contact details.

    Returns the patrons plus a per-patron monthly reading rate used only by
    the circulation simulation (not a persisted column).
    """
    patrons: list[Patron] = []
    reading_rates: dict[str, float] = {}
    used_emails: set[str] = set()
    today = date.today()

    for i in range(num_patrons):
        name = fake.name()
        slug = _ascii_slug(name).replace("_", ".")
        email = f"{slug}@example.com"
        if email in used_emails:
            email = f"{slug}{i}@example.com"
        used_emails.add(email)

        # A few recent sign-ups stay PENDING with no history yet.
        is_pending = i % 23 == 0
        if is_pending:
            membership_date = fake.date_between(start_date="-13d", end_date="today")
        else:
            membership_date = fake.date_between(start_date="-5y", end_date="-3M")

        # Memberships run in 1-year terms; ~12% lapsed without renewing.
        # A lapse is only possible if a full term fits before "recently".
        earliest_lapse = membership_date + timedelta(days=365)
        can_have_lapsed = earliest_lapse < today - timedelta(days=14)
        if not is_pending and can_have_lapsed and random.random() < 0.12:
            expiration_date = fake.date_between(
                start_date=max(earliest_lapse, today - timedelta(days=700)),
                end_date=today - timedelta(days=14),
            )
        else:
            expiration_date = today + timedelta(days=random.randint(30, 540))

        # Most patrons share a persona's core tastes with a personal twist.
        persona_genres = random.choice(list(PERSONAS.values()))
        extra_pool = [g for genres in PERSONAS.values() for g in genres]
        preferred = list(
            dict.fromkeys([*random.sample(persona_genres, 3), random.choice(extra_pool)])
        )

        patrons.append(
            Patron(
                id=f"patron_{i + 1:05d}",
                name=name,
                email=email,
                phone=fake.numerify("(###) ###-####"),
                address=fake.address().replace("\n", ", "),
                membership_date=membership_date,
                expiration_date=expiration_date,
                status=PatronStatusEnum.PENDING if is_pending else PatronStatusEnum.ACTIVE,
                borrowing_limit=random.choice([3, 5, 5, 5, 10, 10, 15]),
                current_checkouts=0,  # derived from simulation
                total_checkouts=0,  # derived from simulation
                outstanding_fines=0.0,  # derived from simulation
                preferred_genres=json.dumps(preferred),
                notification_preferences=json.dumps({"email": True, "sms": random.random() < 0.3}),
                created_at=datetime.combine(membership_date, time(10, 0)),
                updated_at=datetime.now(),
                last_activity=None,  # derived from simulation
            )
        )
        # Mix of occasional readers and voracious ones (books per month).
        reading_rates[patrons[-1].id] = random.choice([0.4, 0.8, 1.0, 1.5, 2.5, 4.0])

    return patrons, reading_rates


# ---------------------------------------------------------------------------
# Circulation simulation
# ---------------------------------------------------------------------------


def _weighted_book_pool(books: list[Book]) -> list[str]:
    """ISBN pool weighted by copies^2, so well-stocked popular titles circulate most.

    Copy counts were themselves derived from curated popularity, making this a
    cheap proxy: a 6-copy bestseller appears 36x more often than a 1-copy title.
    """
    pool: list[str] = []
    for book in books:
        weight = max(1, int(book.total_copies)) ** 2
        pool.extend([book.isbn] * weight)
    return pool


def simulate_circulation(
    patrons: list[Patron], books: list[Book], reading_rates: dict[str, float]
) -> tuple[list[CheckoutRecord], list[ReturnRecord], list[ReservationRecord]]:
    """Simulate HISTORY_MONTHS of borrowing and derive all aggregate state."""
    today = datetime.now().date()
    pool = _weighted_book_pool(books)
    genre_index: dict[str, list[str]] = {}
    for book in books:
        genre_index.setdefault(book.genre, []).append(book.isbn)

    available = {b.isbn: b.total_copies for b in books}
    raw_checkouts: list[dict] = []
    active_counts: dict[str, int] = {}

    for patron in patrons:
        if patron.status == PatronStatusEnum.PENDING:
            continue
        preferred = json.loads(patron.preferred_genres)
        preferred_isbns = [i for g in preferred for i in genre_index.get(g, [])]
        rate = reading_rates[patron.id]

        # cast() because the legacy declarative schema types attributes as Column[...]
        membership = cast("date", patron.membership_date)
        expiration = cast("date", patron.expiration_date)  # always set by build_patrons
        start = max(membership, today - timedelta(days=HISTORY_MONTHS * 30))
        borrowing_end = min(expiration, today)
        cursor = start
        active_count = 0

        while cursor < borrowing_end:
            # How many books this patron borrows this month.
            month_checkouts = int(rate) + (1 if random.random() < (rate % 1) else 0)
            for _ in range(month_checkouts):
                checkout_day = cursor + timedelta(days=random.randint(0, 27))
                if checkout_day >= borrowing_end:
                    continue
                # 70% of picks come from the patron's preferred genres.
                if preferred_isbns and random.random() < 0.7:
                    isbn = random.choice(preferred_isbns)
                else:
                    isbn = random.choice(pool)

                checkout_date = datetime.combine(
                    checkout_day, time(random.randint(9, 19), random.randint(0, 59))
                )
                due = checkout_day + timedelta(days=LOAN_DAYS)
                days_out = (today - checkout_day).days

                # Recent checkouts may still be open; older ones are returned.
                still_out = days_out <= LOAN_DAYS and random.random() < 0.8
                overdue_unreturned = (
                    LOAN_DAYS < days_out <= LOAN_DAYS + 30 and random.random() < 0.12
                )

                if still_out or overdue_unreturned:
                    if active_count >= patron.borrowing_limit or available[isbn] <= 0:
                        continue
                    available[isbn] -= 1
                    active_count += 1
                    raw_checkouts.append(
                        {
                            "patron": patron,
                            "isbn": isbn,
                            "checkout_date": checkout_date,
                            "due": due,
                            "returned": None,
                        }
                    )
                else:
                    # Returned: 82% on time, 18% late with a daily fine.
                    if random.random() < 0.82:
                        return_day = checkout_day + timedelta(days=random.randint(2, LOAN_DAYS))
                        return_day = min(return_day, today)
                    else:
                        return_day = due + timedelta(days=random.randint(1, 21))
                        return_day = min(return_day, today)
                    raw_checkouts.append(
                        {
                            "patron": patron,
                            "isbn": isbn,
                            "checkout_date": checkout_date,
                            "due": due,
                            "returned": datetime.combine(
                                return_day, time(random.randint(9, 19), random.randint(0, 59))
                            ),
                        }
                    )
            cursor += timedelta(days=30)
        active_counts[patron.id] = active_count

    # Engineer bestseller scarcity: drain the remaining copies of the most
    # popular titles with fresh checkouts so reservation queues form — the
    # state that makes availability tracking and queue tools worth demoing.
    bestsellers = sorted(books, key=lambda b: b.total_copies, reverse=True)[:12]
    open_borrowers = [
        p for p in patrons if p.status == PatronStatusEnum.ACTIVE and p.expiration_date > today
    ]
    for book in bestsellers:
        while available[book.isbn] > 0:
            with_capacity = [
                p for p in open_borrowers if active_counts.get(p.id, 0) < p.borrowing_limit
            ]
            if not with_capacity:
                break
            patron = random.choice(with_capacity)
            checkout_day = today - timedelta(days=random.randint(0, LOAN_DAYS - 2))
            available[book.isbn] -= 1
            active_counts[patron.id] = active_counts.get(patron.id, 0) + 1
            raw_checkouts.append(
                {
                    "patron": patron,
                    "isbn": book.isbn,
                    "checkout_date": datetime.combine(
                        checkout_day, time(random.randint(9, 19), random.randint(0, 59))
                    ),
                    "due": checkout_day + timedelta(days=LOAN_DAYS),
                    "returned": None,
                }
            )

    # Materialize ORM rows in chronological order so IDs read naturally.
    raw_checkouts.sort(key=lambda c: c["checkout_date"])
    checkouts: list[CheckoutRecord] = []
    returns: list[ReturnRecord] = []
    fines_by_patron: dict[str, float] = {}
    activity_by_patron: dict[str, datetime] = {}
    totals_by_patron: dict[str, int] = {}
    active_by_patron: dict[str, int] = {}

    for i, raw in enumerate(raw_checkouts, start=1):
        patron = raw["patron"]
        checkout_id = f"checkout_{i:06d}"
        returned: datetime | None = raw["returned"]
        due: date = raw["due"]

        totals_by_patron[patron.id] = totals_by_patron.get(patron.id, 0) + 1
        last_event = returned or raw["checkout_date"]
        if patron.id not in activity_by_patron or last_event > activity_by_patron[patron.id]:
            activity_by_patron[patron.id] = last_event

        if returned is not None:
            late_days = max(0, (returned.date() - due).days)
            fine = round(late_days * FINE_PER_DAY, 2)
            fine_is_paid = fine == 0 or random.random() < 0.92
            if not fine_is_paid:
                fines_by_patron[patron.id] = fines_by_patron.get(patron.id, 0.0) + fine
            checkouts.append(
                CheckoutRecord(
                    id=checkout_id,
                    patron_id=patron.id,
                    book_isbn=raw["isbn"],
                    checkout_date=raw["checkout_date"],
                    due_date=due,
                    return_date=returned,
                    status=CirculationStatusEnum.COMPLETED,
                    renewal_count=random.choices([0, 1, 2], weights=[75, 20, 5])[0],
                    fine_amount=fine,
                    fine_paid=fine_is_paid,
                    created_at=raw["checkout_date"],
                    updated_at=returned,
                )
            )
            returns.append(
                ReturnRecord(
                    id=f"return_{i:06d}",
                    checkout_id=checkout_id,
                    patron_id=patron.id,
                    book_isbn=raw["isbn"],
                    return_date=returned,
                    condition=random.choices(
                        ["excellent", "good", "fair", "poor"], weights=[20, 65, 12, 3]
                    )[0],
                    late_days=late_days,
                    fine_assessed=fine,
                    fine_paid=fine if fine_is_paid else 0.0,
                    processed_by="Front Desk",
                    created_at=returned,
                )
            )
        else:
            is_overdue = due < today
            accrued = round(max(0, (today - due).days) * FINE_PER_DAY, 2)
            if accrued:
                fines_by_patron[patron.id] = fines_by_patron.get(patron.id, 0.0) + accrued
            active_by_patron[patron.id] = active_by_patron.get(patron.id, 0) + 1
            checkouts.append(
                CheckoutRecord(
                    id=checkout_id,
                    patron_id=patron.id,
                    book_isbn=raw["isbn"],
                    checkout_date=raw["checkout_date"],
                    due_date=due,
                    return_date=None,
                    status=CirculationStatusEnum.OVERDUE
                    if is_overdue
                    else CirculationStatusEnum.ACTIVE,
                    renewal_count=random.choices([0, 1], weights=[85, 15])[0],
                    fine_amount=accrued,
                    fine_paid=False,
                    created_at=raw["checkout_date"],
                    updated_at=raw["checkout_date"],
                )
            )

    # Push derived aggregates back onto patrons and books.
    for patron in patrons:
        patron.total_checkouts = totals_by_patron.get(patron.id, 0)
        patron.current_checkouts = active_by_patron.get(patron.id, 0)
        patron.outstanding_fines = round(fines_by_patron.get(patron.id, 0.0), 2)
        patron.last_activity = activity_by_patron.get(patron.id)
        # Status is a consequence of the data: lapsed term -> EXPIRED,
        # heavy unpaid fines -> SUSPENDED. (PENDING was set at creation.)
        if patron.status == PatronStatusEnum.ACTIVE:
            if patron.expiration_date and patron.expiration_date < today:
                patron.status = PatronStatusEnum.EXPIRED
            elif patron.outstanding_fines > SUSPENSION_FINE_THRESHOLD:
                patron.status = PatronStatusEnum.SUSPENDED

    for book in books:
        book.available_copies = available[book.isbn]

    # Reservations: queues form on popular titles with no copies on the shelf.
    reservations: list[ReservationRecord] = []
    eligible_patrons = [p for p in patrons if p.status == PatronStatusEnum.ACTIVE]
    hot_and_gone = [b for b in books if available[b.isbn] == 0 and b.total_copies >= 3]
    holders: dict[str, set[str]] = {}
    for c in checkouts:
        if c.return_date is None:
            holders.setdefault(c.book_isbn, set()).add(c.patron_id)

    counter = 1
    for book in hot_and_gone:
        queue_size = random.randint(1, 4)
        waiting = [p for p in eligible_patrons if p.id not in holders.get(book.isbn, set())]
        for position, patron in enumerate(random.sample(waiting, min(queue_size, len(waiting))), 1):
            reserved_at = fake.date_time_between(start_date="-30d", end_date="now")
            reservations.append(
                ReservationRecord(
                    id=f"reservation_{counter:05d}",
                    patron_id=patron.id,
                    book_isbn=book.isbn,
                    reservation_date=reserved_at,
                    expiration_date=(reserved_at + timedelta(days=90)).date(),
                    status=ReservationStatusEnum.PENDING,
                    queue_position=position,
                    created_at=reserved_at,
                    updated_at=reserved_at,
                )
            )
            counter += 1

    return checkouts, returns, reservations


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def verify_consistency(
    books: list[Book], patrons: list[Patron], checkouts: list[CheckoutRecord]
) -> None:
    """Assert the invariants that make the demo data trustworthy."""
    open_by_isbn: dict[str, int] = {}
    open_by_patron: dict[str, int] = {}
    for c in checkouts:
        if c.return_date is None:
            open_by_isbn[c.book_isbn] = open_by_isbn.get(c.book_isbn, 0) + 1
            open_by_patron[c.patron_id] = open_by_patron.get(c.patron_id, 0) + 1

    for book in books:
        expected = book.total_copies - open_by_isbn.get(book.isbn, 0)
        assert book.available_copies == expected, f"availability drift on {book.isbn}"
        assert 0 <= book.available_copies <= book.total_copies

    for patron in patrons:
        assert patron.current_checkouts == open_by_patron.get(patron.id, 0)
        assert patron.current_checkouts <= patron.borrowing_limit


def seed_database(database_url: str = "sqlite:///library.db") -> None:
    """Create the schema and populate it with the curated + simulated dataset."""
    engine = create_engine(database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    print("Loading curated catalog from seed_data/ ...")
    catalog = load_catalog()
    authors, books = build_authors_and_books(catalog)
    patrons, reading_rates = build_patrons()
    print(f"  {len(authors)} authors, {len(books)} books, {len(patrons)} patrons")

    print("Simulating circulation history ...")
    checkouts, returns, reservations = simulate_circulation(patrons, books, reading_rates)
    verify_consistency(books, patrons, checkouts)

    session = Session(engine)
    try:
        for label, rows in (
            ("authors", authors),
            ("books", books),
            ("patrons", patrons),
            ("checkouts", checkouts),
            ("returns", returns),
            ("reservations", reservations),
        ):
            session.add_all(rows)
            session.commit()
            print(f"  inserted {len(rows):>5} {label}")

        print("\n" + "=" * 56)
        print("DATABASE SEEDING COMPLETE")
        print("=" * 56)
        print(f"Authors:       {len(authors):,}")
        print(f"Books:         {len(books):,} ({sum(b.total_copies for b in books):,} copies)")
        print(f"Patrons:       {len(patrons):,}")
        for status in PatronStatusEnum:
            count = sum(1 for p in patrons if p.status == status)
            print(f"  - {status.value:<10} {count}")
        print(f"Checkouts:     {len(checkouts):,}")
        for status in (
            CirculationStatusEnum.ACTIVE,
            CirculationStatusEnum.OVERDUE,
            CirculationStatusEnum.COMPLETED,
        ):
            count = sum(1 for c in checkouts if c.status == status)
            print(f"  - {status.value:<10} {count}")
        print(f"Returns:       {len(returns):,}")
        print(f"Reservations:  {len(reservations):,}")
        print("=" * 56)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    db_path = Path(__file__).parent.parent / "data" / "library.db"
    db_path.parent.mkdir(exist_ok=True)

    print("Seeding the Virtual Library ...")
    print(f"Database location: {db_path}")
    seed_database(f"sqlite:///{db_path}")
