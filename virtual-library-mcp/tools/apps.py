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
from fastmcp.apps import UI_MIME_TYPE, AppConfig, ResourceCSP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from prefab_ui.actions import SetState
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    H3,
    Alert,
    AlertDescription,
    AlertTitle,
    Badge,
    Card,
    CardContent,
    CardHeader,
    Column,
    DataTable,
    DataTableColumn,
    Grid,
    Heading,
    Metric,
    Progress,
    Row,
    Separator,
    Small,
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
from database.patron_repository import PatronRepository, PatronSearchParams
from database.repository import PaginationParams
from database.session import session_scope
from icons import BOOK_ICON, CARD_ICON, SPARKLE_ICON
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

    with PrefabApp(state={"selected": None}) as app, Column(gap=4, css_class="p-6"):
        with Row(gap=2, align="center"):
            Heading("Explore the Collection")
            Badge("Live catalog", variant="secondary")
        Text(
            f"Showing {len(rows)} of {total} matching titles. "
            "Search within the results, sort any column, or select a title for shelf details."
        )

        with Alert(variant="info"):
            if availability == "available":
                AlertTitle("On-shelf titles only")
                AlertDescription(
                    "Every result currently has at least one copy available for checkout."
                )
            else:
                AlertTitle("Need something available now?")
                AlertDescription(
                    "Ask for available titles or set availability to available before opening the catalog."
                )

        with Grid(columns=4, gap=4):
            Metric(label="Matching titles", value=str(total))
            Metric(label="On shelf in view", value=str(copies_on_shelf))
            Metric(label="Shelf availability", value=f"{shelf_rate}%")
            Metric(label="Genres shown", value=str(genres_shown))

        DataTable(
            columns=[
                DataTableColumn(key="title", header="Title", sortable=True),
                DataTableColumn(key="author", header="Author", sortable=True),
                DataTableColumn(key="call_number", header="Call no.", sortable=True),
                DataTableColumn(key="year", header="Year", sortable=True),
                DataTableColumn(key="status", header="Status", sortable=True),
            ],
            rows=rows,
            search=True,
            paginated=True,
            pageSize=10,
            on_row_click=SetState("selected", Rx("$event")),
        )

        with If(STATE.selected), Card():
            with CardHeader():
                with Row(gap=2, align="center"):
                    H3(Rx("selected.title"))
                    Badge(Rx("selected.genre"), variant="secondary")
                Text(Rx("selected.author"))
            with CardContent():
                with Grid(columns=3, gap=4):
                    with Column(gap=0):
                        Small("Call number")
                        Text(Rx("selected.call_number"))
                    with Column(gap=0):
                        Small("Location")
                        Text(Rx("selected.location"))
                    with Column(gap=0):
                        Small("Copies")
                        Text(Rx("selected.copies"))
                Separator()
                Text(Rx("selected.description"))
                Separator()
                with Grid(columns=3, gap=4):
                    with Column(gap=0):
                        Small("Format")
                        Text(Rx("selected.format"))
                    with Column(gap=0):
                        Small("Publication year")
                        Text(Rx("selected.year"))
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
                    "name": patron.name,
                    "contact_hint": f"{mask_email(patron.email)} · {mask_phone(patron.phone) or 'no phone'}",
                    "status": str(getattr(patron.status, "value", patron.status)).title(),
                    "expires": patron.expiration_date.isoformat()
                    if patron.expiration_date
                    else "No expiration date",
                    "current_checkouts": patron.current_checkouts,
                    "borrowing_limit": patron.borrowing_limit,
                    "available_slots": available_slots,
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

    with PrefabApp(state={"selected": initial_selection}) as app, Column(gap=4, css_class="p-6"):
        with Row(gap=2, align="center"):
            Heading("My Library Account")
            Badge("Private details masked", variant="secondary")
        Text(result_summary)

        with Alert(variant="info"):
            AlertTitle("You do not need your library card number")
            AlertDescription(
                "Search by your name, email address, or phone digits. Full contact details and addresses are never shown."
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
                on_row_click=SetState("selected", Rx("$event")),
            )
        else:
            with Alert(variant="warning"):
                AlertTitle("No account found")
                AlertDescription(
                    "Try the patron's full name, complete email address, or at least four phone digits."
                )

        with If(STATE.selected), Card():
            with CardHeader():
                H3(Rx("selected.name"))
                Text(Rx("selected.eligibility"))
            with CardContent():
                with Grid(columns=4, gap=4):
                    Metric(label="Membership", value=Rx("selected.status"))
                    Metric(label="Items checked out", value=Rx("selected.current_checkouts"))
                    Metric(label="Borrowing limit", value=Rx("selected.borrowing_limit"))
                    Metric(label="Fines", value=Rx("selected.fines"))
                Progress(
                    value=Rx("selected.current_checkouts * 100 / selected.borrowing_limit"),
                    variant="info",
                    size="sm",
                )
                Separator()
                with Grid(columns=2, gap=4):
                    with Column(gap=0):
                        Small("Membership expires")
                        Text(Rx("selected.expires"))
                    with Column(gap=0):
                        Small("Reading interests")
                        Text(Rx("selected.preferred_genres"))
                Separator()
                H3("Current loans")
                DataTable(
                    columns=[
                        DataTableColumn(key="title", header="Title", sortable=True),
                        DataTableColumn(key="due", header="Due date", sortable=True),
                        DataTableColumn(key="status", header="Status", sortable=True),
                    ],
                    rows=Rx("selected.active_loans"),
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
        Heading("Virtual Library Dashboard")
        Text(f"Inventory and reader activity for the last {days} days.")

        with Grid(columns=4, gap=4):
            Metric(label="Titles", value=f"{circulation['total_books']:,}")
            Metric(label="Copies on shelf", value=f"{circulation['available_copies']:,}")
            Metric(label="Checked out", value=f"{circulation['checked_out_copies']:,}")
            Metric(label="Circulation rate", value=f"{circulation['circulation_rate']}%")

        BarChart(
            data=genre_rows,
            series=[ChartSeries(data_key="checkout_count", label="Checkouts")],
            x_axis="genre",
            show_legend=False,
        )

        Separator()
        H3("Most borrowed books")
        DataTable(
            columns=[
                DataTableColumn(key="rank", header="#", sortable=True),
                DataTableColumn(key="title", header="Title", sortable=True),
                DataTableColumn(key="author", header="Author", sortable=True),
                DataTableColumn(key="checkouts", header="Checkouts", sortable=True),
                DataTableColumn(key="status", header="Status", sortable=True),
            ],
            rows=popular_rows,
            search=True,
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
    config = get_config()
    renderer_app = AppConfig(
        csp=ResourceCSP(**get_renderer_csp()),
        domain=config.base_url,
    )
    tool_app = AppConfig(resourceUri=PREFAB_RENDERER_URI)

    @mcp.resource(
        PREFAB_RENDERER_URI,
        name="Virtual Library App Renderer",
        mime_type=UI_MIME_TYPE,
        app=renderer_app,
    )
    def prefab_renderer() -> str:
        return get_renderer_html()

    for spec in APP_TOOL_SPECS:
        mcp.tool(
            spec.fn,
            name=spec.name,
            app=tool_app,
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
    "library_dashboard_app",
    "patron_account_app",
    "prefab_renderer_resource",
    "register",
    "renderer_resource_meta",
]
