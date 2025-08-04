# Virtual Library MCP Scripts

This directory contains utility scripts for the Virtual Library MCP Server.

## test_client.py

A comprehensive Python client that demonstrates all features of the Virtual Library MCP Server through an interactive CLI interface. This client serves as both a testing tool and an educational example for developers learning the Model Context Protocol.

### Features Demonstrated

- **Resources**: Browse books, patrons, and library statistics with pagination
- **Tools**: Search catalog, manage circulation, update book information
- **Prompts**: Generate AI-powered recommendations, reading plans, and reviews
- **Progress Tracking**: Monitor long-running operations like bulk imports
- **Error Handling**: Graceful handling of various error scenarios
- **Multi-server Support**: Example of connecting to MCP servers

### Prerequisites

- Python 3.12+
- FastMCP installed (`pip install fastmcp`)
- Virtual Library MCP Server running or accessible

### Usage

#### Basic Usage

```bash
# From the scripts directory
./test_client.py

# Or using Python directly
python test_client.py

# Specify a different server path
python test_client.py --server /path/to/server.py
```

#### Main Menu Options

1. **Browse Resources** - Explore books, patrons, and library statistics
2. **Search & Catalog** - Search books/authors, browse by genre, update information
3. **Circulation** - Check out, return, and reserve books
4. **AI Features** - Get recommendations, generate reading plans and reviews
5. **Bulk Operations** - Import books from CSV/JSON with progress tracking
6. **List Operations** - View all available tools, resources, and prompts
7. **Test Error Handling** - Demonstrate proper error handling

### Example Workflows

#### 1. Searching for Books

```
Main Menu > 2 (Search & Catalog) > 1 (Search Books)
Enter search query: "philosophy"
```

The client will search for books containing "philosophy" and display results with relevance scores.

#### 2. Checking Out a Book

```
Main Menu > 3 (Circulation) > 1 (Check Out Book)
Enter patron ID: PAT001
Enter book ISBN: 9780140449136
```

The client will process the checkout and display the due date.

#### 3. Getting Book Recommendations

```
Main Menu > 4 (AI Features) > 1 (Get Recommendations)
Preferred genres: Science Fiction, Philosophy
Topics of interest: artificial intelligence, ethics
```

The client will generate a prompt template that would be sent to an LLM for personalized recommendations.

#### 4. Bulk Import with Progress

```
Main Menu > 5 (Bulk Operations) > 1 (Import from CSV)
Use sample file? y
```

The client will import books showing a real-time progress bar.

### Error Handling Examples

The client demonstrates proper error handling for common scenarios:

- Invalid ISBN or patron ID
- Attempting to check out an already borrowed book
- Missing resources or tools
- Network connection issues
- Invalid parameters

### Development Tips

1. **Testing New Features**: Use the client to test new server features before integration
2. **Debugging**: The client shows detailed error messages to help debug server issues
3. **Learning MCP**: Study the client code to understand MCP client implementation patterns
4. **Extending**: Add new menu options to test custom server features

### Color Output

The client uses ANSI color codes for better readability:
- 🟢 Green: Success messages
- 🟡 Yellow: Warnings and progress
- 🔴 Red: Errors
- 🔵 Blue/Cyan: Information and headers

### Architecture

The client is structured with:

- `VirtualLibraryClient` class: Main client logic and menu system
- Category-specific methods: Organized by feature area
- Error handling: Try-catch blocks with specific error types
- Progress handler: Async callback for long operations
- Color support: ANSI codes for terminal output

### Connection Management

The client uses FastMCP's context manager for automatic connection handling:

```python
async with client:
    # Server connection is active here
    result = await client.call_tool("tool_name", params)
```

### Adding New Features

To add support for new server features:

1. Add a new menu option in the appropriate category
2. Create a method to handle the feature
3. Use appropriate client methods (`call_tool`, `read_resource`, `get_prompt`)
4. Add error handling for edge cases
5. Include helpful output with colors

## init_database.py

Initializes the Virtual Library database with sample data. This script is typically run during server setup to populate the database with books, authors, and patrons.

### Usage

```bash
python init_database.py
```

This will create or reset the database with a comprehensive set of sample data for testing.