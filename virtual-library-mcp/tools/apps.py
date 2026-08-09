# ruff: noqa: SIM117
"""Read-only MCP Apps for visually exploring the virtual library.

FastMCP attaches standard MCP Apps UI metadata while Prefab serializes each
component tree into structured content. The renderer is registered explicitly
so its stable sandbox domain survives on the wire. Shared app definitions also
let the hand-built 2026-07-28 teaching transport advertise the independent MCP
Apps extension without changing either core protocol version.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.apps import UI_MIME_TYPE, PrefabAppConfig, ResourceCSP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from prefab_ui.actions import RequestDisplayMode, SendMessage, SetState
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    H3,
    Alert,
    AlertDescription,
    AlertTitle,
    Badge,
    Button,
    Card,
    CardContent,
    CardHeader,
    Column,
    DataTable,
    DataTableColumn,
    Grid,
    Heading,
    Metric,
    Page,
    Pages,
    Progress,
    Row,
    Separator,
    Small,
    Tab,
    Tabs,
    Text,
)
from prefab_ui.components.charts import BarChart, ChartSeries
from prefab_ui.components.control_flow import If
from prefab_ui.renderer import get_renderer_csp, get_renderer_html
from prefab_ui.rx import STATE, Rx
from pydantic import Field

from config import get_config
from database.author_repository import AuthorRepository
from database.book_repository import BookRepository, BookSearchParams, BookSortOptions
from database.circulation_repository import CirculationRepository
from database.patron_repository import PatronRepository, PatronSearchParams
from database.repository import PaginationParams
from database.session import session_scope
from icons import BOOK_ICON, CARD_ICON, SPARKLE_ICON
from resources.recommendations import get_patron_recommendations_handler
from resources.stats import (
    get_circulation_stats_handler,
    get_genre_distribution_handler,
    get_popular_books_handler,
)

from .patrons import mask_email, mask_phone

PREFAB_RENDERER_URI = "ui://virtual-library/prefab/renderer-v1.html"
MCP_APPS_EXTENSION_ID = "io.modelcontextprotocol/ui"

_COLLECTION_CODES = {
    "Adventure": "ADV",
    "Biography": "BIO",
    "Business": "BUS",
    "Children": "JUV",
    "Drama": "DRA",
    "Dystopian": "DYS",
    "Fantasy": "FAN",
    "Fiction": "FIC",
    "Historical Fiction": "HIS FIC",
    "History": "HIS",
    "Horror": "HOR",
    "Memoir": "MEM",
    "Mystery": "MYS",
    "Philosophy": "PHI",
    "Poetry": "POE",
    "Psychology": "PSY",
    "Romance": "ROM",
    "Science": "SCI",
    "Science Fiction": "SF",
    "Self-Help": "SELF",
    "Thriller": "THR",
    "True Crime": "364.1",
    "Young Adult": "YA",
}


def _author_mark(author_name: str) -> str:
    """Return a compact, readable shelf mark from an author's surname."""
    surname = author_name.rsplit(maxsplit=1)[-1]
    normalized = unicodedata.normalize("NFKD", surname).encode("ascii", "ignore").decode()
    letters = re.sub(r"[^A-Za-z]", "", normalized).upper()
    return (letters[:3] or "UNK").ljust(3, "X")


def _catalog_location(genre: str) -> str:
    """Map a genre to the kind of collection label patrons see in libraries."""
    if genre == "Young Adult":
        return "Teen Collection"
    if genre == "Children":
        return "Children's Room"
    if genre in {
        "Biography",
        "Business",
        "History",
        "Philosophy",
        "Psychology",
        "Science",
        "Self-Help",
        "True Crime",
    }:
        return "Adult Nonfiction"
    return "Adult Fiction"


def _detail_buttons(
    rows: list[dict[str, Any]],
    *,
    label_key: str,
    destination: str,
    prompt: str,
) -> None:
    """Add explicit drill-down controls for MCP App renderers without row events."""
    if not rows:
        return

    with Column(gap=2):
        Small(prompt)
        with Grid(columns=2, gap=2):
            for row in rows:
                Button(
                    f"Open {row[label_key]}",
                    icon="arrow-right",
                    variant="outline",
                    size="sm",
                    on_click=[
                        SetState("selected", row),
                        SetState("page", destination),
                    ],
                )


def _catalog_rows(
    query: str | None,
    genre: str | None,
    available_only: bool,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """Load display-ready catalog rows and the total matching count."""
    query = query.strip() if query and query.strip() else None
    genre = genre.strip().title() if genre and genre.strip() else None

    with session_scope() as session:
        books = BookRepository(session).search(
            search_params=BookSearchParams(
                query=query,
                genre=genre,
                available_only=available_only,
            ),
            pagination=PaginationParams(page=1, page_size=limit),
            sort_by=BookSortOptions.TITLE,
        )
        author_repo = AuthorRepository(session)
        author_names = {}
        for book in books.items:
            if book.author_id not in author_names:
                author = author_repo.get_by_id(book.author_id)
                author_names[book.author_id] = author.name if author else "Unknown author"

    rows = [
        {
            "title": book.title,
            "author": author_names[book.author_id],
            "genre": book.genre,
            "year": book.publication_year,
            "availability": (
                f"On shelf ({book.available_copies}/{book.total_copies})"
                if book.available_copies
                else f"Checked out (0/{book.total_copies})"
            ),
            "status": "Available" if book.available_copies else "All copies out",
            "copies": f"{book.available_copies} of {book.total_copies} available",
            "available_copies": book.available_copies,
            "total_copies": book.total_copies,
            "isbn": book.isbn,
            "format": "Print book",
            "call_number": f"{_COLLECTION_CODES.get(book.genre, 'GEN')} {_author_mark(author_names[book.author_id])}",
            "location": _catalog_location(book.genre),
            "description": book.description or "No description is available for this title.",
        }
        for book in books.items
    ]
    return rows, books.total


async def browse_catalog_app(
    query: Annotated[
        str | None,
        Field(description="Optional title, author, description, or ISBN search", max_length=200),
    ] = None,
    genre: Annotated[
        str | None,
        Field(description="Optional exact genre filter, such as Science Fiction"),
    ] = None,
    availability: Annotated[
        Literal["all", "available"],
        Field(description="Show all titles or only titles with copies on the shelf"),
    ] = "all",
    limit: Annotated[
        int,
        Field(description="Maximum number of rows to display", ge=1, le=50),
    ] = 30,
) -> PrefabApp:
    """Use this when the user wants to browse or visually search the book catalog."""
    rows, total = _catalog_rows(query, genre, availability == "available", limit)
    copies_on_shelf = sum(row["available_copies"] for row in rows)
    copies_in_view = sum(row["total_copies"] for row in rows)
    genres_shown = len({row["genre"] for row in rows})
    shelf_rate = round((copies_on_shelf / copies_in_view) * 100) if copies_in_view else 0

    with (
        PrefabApp(state={"page": "catalog", "selected": None}) as app,
        Column(gap=4, css_class="p-6"),
    ):
        with Pages(name="page", value="catalog"):
            with Page("Catalog", value="catalog"):
                with Row(gap=2, align="center"):
                    Heading("Explore the Collection")
                    Badge("Live catalog", variant="secondary")
                Button(
                    "Open full screen",
                    icon="maximize-2",
                    variant="outline",
                    size="sm",
                    on_click=RequestDisplayMode("fullscreen"),
                )
                Text(
                    f"Showing {len(rows)} of {total} matching titles. "
                    "Search, sort, and open a title for a full shelf record."
                )

                with Alert(variant="info"):
                    if availability == "available":
                        AlertTitle("Ready to borrow")
                        AlertDescription(
                            "Every result currently has at least one copy on the shelf."
                        )
                    else:
                        AlertTitle("Live availability")
                        AlertDescription(
                            "Availability can change after checkout or return; the shelf count is current."
                        )

                with Grid(columns=2, gap=4):
                    Metric(label="Matching titles", value=str(total))
                    Metric(label="Copies on shelf", value=str(copies_on_shelf))
                    Metric(label="Shelf availability", value=f"{shelf_rate}%")
                    Metric(label="Genres in view", value=str(genres_shown))

                DataTable(
                    columns=[
                        DataTableColumn(key="title", header="Title", sortable=True),
                        DataTableColumn(key="author", header="Author", sortable=True),
                        DataTableColumn(key="status", header="Status", sortable=True),
                    ],
                    rows=rows,
                    search=True,
                    paginated=True,
                    pageSize=10,
                    on_row_click=[
                        SetState("selected", Rx("$event")),
                        SetState("page", "details"),
                    ],
                )
                _detail_buttons(
                    rows,
                    label_key="title",
                    destination="details",
                    prompt="Open a shelf record",
                )

            with Page("Book details", value="details"):
                with If(STATE.selected):
                    with Column(gap=2):
                        Button(
                            "Back to catalog",
                            icon="arrow-left",
                            variant="outline",
                            on_click=SetState("page", "catalog"),
                        )
                        Button(
                            "Check borrowing readiness",
                            icon="badge-check",
                            variant="default",
                            on_click=SendMessage(
                                "Check whether I can borrow {{selected.title}}. Use the checkout readiness app before making any changes."
                            ),
                        )
                    with Card():
                        with CardHeader():
                            with Row(gap=2, align="center"):
                                H3(Rx("selected.title"))
                                Badge(Rx("selected.status"), variant="secondary")
                            Text(Rx("selected.author"))
                        with CardContent():
                            with Tabs(value="summary", variant="line"):
                                with Tab("Summary", value="summary"):
                                    Text(Rx("selected.description"))
                                with Tab("Availability", value="availability"):
                                    with Grid(columns=3, gap=4):
                                        Metric(label="Status", value=Rx("selected.status"))
                                        Metric(label="Copies", value=Rx("selected.copies"))
                                        Metric(label="Format", value=Rx("selected.format"))
                                    Text(
                                        "Ask for checkout readiness to verify the patron account before any loan is created."
                                    )
                                with Tab("Library record", value="record"):
                                    with Grid(columns=3, gap=4):
                                        with Column(gap=0):
                                            Small("Call number")
                                            Text(Rx("selected.call_number"))
                                        with Column(gap=0):
                                            Small("Location")
                                            Text(Rx("selected.location"))
                                        with Column(gap=0):
                                            Small("Publication year")
                                            Text(Rx("selected.year"))
                                    Separator()
                                    with Column(gap=0):
                                        Small("ISBN")
                                        Text(Rx("selected.isbn"))

    return app


def _patron_rows(query: str, limit: int) -> tuple[list[dict[str, Any]], int]:
    """Load privacy-minimized patron candidates with their current loans."""
    normalized_query = query.strip()
    phone_digits = re.sub(r"\D", "", normalized_query)
    if len(phone_digits) >= 4 and not any(char.isalpha() for char in normalized_query):
        normalized_query = phone_digits

    with session_scope() as session:
        patron_repo = PatronRepository(session)
        result = patron_repo.search(
            search_params=PatronSearchParams(query=normalized_query),
            pagination=PaginationParams(page=1, page_size=limit),
        )
        book_repo = BookRepository(session)
        rows = []
        for patron in result.items:
            activity = patron_repo.get_with_activity(patron.id)
            active_loans = []
            if activity:
                for loan in activity.active_checkouts:
                    book = book_repo.get_by_isbn(loan["book_isbn"])
                    due_date = loan["due_date"]
                    active_loans.append(
                        {
                            "title": book.title if book else "Unknown title",
                            "isbn": loan["book_isbn"],
                            "due": due_date.isoformat(),
                            "status": "Overdue" if due_date < date.today() else "Checked out",
                        }
                    )
            available_slots = max(0, patron.borrowing_limit - patron.current_checkouts)
            rows.append(
                {
                    "patron_id": patron.id,
                    "name": patron.name,
                    "contact_hint": f"{mask_email(patron.email)} · {mask_phone(patron.phone) or 'no phone'}",
                    "status": str(getattr(patron.status, "value", patron.status)).title(),
                    "expires": patron.expiration_date.isoformat()
                    if patron.expiration_date
                    else "No expiration date",
                    "current_checkouts": patron.current_checkouts,
                    "borrowing_limit": patron.borrowing_limit,
                    "available_slots": available_slots,
                    "can_checkout": patron.can_checkout,
                    "outstanding_fines": round(patron.outstanding_fines, 2),
                    "borrowed": f"{patron.current_checkouts} of {patron.borrowing_limit}",
                    "fines": f"${patron.outstanding_fines:.2f}",
                    "eligibility": (
                        f"Eligible to borrow {available_slots} more item(s)"
                        if patron.can_checkout
                        else "Borrowing unavailable; ask library staff for help"
                    ),
                    "preferred_genres": ", ".join(patron.preferred_genres)
                    or "No preferences saved",
                    "active_loans": active_loans,
                }
            )
    return rows, result.total


async def patron_account_app(
    query: Annotated[
        str,
        Field(
            min_length=2,
            max_length=120,
            description="Patron name, email address, or phone digits; no card number required",
        ),
    ],
    limit: Annotated[
        int,
        Field(description="Maximum candidate accounts to show", ge=1, le=10),
    ] = 5,
) -> PrefabApp:
    """Use this to find and view a patron account without knowing its patron number."""
    if len(query.strip()) < 2:
        raise ToolError("Enter at least two non-space characters to find an account.")
    rows, total = _patron_rows(query, limit)
    for row in rows:
        row.pop("patron_id", None)
    initial_selection = rows[0] if len(rows) == 1 else None
    if total > len(rows):
        result_summary = (
            f"Showing the first {len(rows)} of {total} accounts matching “{query.strip()}”. "
            "Add more of the name or contact detail to narrow the list."
        )
    elif rows:
        result_summary = (
            f"Found {total} account(s) matching “{query.strip()}”. "
            "Select your name and confirm the masked contact hint."
        )
    else:
        result_summary = f"No account matched “{query.strip()}”."

    initial_page = "account" if initial_selection else "matches"
    with (
        PrefabApp(state={"page": initial_page, "selected": initial_selection}) as app,
        Column(gap=4, css_class="p-6"),
    ):
        with Pages(name="page", value=initial_page):
            with Page("Account matches", value="matches"):
                with Row(gap=2, align="center"):
                    Heading("Find My Library Account")
                    Badge("Private details masked", variant="secondary")
                Text(result_summary)

                with Alert(variant="info"):
                    AlertTitle("No card number needed")
                    AlertDescription(
                        "Use a name, email address, or phone digits. Confirm the masked contact hint before opening an account."
                    )

                if rows:
                    DataTable(
                        columns=[
                            DataTableColumn(key="name", header="Name", sortable=True),
                            DataTableColumn(key="contact_hint", header="Contact hint"),
                            DataTableColumn(key="status", header="Membership", sortable=True),
                            DataTableColumn(key="borrowed", header="Items out", sortable=True),
                        ],
                        rows=rows,
                        search=True,
                        on_row_click=[
                            SetState("selected", Rx("$event")),
                            SetState("page", "account"),
                        ],
                    )
                    _detail_buttons(
                        rows,
                        label_key="name",
                        destination="account",
                        prompt="Choose an account",
                    )
                else:
                    with Alert(variant="warning"):
                        AlertTitle("No account found")
                        AlertDescription(
                            "Try the full name, complete email address, or at least four phone digits."
                        )

            with Page("Account", value="account"):
                with If(STATE.selected):
                    with Column(gap=2):
                        Button(
                            "Choose another account",
                            icon="arrow-left",
                            variant="outline",
                            on_click=SetState("page", "matches"),
                        )
                        Button(
                            "Find my next book",
                            icon="sparkles",
                            on_click=SendMessage(
                                "Show personalized reading recommendations for {{selected.name}} using the recommendations app."
                            ),
                        )
                    with Card():
                        with CardHeader():
                            with Row(gap=2, align="center"):
                                H3(Rx("selected.name"))
                                Badge(Rx("selected.status"), variant="secondary")
                            Text(Rx("selected.eligibility"))
                        with CardContent():
                            with Tabs(value="overview", variant="line"):
                                with Tab("Overview", value="overview"):
                                    with Grid(columns=2, gap=4):
                                        Metric(label="Membership", value=Rx("selected.status"))
                                        Metric(
                                            label="Items checked out",
                                            value=Rx("selected.current_checkouts"),
                                        )
                                        Metric(
                                            label="Borrowing limit",
                                            value=Rx("selected.borrowing_limit"),
                                        )
                                        Metric(label="Fines", value=Rx("selected.fines"))
                                    Progress(
                                        value=Rx(
                                            "selected.current_checkouts * 100 / selected.borrowing_limit"
                                        ),
                                        variant="info",
                                        size="sm",
                                    )
                                    Separator()
                                    with Column(gap=0):
                                        Small("Membership expires")
                                        Text(Rx("selected.expires"))
                                with Tab("Current loans", value="loans"):
                                    DataTable(
                                        columns=[
                                            DataTableColumn(
                                                key="title", header="Title", sortable=True
                                            ),
                                            DataTableColumn(
                                                key="due", header="Due date", sortable=True
                                            ),
                                            DataTableColumn(
                                                key="status", header="Status", sortable=True
                                            ),
                                        ],
                                        rows=Rx("selected.active_loans"),
                                    )
                                with Tab("Reading profile", value="profile"):
                                    with Column(gap=0):
                                        Small("Saved interests")
                                        Text(Rx("selected.preferred_genres"))
                                    Separator()
                                    Text(
                                        "Recommendations use borrowing history and saved interests; contact details remain masked."
                                    )

    return app


async def library_dashboard_app(
    days: Annotated[
        int,
        Field(description="Number of recent days to analyze", ge=1, le=365),
    ] = 30,
    popular_limit: Annotated[
        int,
        Field(description="Number of popular titles to display", ge=1, le=20),
    ] = 10,
) -> PrefabApp:
    """Use this when the user wants a visual snapshot of books and circulation."""
    circulation = await get_circulation_stats_handler()
    genre_result = await get_genre_distribution_handler(str(days))
    popular_result = await get_popular_books_handler(str(days), str(popular_limit))

    genre_rows = list(genre_result["genres"][:8])
    popular_rows = [
        {
            "rank": book["rank"],
            "title": book["title"],
            "author": book["author"],
            "checkouts": book["checkout_count"],
            "status": "Available" if book["currently_available"] else "Checked out",
        }
        for book in popular_result["books"]
    ]

    with PrefabApp() as app, Column(gap=4, css_class="p-6"):
        with Row(gap=2, align="center"):
            Heading("Library Pulse")
            Badge(f"Last {days} days", variant="secondary")
        Button(
            "Full screen",
            icon="maximize-2",
            variant="outline",
            size="sm",
            on_click=RequestDisplayMode("fullscreen"),
        )
        Text("A live view of collection health and what readers are borrowing.")

        with Tabs(value="overview", variant="line"):
            with Tab("Overview", value="overview"):
                with Grid(columns=2, gap=4):
                    Metric(label="Titles", value=f"{circulation['total_books']:,}")
                    Metric(label="Copies on shelf", value=f"{circulation['available_copies']:,}")
                    Metric(label="Checked out", value=f"{circulation['checked_out_copies']:,}")
                    Metric(label="Circulation rate", value=f"{circulation['circulation_rate']}%")
                with Alert(variant="info"):
                    AlertTitle("Collection snapshot")
                    AlertDescription(
                        "Counts update after checkout and return tools complete successfully."
                    )
            with Tab("Popular titles", value="popular"):
                H3("Most borrowed books")
                DataTable(
                    columns=[
                        DataTableColumn(key="title", header="Title", sortable=True),
                        DataTableColumn(key="checkouts", header="Checkouts", sortable=True),
                        DataTableColumn(key="status", header="Status", sortable=True),
                    ],
                    rows=popular_rows,
                    search=True,
                )
            with Tab("Genres", value="genres"):
                H3("Reader interest by genre")
                BarChart(
                    data=genre_rows,
                    series=[ChartSeries(data_key="checkout_count", label="Checkouts")],
                    x_axis="genre",
                    show_legend=False,
                )

    return app


async def checkout_readiness_app(
    book_query: Annotated[
        str,
        Field(
            min_length=2,
            max_length=200,
            description="Book title, author, or ISBN to check before checkout",
        ),
    ],
    patron_query: Annotated[
        str | None,
        Field(
            max_length=120,
            description=(
                "Optional patron name, email, or phone digits. A patron number is not required."
            ),
        ),
    ] = None,
) -> PrefabApp:
    """Use this before checkout to verify the title, account, and borrowing rules safely."""
    if len(book_query.strip()) < 2:
        raise ToolError("Enter at least two non-space characters to find a book.")
    if patron_query is not None and len(patron_query.strip()) < 2:
        raise ToolError("Enter at least two non-space characters to find an account.")

    books, book_total = _catalog_rows(book_query, None, False, 5)
    patrons, patron_total = _patron_rows(patron_query, 5) if patron_query else ([], 0)
    normalized_book_query = book_query.strip().casefold()
    exact_books = [
        candidate
        for candidate in books
        if candidate["title"].casefold() == normalized_book_query
        or candidate["isbn"] == normalized_book_query
    ]
    book = exact_books[0] if len(exact_books) == 1 else (books[0] if book_total == 1 else None)
    patron = patrons[0] if patron_total == 1 and patrons else None
    existing_checkout = None
    if book is not None and patron is not None:
        with session_scope() as session:
            existing_checkout = CirculationRepository(session).get_active_checkout_for_book(
                patron["patron_id"], book["isbn"]
            )
    for candidate in patrons:
        candidate.pop("patron_id", None)

    if book_total == 0:
        readiness = "Title not found"
        detail = "Try the full title, author name, or ISBN."
        variant = "warning"
    elif book is None and book_total > 1:
        readiness = "Choose a title"
        detail = f"{book_total} titles matched. Add more of the title or the ISBN."
        variant = "info"
    elif patron_query is None:
        readiness = "Account needed"
        detail = "Tell me your name, email address, or phone digits; no card number is needed."
        variant = "info"
    elif patron_total == 0:
        readiness = "Account not found"
        detail = "Try the patron's full name, complete email, or at least four phone digits."
        variant = "warning"
    elif patron_total > 1:
        readiness = "Confirm the account"
        detail = f"{patron_total} accounts matched. Use the masked contact hint to narrow it down."
        variant = "info"
    elif existing_checkout is not None:
        readiness = "Already checked out"
        detail = (
            f"This account already has the title. It is due "
            f"{existing_checkout.due_date.isoformat()}; another checkout is unnecessary."
        )
        variant = "info"
    elif not patron["can_checkout"]:
        readiness = "Account needs attention"
        detail = patron["eligibility"]
        variant = "warning"
    elif not book["available_copies"]:
        readiness = "Place a hold"
        detail = "All copies are out. The patron can join the reservation queue."
        variant = "warning"
    elif patron["outstanding_fines"] > 0:
        readiness = "Ready after confirmation"
        detail = (
            f"A copy is available, but the account has ${patron['outstanding_fines']:.2f} "
            "in fines. Confirm before checkout."
        )
        variant = "warning"
    else:
        readiness = "Ready to check out"
        detail = "The account is active, has borrowing room, and a copy is on the shelf."
        variant = "success"

    with PrefabApp() as app, Column(gap=4, css_class="p-6"):
        with Row(gap=2, align="center"):
            Heading("Checkout Readiness")
            Badge("Read-only preflight", variant="secondary")
        Text("Verify the book and patron before creating a loan.")

        with Alert(variant=variant):
            AlertTitle(readiness)
            AlertDescription(detail)

        with Column(gap=3):
            with Card():
                with CardHeader():
                    H3("Book")
                with CardContent():
                    with Column(gap=1):
                        if book is not None:
                            Text(f"{book['title']} — {book['author']}")
                            Small(f"{book['call_number']} · {book['location']}")
                            Text(book["copies"])
                        else:
                            Text(f"{book_total} matching title(s)")
                            Small("Narrow the search to one title.")
            with Card():
                with CardHeader():
                    H3("Patron")
                with CardContent():
                    with Column(gap=1):
                        if patron is not None:
                            Text(patron["name"])
                            Small(patron["contact_hint"])
                            Text(patron["eligibility"])
                        elif patron_query:
                            Text(f"{patron_total} matching account(s)")
                            Small("Confirm the masked contact hint.")
                        else:
                            Text("Not identified yet")
                            Small("A name, email, or phone digits will work.")

        if book is None and book_total > 1:
            H3("Matching titles")
            DataTable(
                columns=[
                    DataTableColumn(key="title", header="Title", sortable=True),
                    DataTableColumn(key="author", header="Author", sortable=True),
                    DataTableColumn(key="year", header="Year", sortable=True),
                    DataTableColumn(key="status", header="Status", sortable=True),
                ],
                rows=books,
            )
        if patron_total > 1:
            H3("Matching accounts")
            DataTable(
                columns=[
                    DataTableColumn(key="name", header="Name", sortable=True),
                    DataTableColumn(key="contact_hint", header="Contact hint"),
                    DataTableColumn(key="status", header="Membership", sortable=True),
                ],
                rows=patrons,
            )

        if readiness in {"Ready to check out", "Ready after confirmation"}:
            Button(
                "Ask to check out this book",
                icon="book-check",
                on_click=SendMessage(
                    "I have reviewed the checkout readiness result. Ask for confirmation if needed, then check out the selected title to the matched patron."
                ),
            )
        elif readiness == "Place a hold":
            Button(
                "Ask to place a hold",
                icon="bookmark-plus",
                on_click=SendMessage(
                    "The checkout readiness result says all copies are out. Help me place a hold for the matched patron."
                ),
            )

    return app


async def reading_recommendations_app(
    query: Annotated[
        str,
        Field(
            min_length=2,
            max_length=120,
            description="Patron name, email, or phone digits; no patron number required",
        ),
    ],
    limit: Annotated[
        int,
        Field(description="Maximum recommendations to display", ge=1, le=10),
    ] = 8,
) -> PrefabApp:
    """Use this to show a patron-friendly personalized reading list."""
    if len(query.strip()) < 2:
        raise ToolError("Enter at least two non-space characters to find an account.")
    patrons, total = _patron_rows(query, 5)
    patron = patrons[0] if total == 1 and patrons else None
    recommendations: list[dict[str, Any]] = []
    favorite_genres = ""
    if patron is not None:
        patron_id = patron["patron_id"]
        try:
            payload = await get_patron_recommendations_handler(patron_id)
        except Exception as exc:
            raise ToolError("Unable to build recommendations right now.") from exc
        favorite_genres = ", ".join(payload["favorite_genres"]) or patron["preferred_genres"]
        recommendations = [
            {
                "rank": item["rank"],
                "title": item["title"],
                "author": item["author"],
                "genre": item["genre"],
                "reason": item["reason"],
                "match": f"{round(item['score'])}%",
                "status": "Available" if item["available"] else "All copies out",
                "isbn": item["isbn"],
            }
            for item in payload["recommendations"][:limit]
        ]
    for candidate in patrons:
        candidate.pop("patron_id", None)

    with PrefabApp(state={"page": "list", "selected": None}) as app, Column(gap=4, css_class="p-6"):
        with Row(gap=2, align="center"):
            Heading("Your Next Read")
            Badge("Personalized", variant="secondary")

        if patron is None:
            if total:
                Text(
                    f"Found {total} matching accounts. Confirm the masked contact hint before viewing recommendations."
                )
                DataTable(
                    columns=[
                        DataTableColumn(key="name", header="Name", sortable=True),
                        DataTableColumn(key="contact_hint", header="Contact hint"),
                        DataTableColumn(key="status", header="Membership", sortable=True),
                    ],
                    rows=patrons,
                )
            else:
                with Alert(variant="warning"):
                    AlertTitle("Account not found")
                    AlertDescription(
                        "Try the full name, complete email, or at least four phone digits."
                    )
        else:
            Text(f"Recommendations for {patron['name']} based on library activity and interests.")
            with Alert(variant="info"):
                AlertTitle("Reading profile")
                AlertDescription(f"Top interests: {favorite_genres or 'broad reading'}")

            with Pages(name="page", value="list"):
                with Page("Recommendations", value="list"):
                    if recommendations:
                        DataTable(
                            columns=[
                                DataTableColumn(key="title", header="Title", sortable=True),
                                DataTableColumn(key="match", header="Match", sortable=True),
                                DataTableColumn(key="status", header="Status", sortable=True),
                            ],
                            rows=recommendations,
                            on_row_click=[
                                SetState("selected", Rx("$event")),
                                SetState("page", "details"),
                            ],
                        )
                        _detail_buttons(
                            recommendations,
                            label_key="title",
                            destination="details",
                            prompt="Open a recommendation",
                        )
                    else:
                        with Alert(variant="warning"):
                            AlertTitle("No fresh matches yet")
                            AlertDescription(
                                "Borrowing more titles will give the recommendation engine a stronger signal."
                            )
                with Page("Recommendation details", value="details"):
                    with If(STATE.selected):
                        Button(
                            "Back to recommendations",
                            icon="arrow-left",
                            variant="outline",
                            on_click=SetState("page", "list"),
                        )
                        with Card():
                            with CardHeader():
                                with Row(gap=2, align="center"):
                                    H3(Rx("selected.title"))
                                    Badge(Rx("selected.status"), variant="secondary")
                                Text(Rx("selected.author"))
                            with CardContent():
                                with Grid(columns=2, gap=4):
                                    Metric(label="Match", value=Rx("selected.match"))
                                    Metric(label="Genre", value=Rx("selected.genre"))
                                Separator()
                                Text(Rx("selected.reason"))
                                Separator()
                                with Column(gap=0):
                                    Small("ISBN")
                                    Text(Rx("selected.isbn"))
                        Button(
                            "Check borrowing readiness",
                            icon="badge-check",
                            on_click=SendMessage(
                                "Check whether I can borrow {{selected.title}} using the checkout readiness app before making any changes."
                            ),
                        )

    return app


@dataclass(frozen=True)
class AppToolSpec:
    """Framework-neutral metadata shared by both protocol revisions."""

    fn: Any
    name: str
    annotations: ToolAnnotations
    icons: list[Any]
    tags: frozenset[str]
    meta: dict[str, Any]


_APP_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_APP_TOOL_META = {"ui": {"resourceUri": PREFAB_RENDERER_URI}}

APP_TOOL_SPECS = [
    AppToolSpec(
        fn=browse_catalog_app,
        name="browse_catalog_app",
        annotations=_APP_ANNOTATIONS,
        icons=[BOOK_ICON],
        tags=frozenset({"app", "catalog"}),
        meta=_APP_TOOL_META,
    ),
    AppToolSpec(
        fn=library_dashboard_app,
        name="library_dashboard_app",
        annotations=_APP_ANNOTATIONS,
        icons=[SPARKLE_ICON],
        tags=frozenset({"app", "analytics"}),
        meta=_APP_TOOL_META,
    ),
    AppToolSpec(
        fn=patron_account_app,
        name="patron_account_app",
        annotations=_APP_ANNOTATIONS,
        icons=[CARD_ICON],
        tags=frozenset({"app", "patrons"}),
        meta=_APP_TOOL_META,
    ),
    AppToolSpec(
        fn=checkout_readiness_app,
        name="checkout_readiness_app",
        annotations=_APP_ANNOTATIONS,
        icons=[BOOK_ICON],
        tags=frozenset({"app", "catalog", "patrons", "readiness"}),
        meta=_APP_TOOL_META,
    ),
    AppToolSpec(
        fn=reading_recommendations_app,
        name="reading_recommendations_app",
        annotations=_APP_ANNOTATIONS,
        icons=[SPARKLE_ICON],
        tags=frozenset({"app", "catalog", "patrons", "recommendations"}),
        meta=_APP_TOOL_META,
    ),
]

APP_EXTENSION_CAPABILITIES = {
    MCP_APPS_EXTENSION_ID: {"mimeTypes": [UI_MIME_TYPE]},
}


def renderer_resource_meta() -> dict[str, Any]:
    """Return the reviewable CSP and optional production sandbox domain."""
    config = get_config()
    ui_meta: dict[str, Any] = {
        "csp": ResourceCSP(**get_renderer_csp()).model_dump(
            by_alias=True,
            exclude_none=True,
            mode="json",
        )
    }
    if config.base_url:
        ui_meta["domain"] = config.base_url
    return {"ui": ui_meta}


async def prefab_renderer_resource() -> str:
    """Serve the pinned Prefab renderer as an MCP Apps HTML resource."""
    return get_renderer_html()


def app_resource_definitions() -> list[dict[str, Any]]:
    """Return the modern registry's declaration for the shared renderer."""
    return [
        {
            "uri": PREFAB_RENDERER_URI,
            "name": "Virtual Library App Renderer",
            "description": "Sandboxed renderer for the virtual library MCP Apps.",
            "mime_type": UI_MIME_TYPE,
            "handler": prefab_renderer_resource,
            "meta": renderer_resource_meta(),
        }
    ]


def register(mcp: FastMCP) -> None:
    """Register the UI tools on the FastMCP path used by MCP Apps hosts."""
    for spec in APP_TOOL_SPECS:
        mcp.tool(
            spec.fn,
            name=spec.name,
            # FastMCP synthesizes an isolated, per-tool Prefab renderer URI.
            # ChatGPT binds a component resource to the tool that declared it;
            # sharing one hand-registered renderer across unrelated app tools
            # can leave the host with a stale or mismatched component schema.
            app=PrefabAppConfig(),
            annotations=spec.annotations,
            icons=spec.icons,
            tags=set(spec.tags),
        )


__all__ = [
    "APP_EXTENSION_CAPABILITIES",
    "APP_TOOL_SPECS",
    "MCP_APPS_EXTENSION_ID",
    "PREFAB_RENDERER_URI",
    "app_resource_definitions",
    "browse_catalog_app",
    "checkout_readiness_app",
    "library_dashboard_app",
    "patron_account_app",
    "prefab_renderer_resource",
    "reading_recommendations_app",
    "register",
    "renderer_resource_meta",
]
