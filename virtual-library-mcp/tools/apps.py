"""Read-only MCP Apps for visually exploring the virtual library.

FastMCP's ``app=True`` integration attaches the standard MCP Apps UI metadata,
registers the shared ``text/html;profile=mcp-app`` renderer resource, and
serializes each Prefab component tree into structured content. These tools are
registered only on the FastMCP protocol path used by current MCP Apps hosts;
the hand-built 2026-07-28 teaching transport remains framework-independent.
"""

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from prefab_ui.actions import SetState
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    H3,
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
    Row,
    Separator,
    Small,
    Text,
)
from prefab_ui.components.charts import BarChart, ChartSeries
from prefab_ui.components.control_flow import If
from prefab_ui.rx import STATE, Rx
from pydantic import Field

from database.author_repository import AuthorRepository
from database.book_repository import BookRepository, BookSearchParams, BookSortOptions
from database.repository import PaginationParams
from database.session import session_scope
from icons import BOOK_ICON, SPARKLE_ICON
from resources.stats import (
    get_circulation_stats_handler,
    get_genre_distribution_handler,
    get_popular_books_handler,
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
            "available_copies": book.available_copies,
            "total_copies": book.total_copies,
            "isbn": book.isbn,
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
    genres_shown = len({row["genre"] for row in rows})

    with PrefabApp(state={"selected": None}) as app, Column(gap=4, css_class="p-6"):
        Heading("Virtual Library Catalog")
        Text(
            f"Showing {len(rows)} of {total} matching titles. "
            "Search, sort, or select a row for details."
        )

        with Grid(columns=3, gap=4):
            Metric(label="Matching titles", value=str(total))
            Metric(label="Copies on shelf", value=str(copies_on_shelf))
            Metric(label="Genres shown", value=str(genres_shown))

        DataTable(
            columns=[
                DataTableColumn(key="title", header="Title", sortable=True),
                DataTableColumn(key="author", header="Author", sortable=True),
                DataTableColumn(key="genre", header="Genre", sortable=True),
                DataTableColumn(key="year", header="Year", sortable=True),
                DataTableColumn(key="availability", header="Availability", sortable=True),
            ],
            rows=rows,
            search=True,
            on_row_click=SetState("selected", Rx("$event")),
        )

        with If(STATE.selected), Card():
            with CardHeader(), Row(gap=2, align="center"):
                H3(Rx("selected.title"))
                Badge(Rx("selected.genre"), variant="secondary")
            with CardContent():
                with Grid(columns=3, gap=4):
                    with Column(gap=0):
                        Small("Author")
                        Text(Rx("selected.author"))
                    with Column(gap=0):
                        Small("ISBN")
                        Text(Rx("selected.isbn"))
                    with Column(gap=0):
                        Small("Availability")
                        Text(Rx("selected.availability"))
                Separator()
                Text(Rx("selected.description"))

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


def register(mcp: FastMCP) -> None:
    """Register the UI tools on the FastMCP path used by MCP Apps hosts."""
    annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    mcp.tool(
        browse_catalog_app,
        app=True,
        annotations=annotations,
        icons=[BOOK_ICON],
        tags={"app", "catalog"},
    )
    mcp.tool(
        library_dashboard_app,
        app=True,
        annotations=annotations,
        icons=[SPARKLE_ICON],
        tags={"app", "analytics"},
    )


__all__ = ["browse_catalog_app", "library_dashboard_app", "register"]
