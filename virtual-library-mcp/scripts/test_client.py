#!/usr/bin/env python3
"""
Virtual Library MCP Test Client

This comprehensive client demonstrates all features of the Virtual Library MCP Server
through an interactive CLI interface. It serves as both a testing tool and an
educational example for developers learning the Model Context Protocol.

Features demonstrated:
- Resources with pagination
- Tools with parameters
- Prompts for AI interactions
- Subscriptions (when implemented)
- Progress tracking for long operations
- Error handling and recovery

Author: Virtual Library MCP Team
"""

import asyncio
import json
import sys
from pathlib import Path

# Add parent directory to path to import from server
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from fastmcp import Client
    from fastmcp.exceptions import McpError

    # Note: ConnectionError might not exist in fastmcp.exceptions, using built-in
    MCPConnectionError = ConnectionError
except ImportError:
    print("Error: FastMCP not installed. Please install with: pip install fastmcp")
    sys.exit(1)


class Colors:
    """ANSI color codes for terminal output"""

    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"


class VirtualLibraryClient:
    """Interactive client for the Virtual Library MCP Server"""

    def __init__(self, server_path: str = "../server.py"):
        """Initialize the client with server connection details"""
        self.server_path = Path(server_path).resolve()
        if not self.server_path.exists():
            print(f"{Colors.RED}Error: Server file not found at {self.server_path}{Colors.END}")
            sys.exit(1)

        self.client = Client(str(self.server_path))
        self.running = True

        # Progress handler for long operations
        self.progress_handler = self._create_progress_handler()

    def _create_progress_handler(self):
        """Create a progress handler for tracking long operations"""

        async def handler(progress: float, total: float | None, message: str | None):
            if total:
                percentage = (progress / total) * 100
                bar_length = 30
                filled = int(bar_length * progress / total)
                bar = "█" * filled + "░" * (bar_length - filled)
                print(
                    f"\r{Colors.CYAN}[{bar}] {percentage:.1f}% - {message or ''}{Colors.END}",
                    end="",
                    flush=True,
                )
            else:
                print(
                    f"\r{Colors.CYAN}Progress: {progress} - {message or ''}{Colors.END}",
                    end="",
                    flush=True,
                )

        return handler

    async def connect(self):
        """Establish connection to the MCP server"""
        print(f"{Colors.YELLOW}Connecting to Virtual Library MCP Server...{Colors.END}")
        try:
            await self.client.__aenter__()
            print(f"{Colors.GREEN}✓ Connected successfully!{Colors.END}")

            # Test connection
            await self.client.ping()
            print(f"{Colors.GREEN}✓ Server is responsive{Colors.END}")

            # Get server info
            init_result = self.client.initialize_result
            print(f"\n{Colors.CYAN}Server Information:{Colors.END}")
            print(f"  Name: {init_result.server_info.name}")
            print(f"  Version: {init_result.server_info.version}")

            # Display capabilities
            caps = init_result.capabilities
            print(f"\n{Colors.CYAN}Server Capabilities:{Colors.END}")
            if hasattr(caps, "resources") and caps.resources:
                print("  ✓ Resources")
            if hasattr(caps, "tools") and caps.tools:
                print("  ✓ Tools")
            if hasattr(caps, "prompts") and caps.prompts:
                print("  ✓ Prompts")

        except MCPConnectionError as e:
            print(f"{Colors.RED}Failed to connect: {e}{Colors.END}")
            raise
        except Exception as e:
            print(f"{Colors.RED}Unexpected error during connection: {e}{Colors.END}")
            raise

    async def disconnect(self):
        """Close connection to the MCP server"""
        await self.client.__aexit__(None, None, None)
        print(f"\n{Colors.YELLOW}Disconnected from server{Colors.END}")

    def print_menu(self):
        """Display the main menu"""
        print(f"\n{Colors.HEADER}{'=' * 60}{Colors.END}")
        print(f"{Colors.BOLD}Virtual Library MCP Client - Main Menu{Colors.END}")
        print(f"{Colors.HEADER}{'=' * 60}{Colors.END}")
        print("\n1. Browse Resources (Books, Patrons, Stats)")
        print("2. Search & Catalog Operations")
        print("3. Circulation (Checkout, Return, Reserve)")
        print("4. AI Features (Recommendations, Reviews)")
        print("5. Bulk Operations (Import with Progress)")
        print("6. List All Available Operations")
        print("7. Test Error Handling")
        print("\n0. Exit")
        print(f"{Colors.HEADER}{'=' * 60}{Colors.END}")

    async def browse_resources(self):
        """Browse available resources with pagination"""
        while True:
            print(f"\n{Colors.CYAN}Resource Browser{Colors.END}")
            print("1. List All Resources")
            print("2. Browse Books")
            print("3. View Specific Book")
            print("4. Browse Patrons")
            print("5. View Library Stats")
            print("0. Back to Main Menu")

            choice = input("\nSelect option: ").strip()

            if choice == "0":
                break
            if choice == "1":
                await self._list_all_resources()
            elif choice == "2":
                await self._browse_books()
            elif choice == "3":
                await self._view_book()
            elif choice == "4":
                await self._browse_patrons()
            elif choice == "5":
                await self._view_stats()

    async def _list_all_resources(self):
        """List all available resources"""
        try:
            resources = await self.client.list_resources()
            print(f"\n{Colors.GREEN}Available Resources:{Colors.END}")
            for resource in resources:
                print(f"\n  {Colors.BOLD}{resource.name}{Colors.END}")
                print(f"    URI: {resource.uri}")
                if resource.description:
                    print(f"    Description: {resource.description}")
                if resource.mimeType:
                    print(f"    Type: {resource.mimeType}")
        except Exception as e:
            print(f"{Colors.RED}Error listing resources: {e}{Colors.END}")

    async def _browse_books(self):
        """Browse books with pagination"""
        try:
            print(f"\n{Colors.YELLOW}Fetching book catalog...{Colors.END}")
            content = await self.client.read_resource("library://books/list")

            if content and content[0].text:
                books = json.loads(content[0].text)

                print(f"\n{Colors.GREEN}Found {len(books)} books:{Colors.END}")

                # Display first 10 books
                for i, book in enumerate(books[:10]):
                    print(f"\n{i + 1}. {Colors.BOLD}{book['title']}{Colors.END}")
                    print(f"   Author: {book['author']}")
                    print(f"   ISBN: {book['isbn']}")
                    print(f"   Status: {book['status']}")

                if len(books) > 10:
                    print(f"\n{Colors.YELLOW}(Showing first 10 of {len(books)} books){Colors.END}")

        except Exception as e:
            print(f"{Colors.RED}Error browsing books: {e}{Colors.END}")

    async def _view_book(self):
        """View details of a specific book"""
        isbn = input("Enter ISBN: ").strip()
        if not isbn:
            return

        try:
            uri = f"library://books/{isbn}"
            content = await self.client.read_resource(uri)

            if content and content[0].text:
                book = json.loads(content[0].text)
                print(f"\n{Colors.GREEN}Book Details:{Colors.END}")
                print(f"  Title: {Colors.BOLD}{book['title']}{Colors.END}")
                print(f"  Author: {book['author']}")
                print(f"  ISBN: {book['isbn']}")
                print(f"  Publisher: {book.get('publisher', 'N/A')}")
                print(f"  Year: {book.get('publication_year', 'N/A')}")
                print(f"  Genre: {book.get('genre', 'N/A')}")
                print(f"  Pages: {book.get('total_pages', 'N/A')}")
                print(f"  Status: {book['status']}")
                print(f"  Description: {book.get('description', 'No description available')}")
        except Exception as e:
            print(f"{Colors.RED}Error viewing book: {e}{Colors.END}")

    async def _browse_patrons(self):
        """Browse library patrons"""
        try:
            content = await self.client.read_resource("library://patrons/list")

            if content and content[0].text:
                patrons = json.loads(content[0].text)

                print(f"\n{Colors.GREEN}Library Patrons ({len(patrons)} total):{Colors.END}")

                for patron in patrons[:10]:
                    print(f"\n  {Colors.BOLD}{patron['name']}{Colors.END}")
                    print(f"    ID: {patron['id']}")
                    print(f"    Email: {patron['email']}")
                    print(f"    Type: {patron['membership_type']}")
                    print(f"    Joined: {patron['join_date']}")

        except Exception as e:
            print(f"{Colors.RED}Error browsing patrons: {e}{Colors.END}")

    async def _view_stats(self):
        """View library statistics"""
        try:
            content = await self.client.read_resource("library://stats/overview")

            if content and content[0].text:
                stats = json.loads(content[0].text)

                print(f"\n{Colors.GREEN}Library Statistics:{Colors.END}")
                print(f"\n{Colors.CYAN}Collection:{Colors.END}")
                print(f"  Total Books: {stats['total_books']}")
                print(f"  Available: {stats['available_books']}")
                print(f"  Checked Out: {stats['checked_out_books']}")
                print(f"  Genres: {stats['total_genres']}")

                print(f"\n{Colors.CYAN}Members:{Colors.END}")
                print(f"  Total Patrons: {stats['total_patrons']}")
                print(f"  Active Members: {stats['active_patrons']}")

                print(f"\n{Colors.CYAN}Activity:{Colors.END}")
                print(f"  Checkouts This Month: {stats['checkouts_this_month']}")
                print(f"  Returns This Month: {stats['returns_this_month']}")

                if "popular_genres" in stats:
                    print(f"\n{Colors.CYAN}Popular Genres:{Colors.END}")
                    for genre, count in stats["popular_genres"].items():
                        print(f"  {genre}: {count} books")

        except Exception as e:
            print(f"{Colors.RED}Error viewing stats: {e}{Colors.END}")

    async def search_catalog(self):
        """Search and catalog operations"""
        while True:
            print(f"\n{Colors.CYAN}Search & Catalog Operations{Colors.END}")
            print("1. Search Books")
            print("2. Search Authors")
            print("3. Browse by Genre")
            print("4. Update Book Information")
            print("5. Archive Old Books")
            print("0. Back to Main Menu")

            choice = input("\nSelect option: ").strip()

            if choice == "0":
                break
            if choice == "1":
                await self._search_books()
            elif choice == "2":
                await self._search_authors()
            elif choice == "3":
                await self._browse_by_genre()
            elif choice == "4":
                await self._update_book()
            elif choice == "5":
                await self._archive_books()

    async def _search_books(self):
        """Search for books using the search tool"""
        query = input("Enter search query: ").strip()
        if not query:
            return

        try:
            print(f"\n{Colors.YELLOW}Searching for '{query}'...{Colors.END}")

            result = await self.client.call_tool(
                "search_books", {"query": query, "search_type": "all"}
            )

            if result.data:
                books = result.data
                print(f"\n{Colors.GREEN}Found {len(books)} matching books:{Colors.END}")

                for book in books[:10]:
                    print(f"\n  {Colors.BOLD}{book['title']}{Colors.END}")
                    print(f"    Author: {book['author']}")
                    print(f"    ISBN: {book['isbn']}")
                    print(f"    Match: {book.get('relevance_score', 'N/A')}")
            else:
                print(f"{Colors.YELLOW}No books found matching '{query}'{Colors.END}")

        except Exception as e:
            print(f"{Colors.RED}Error searching books: {e}{Colors.END}")

    async def _search_authors(self):
        """Search for authors"""
        query = input("Enter author name: ").strip()
        if not query:
            return

        try:
            result = await self.client.call_tool("search_authors", {"query": query})

            if result.data:
                authors = result.data
                print(f"\n{Colors.GREEN}Found {len(authors)} matching authors:{Colors.END}")

                for author in authors:
                    print(f"\n  {Colors.BOLD}{author['name']}{Colors.END}")
                    print(f"    ID: {author['id']}")
                    print(f"    Books: {author.get('book_count', 0)}")
                    if author.get("biography"):
                        print(f"    Bio: {author['biography'][:100]}...")
            else:
                print(f"{Colors.YELLOW}No authors found{Colors.END}")

        except Exception as e:
            print(f"{Colors.RED}Error searching authors: {e}{Colors.END}")

    async def _browse_by_genre(self):
        """Browse books by genre"""
        genre = input("Enter genre (e.g., Fiction, Science, History): ").strip()
        if not genre:
            return

        try:
            uri = f"library://books/by-genre/{genre}"
            content = await self.client.read_resource(uri)

            if content and content[0].text:
                books = json.loads(content[0].text)
                print(f"\n{Colors.GREEN}Books in {genre} ({len(books)} total):{Colors.END}")

                for book in books[:10]:
                    print(f"\n  {Colors.BOLD}{book['title']}{Colors.END}")
                    print(f"    Author: {book['author']}")
                    print(f"    Year: {book.get('publication_year', 'N/A')}")

        except Exception as e:
            print(f"{Colors.RED}Error browsing genre: {e}{Colors.END}")

    async def _update_book(self):
        """Update book information"""
        isbn = input("Enter ISBN of book to update: ").strip()
        if not isbn:
            return

        print("\nWhat would you like to update?")
        print("1. Description")
        print("2. Genre")
        print("3. Publisher")

        field_choice = input("Select field: ").strip()

        field_map = {"1": "description", "2": "genre", "3": "publisher"}

        field = field_map.get(field_choice)
        if not field:
            print(f"{Colors.RED}Invalid selection{Colors.END}")
            return

        new_value = input(f"Enter new {field}: ").strip()
        if not new_value:
            return

        try:
            result = await self.client.call_tool(
                "update_book", {"isbn": isbn, "updates": {field: new_value}}
            )

            print(f"\n{Colors.GREEN}Book updated successfully!{Colors.END}")
            if result.data:
                print(f"Updated book: {result.data.get('title', 'Unknown')}")

        except Exception as e:
            print(f"{Colors.RED}Error updating book: {e}{Colors.END}")

    async def _archive_books(self):
        """Archive old books"""
        year = input("Archive books published before year: ").strip()

        try:
            year = int(year)

            print(f"\n{Colors.YELLOW}Searching for books to archive...{Colors.END}")

            result = await self.client.call_tool(
                "archive_old_books", {"before_year": year, "dry_run": True}
            )

            if result.data:
                count = result.data.get("count", 0)
                if count > 0:
                    print(f"\n{Colors.YELLOW}Found {count} books to archive{Colors.END}")

                    confirm = input("Proceed with archiving? (y/n): ").strip().lower()
                    if confirm == "y":
                        result = await self.client.call_tool(
                            "archive_old_books", {"before_year": year, "dry_run": False}
                        )
                        print(f"{Colors.GREEN}Archived {count} books{Colors.END}")
                else:
                    print(f"{Colors.YELLOW}No books found to archive{Colors.END}")

        except ValueError:
            print(f"{Colors.RED}Invalid year{Colors.END}")
        except Exception as e:
            print(f"{Colors.RED}Error archiving books: {e}{Colors.END}")

    async def circulation_operations(self):
        """Handle circulation operations"""
        while True:
            print(f"\n{Colors.CYAN}Circulation Operations{Colors.END}")
            print("1. Check Out Book")
            print("2. Return Book")
            print("3. Reserve Book")
            print("4. View Patron History")
            print("5. Check Book Availability")
            print("0. Back to Main Menu")

            choice = input("\nSelect option: ").strip()

            if choice == "0":
                break
            if choice == "1":
                await self._checkout_book()
            elif choice == "2":
                await self._return_book()
            elif choice == "3":
                await self._reserve_book()
            elif choice == "4":
                await self._view_patron_history()
            elif choice == "5":
                await self._check_availability()

    async def _checkout_book(self):
        """Check out a book"""
        patron_id = input("Enter patron ID: ").strip()
        isbn = input("Enter book ISBN: ").strip()

        if not patron_id or not isbn:
            return

        try:
            print(f"\n{Colors.YELLOW}Processing checkout...{Colors.END}")

            result = await self.client.call_tool(
                "checkout_book", {"patron_id": patron_id, "isbn": isbn}
            )

            if result.data:
                checkout = result.data
                print(f"\n{Colors.GREEN}✓ Book checked out successfully!{Colors.END}")
                print(f"  Checkout ID: {checkout.get('id', 'N/A')}")
                print(f"  Due Date: {checkout.get('due_date', 'N/A')}")

        except McpError as e:
            if "already checked out" in str(e).lower():
                print(f"{Colors.YELLOW}Book is already checked out{Colors.END}")
            elif "not found" in str(e).lower():
                print(f"{Colors.RED}Book or patron not found{Colors.END}")
            else:
                print(f"{Colors.RED}Checkout failed: {e}{Colors.END}")
        except Exception as e:
            print(f"{Colors.RED}Error during checkout: {e}{Colors.END}")

    async def _return_book(self):
        """Return a book"""
        patron_id = input("Enter patron ID: ").strip()
        isbn = input("Enter book ISBN: ").strip()

        if not patron_id or not isbn:
            return

        try:
            result = await self.client.call_tool(
                "return_book", {"patron_id": patron_id, "isbn": isbn}
            )

            print(f"\n{Colors.GREEN}✓ Book returned successfully!{Colors.END}")

            if result.data and result.data.get("late_fee"):
                print(f"{Colors.YELLOW}Late fee: ${result.data['late_fee']:.2f}{Colors.END}")

        except Exception as e:
            print(f"{Colors.RED}Error returning book: {e}{Colors.END}")

    async def _reserve_book(self):
        """Reserve a book"""
        patron_id = input("Enter patron ID: ").strip()
        isbn = input("Enter book ISBN: ").strip()

        if not patron_id or not isbn:
            return

        try:
            result = await self.client.call_tool(
                "reserve_book", {"patron_id": patron_id, "isbn": isbn}
            )

            if result.data:
                reservation = result.data
                print(f"\n{Colors.GREEN}✓ Book reserved successfully!{Colors.END}")
                print(f"  Reservation ID: {reservation.get('id', 'N/A')}")
                print(f"  Queue Position: {reservation.get('queue_position', 'N/A')}")

        except Exception as e:
            print(f"{Colors.RED}Error reserving book: {e}{Colors.END}")

    async def _view_patron_history(self):
        """View patron borrowing history"""
        patron_id = input("Enter patron ID: ").strip()
        if not patron_id:
            return

        try:
            uri = f"library://patrons/{patron_id}/history"
            content = await self.client.read_resource(uri)

            if content and content[0].text:
                history = json.loads(content[0].text)

                print(f"\n{Colors.GREEN}Borrowing History:{Colors.END}")

                if history.get("current"):
                    print(f"\n{Colors.CYAN}Currently Borrowed:{Colors.END}")
                    for item in history["current"]:
                        print(f"  - {item['title']} (Due: {item['due_date']})")

                if history.get("past"):
                    print(f"\n{Colors.CYAN}Past Borrowings:{Colors.END}")
                    for item in history["past"][:5]:
                        print(f"  - {item['title']} (Returned: {item['return_date']})")

        except Exception as e:
            print(f"{Colors.RED}Error viewing history: {e}{Colors.END}")

    async def _check_availability(self):
        """Check book availability"""
        isbn = input("Enter book ISBN: ").strip()
        if not isbn:
            return

        try:
            result = await self.client.call_tool("check_availability", {"isbn": isbn})

            if result.data:
                status = result.data
                print(f"\n{Colors.GREEN}Book Status:{Colors.END}")
                print(
                    f"  Available: {Colors.GREEN if status['available'] else Colors.RED}{status['available']}{Colors.END}"
                )

                if not status["available"] and status.get("due_date"):
                    print(f"  Expected Return: {status['due_date']}")
                if status.get("reserve_count"):
                    print(f"  Reservations: {status['reserve_count']}")

        except Exception as e:
            print(f"{Colors.RED}Error checking availability: {e}{Colors.END}")

    async def ai_features(self):
        """AI-powered features"""
        while True:
            print(f"\n{Colors.CYAN}AI Features{Colors.END}")
            print("1. Get Book Recommendations")
            print("2. Generate Reading Plan")
            print("3. Generate Book Review")
            print("4. Find Similar Books")
            print("0. Back to Main Menu")

            choice = input("\nSelect option: ").strip()

            if choice == "0":
                break
            if choice == "1":
                await self._get_recommendations()
            elif choice == "2":
                await self._generate_reading_plan()
            elif choice == "3":
                await self._generate_review()
            elif choice == "4":
                await self._find_similar_books()

    async def _get_recommendations(self):
        """Get book recommendations using prompts"""
        print("\nProvide preferences for recommendations:")
        genres = input("Preferred genres (comma-separated): ").strip()
        topics = input("Topics of interest: ").strip()

        try:
            print(f"\n{Colors.YELLOW}Generating recommendations...{Colors.END}")

            # Get prompt template
            messages = await self.client.get_prompt(
                "book_recommendations",
                {
                    "genres": genres or "any",
                    "preferences": topics or "general interest",
                    "count": 5,
                },
            )

            print(f"\n{Colors.GREEN}Recommendation Prompt Generated:{Colors.END}")
            print(f"\n{Colors.CYAN}System Message:{Colors.END}")
            if messages.messages:
                for msg in messages.messages:
                    print(f"  {msg.content}")

            # In a real implementation, this would be sent to an LLM
            print(
                f"\n{Colors.YELLOW}(In production, this prompt would be sent to an LLM for recommendations){Colors.END}"
            )

        except Exception as e:
            print(f"{Colors.RED}Error getting recommendations: {e}{Colors.END}")

    async def _generate_reading_plan(self):
        """Generate a personalized reading plan"""
        goal = input("What's your reading goal? ").strip()
        timeframe = input("Timeframe (e.g., '3 months'): ").strip()
        level = input("Reading level (beginner/intermediate/advanced): ").strip()

        try:
            messages = await self.client.get_prompt(
                "reading_plan",
                {
                    "goal": goal or "improve general knowledge",
                    "timeframe": timeframe or "6 months",
                    "reading_level": level or "intermediate",
                    "preferences": "varied genres",
                },
            )

            print(f"\n{Colors.GREEN}Reading Plan Template Generated:{Colors.END}")
            for msg in messages.messages:
                print(f"\n{Colors.CYAN}Role: {msg.role}{Colors.END}")
                print(f"Content: {msg.content}")

        except Exception as e:
            print(f"{Colors.RED}Error generating reading plan: {e}{Colors.END}")

    async def _generate_review(self):
        """Generate a book review"""
        isbn = input("Enter book ISBN: ").strip()
        if not isbn:
            return

        try:
            # First get the book details
            uri = f"library://books/{isbn}"
            content = await self.client.read_resource(uri)

            if content and content[0].text:
                book = json.loads(content[0].text)

                # Get review prompt
                messages = await self.client.get_prompt(
                    "book_review",
                    {
                        "title": book["title"],
                        "author": book["author"],
                        "genre": book.get("genre", "Unknown"),
                        "description": book.get("description", "No description available"),
                    },
                )

                print(f"\n{Colors.GREEN}Review Prompt for '{book['title']}':{Colors.END}")
                for msg in messages.messages:
                    print(f"\n{msg.content}")

        except Exception as e:
            print(f"{Colors.RED}Error generating review: {e}{Colors.END}")

    async def _find_similar_books(self):
        """Find books similar to a given book"""
        isbn = input("Enter book ISBN: ").strip()
        if not isbn:
            return

        try:
            result = await self.client.call_tool("find_similar_books", {"isbn": isbn, "limit": 5})

            if result.data:
                similar = result.data
                print(f"\n{Colors.GREEN}Similar Books:{Colors.END}")

                for book in similar:
                    print(f"\n  {Colors.BOLD}{book['title']}{Colors.END}")
                    print(f"    Author: {book['author']}")
                    print(f"    Similarity: {book.get('similarity_score', 'N/A')}")
                    print(f"    Reason: {book.get('reason', 'Similar genre/topic')}")

        except Exception as e:
            print(f"{Colors.RED}Error finding similar books: {e}{Colors.END}")

    async def bulk_operations(self):
        """Demonstrate bulk operations with progress tracking"""
        while True:
            print(f"\n{Colors.CYAN}Bulk Operations{Colors.END}")
            print("1. Import Books from CSV")
            print("2. Import Books from JSON")
            print("3. Bulk Update Genres")
            print("4. Export Catalog")
            print("0. Back to Main Menu")

            choice = input("\nSelect option: ").strip()

            if choice == "0":
                break
            if choice == "1":
                await self._import_csv()
            elif choice == "2":
                await self._import_json()
            elif choice == "3":
                await self._bulk_update_genres()
            elif choice == "4":
                await self._export_catalog()

    async def _import_csv(self):
        """Import books from CSV file"""
        # Use sample file if it exists
        sample_csv = Path("../data/samples/books_sample.csv")

        if sample_csv.exists():
            use_sample = input(f"Use sample file ({sample_csv.name})? (y/n): ").strip().lower()
            if use_sample == "y":
                file_path = str(sample_csv)
            else:
                file_path = input("Enter CSV file path: ").strip()
        else:
            file_path = input("Enter CSV file path: ").strip()

        if not file_path or not Path(file_path).exists():
            print(f"{Colors.RED}File not found{Colors.END}")
            return

        try:
            print(f"\n{Colors.YELLOW}Starting CSV import...{Colors.END}")

            result = await self.client.call_tool(
                "import_books_csv",
                {"file_path": file_path, "validate_only": False},
                progress_handler=self.progress_handler,
            )

            print(f"\n\n{Colors.GREEN}Import completed!{Colors.END}")
            if result.data:
                stats = result.data
                print(f"  Processed: {stats.get('processed', 0)} books")
                print(f"  Imported: {stats.get('imported', 0)} books")
                print(f"  Errors: {stats.get('errors', 0)}")

        except Exception as e:
            print(f"\n{Colors.RED}Error during import: {e}{Colors.END}")

    async def _import_json(self):
        """Import books from JSON file"""
        sample_json = Path("../data/samples/books_sample.json")

        if sample_json.exists():
            use_sample = input(f"Use sample file ({sample_json.name})? (y/n): ").strip().lower()
            if use_sample == "y":
                file_path = str(sample_json)
            else:
                file_path = input("Enter JSON file path: ").strip()
        else:
            file_path = input("Enter JSON file path: ").strip()

        if not file_path or not Path(file_path).exists():
            print(f"{Colors.RED}File not found{Colors.END}")
            return

        try:
            print(f"\n{Colors.YELLOW}Starting JSON import...{Colors.END}")

            result = await self.client.call_tool(
                "import_books_json",
                {"file_path": file_path},
                progress_handler=self.progress_handler,
            )

            print(f"\n\n{Colors.GREEN}Import completed!{Colors.END}")
            if result.data:
                print(f"  Imported: {result.data.get('imported', 0)} books")

        except Exception as e:
            print(f"\n{Colors.RED}Error during import: {e}{Colors.END}")

    async def _bulk_update_genres(self):
        """Bulk update book genres"""
        old_genre = input("Current genre to update: ").strip()
        new_genre = input("New genre name: ").strip()

        if not old_genre or not new_genre:
            return

        try:
            result = await self.client.call_tool(
                "bulk_update_genre", {"old_genre": old_genre, "new_genre": new_genre}
            )

            if result.data:
                count = result.data.get("updated", 0)
                print(
                    f"\n{Colors.GREEN}Updated {count} books from '{old_genre}' to '{new_genre}'{Colors.END}"
                )

        except Exception as e:
            print(f"{Colors.RED}Error updating genres: {e}{Colors.END}")

    async def _export_catalog(self):
        """Export library catalog"""
        format_type = input("Export format (csv/json): ").strip().lower()

        if format_type not in ["csv", "json"]:
            print(f"{Colors.RED}Invalid format{Colors.END}")
            return

        try:
            print(f"\n{Colors.YELLOW}Exporting catalog...{Colors.END}")

            result = await self.client.call_tool(
                "export_catalog", {"format": format_type, "include_metadata": True}
            )

            if result.data:
                file_path = result.data.get("file_path")
                count = result.data.get("count", 0)
                print(f"\n{Colors.GREEN}Exported {count} books to:{Colors.END}")
                print(f"  {file_path}")

        except Exception as e:
            print(f"{Colors.RED}Error exporting catalog: {e}{Colors.END}")

    async def list_operations(self):
        """List all available operations"""
        try:
            # List tools
            tools = await self.client.list_tools()
            print(f"\n{Colors.GREEN}Available Tools ({len(tools)}):{Colors.END}")

            for tool in sorted(tools, key=lambda t: t.name):
                print(f"\n  {Colors.BOLD}{tool.name}{Colors.END}")
                if tool.description:
                    print(f"    {tool.description}")
                if tool.inputSchema and tool.inputSchema.properties:
                    print(f"    Parameters: {', '.join(tool.inputSchema.properties.keys())}")

            # List resources
            resources = await self.client.list_resources()
            print(f"\n\n{Colors.GREEN}Available Resources ({len(resources)}):{Colors.END}")

            for resource in sorted(resources, key=lambda r: r.name):
                print(f"\n  {Colors.BOLD}{resource.name}{Colors.END}")
                print(f"    URI: {resource.uri}")

            # List prompts
            prompts = await self.client.list_prompts()
            print(f"\n\n{Colors.GREEN}Available Prompts ({len(prompts)}):{Colors.END}")

            for prompt in sorted(prompts, key=lambda p: p.name):
                print(f"\n  {Colors.BOLD}{prompt.name}{Colors.END}")
                if prompt.description:
                    print(f"    {prompt.description}")

        except Exception as e:
            print(f"{Colors.RED}Error listing operations: {e}{Colors.END}")

    async def test_error_handling(self):
        """Test various error scenarios"""
        print(f"\n{Colors.CYAN}Error Handling Tests{Colors.END}")
        print("1. Test Invalid ISBN")
        print("2. Test Duplicate Checkout")
        print("3. Test Missing Resource")
        print("4. Test Invalid Tool Parameters")
        print("0. Back to Main Menu")

        choice = input("\nSelect test: ").strip()

        if choice == "1":
            await self._test_invalid_isbn()
        elif choice == "2":
            await self._test_duplicate_checkout()
        elif choice == "3":
            await self._test_missing_resource()
        elif choice == "4":
            await self._test_invalid_params()

    async def _test_invalid_isbn(self):
        """Test handling of invalid ISBN"""
        try:
            print(f"\n{Colors.YELLOW}Testing invalid ISBN...{Colors.END}")
            await self.client.read_resource("library://books/INVALID-ISBN")
        except McpError as e:
            print(f"{Colors.GREEN}✓ Error correctly caught: {e}{Colors.END}")
        except Exception as e:
            print(f"{Colors.RED}Unexpected error: {e}{Colors.END}")

    async def _test_duplicate_checkout(self):
        """Test duplicate checkout attempt"""
        try:
            print(f"\n{Colors.YELLOW}Testing duplicate checkout...{Colors.END}")
            # First checkout
            await self.client.call_tool(
                "checkout_book", {"patron_id": "PAT001", "isbn": "9780140449136"}
            )

            # Attempt duplicate
            await self.client.call_tool(
                "checkout_book", {"patron_id": "PAT002", "isbn": "9780140449136"}
            )

        except McpError as e:
            print(f"{Colors.GREEN}✓ Error correctly caught: {e}{Colors.END}")
        except Exception as e:
            print(f"{Colors.RED}Unexpected error: {e}{Colors.END}")

    async def _test_missing_resource(self):
        """Test accessing non-existent resource"""
        try:
            print(f"\n{Colors.YELLOW}Testing missing resource...{Colors.END}")
            await self.client.read_resource("library://nonexistent/resource")
        except McpError as e:
            print(f"{Colors.GREEN}✓ Error correctly caught: {e}{Colors.END}")
        except Exception as e:
            print(f"{Colors.RED}Unexpected error: {e}{Colors.END}")

    async def _test_invalid_params(self):
        """Test tool with invalid parameters"""
        try:
            print(f"\n{Colors.YELLOW}Testing invalid parameters...{Colors.END}")
            await self.client.call_tool("checkout_book", {"invalid": "params"})
        except McpError as e:
            print(f"{Colors.GREEN}✓ Error correctly caught: {e}{Colors.END}")
        except Exception as e:
            print(f"{Colors.RED}Unexpected error: {e}{Colors.END}")

    async def run(self):
        """Main event loop"""
        try:
            await self.connect()

            print(f"\n{Colors.GREEN}Welcome to the Virtual Library MCP Test Client!{Colors.END}")
            print("This client demonstrates all features of the Virtual Library MCP Server")
            print("and serves as an educational example for MCP development.")

            while self.running:
                self.print_menu()
                choice = input("\nSelect option: ").strip()

                if choice == "0":
                    self.running = False
                elif choice == "1":
                    await self.browse_resources()
                elif choice == "2":
                    await self.search_catalog()
                elif choice == "3":
                    await self.circulation_operations()
                elif choice == "4":
                    await self.ai_features()
                elif choice == "5":
                    await self.bulk_operations()
                elif choice == "6":
                    await self.list_operations()
                elif choice == "7":
                    await self.test_error_handling()
                else:
                    print(f"{Colors.RED}Invalid option{Colors.END}")

        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}Interrupted by user{Colors.END}")
        except Exception as e:
            print(f"{Colors.RED}Fatal error: {e}{Colors.END}")
            raise
        finally:
            await self.disconnect()


async def main():
    """Entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Virtual Library MCP Test Client - Comprehensive testing and demonstration"
    )
    parser.add_argument(
        "--server",
        type=str,
        default="../server.py",
        help="Path to the MCP server script (default: ../server.py)",
    )

    args = parser.parse_args()

    print(f"{Colors.HEADER}{'=' * 60}{Colors.END}")
    print(f"{Colors.BOLD}Virtual Library MCP Test Client{Colors.END}")
    print(f"{Colors.HEADER}{'=' * 60}{Colors.END}")

    client = VirtualLibraryClient(args.server)
    await client.run()


if __name__ == "__main__":
    asyncio.run(main())
