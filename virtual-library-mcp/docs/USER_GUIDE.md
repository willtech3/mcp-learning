# Virtual Library MCP Server - Complete User Guide

## Table of Contents
1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Running the Server](#running-the-server)
5. [VS Code Integration](#vs-code-integration)
6. [Testing MCP Features](#testing-mcp-features)
7. [Troubleshooting](#troubleshooting)
8. [Quick Reference](#quick-reference)

---

## Overview

The Virtual Library MCP Server is an educational implementation of the Model Context Protocol that simulates a complete library management system. It demonstrates all core MCP concepts through practical features including resources, tools, prompts, and sampling capabilities.

### What You Can Do
- Browse a catalog of 1000+ books
- Search and filter books by various criteria
- Manage library patrons and circulation
- Generate AI-powered book insights and recommendations
- Track checkout/return operations
- Bulk import book catalogs
- Perform catalog maintenance

---

## Prerequisites

Before starting, ensure you have:

1. **Python 3.12 or higher** installed
   ```bash
   python --version  # Should show 3.12.x or higher
   ```

2. **uv package manager** installed
   ```bash
   # Install uv if not present
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. **VS Code** with Claude Desktop extension (optional but recommended)
   - Install VS Code from https://code.visualstudio.com/
   - Install Claude Desktop extension from VS Code marketplace

4. **Git** for cloning the repository
   ```bash
   git --version  # Verify git is installed
   ```

---

## Installation

### Step 1: Clone the Repository
```bash
git clone https://github.com/willtech3/mcp-learning.git
cd mcp-learning/virtual-library-mcp
```

### Step 2: Set Up Python Environment
```bash
# Create and activate virtual environment using uv
uv venv
source .venv/bin/activate  # On macOS/Linux
# or
.venv\Scripts\activate  # On Windows
```

### Step 3: Install Dependencies
```bash
# Using just (recommended)
just install

# Or manually with uv
uv pip install -e .
```

### Step 4: Initialize the Database
```bash
# Initialize with sample data
just init-db

# Or run the script directly
python scripts/init_database.py
```

This creates a SQLite database at `data/library.db` with:
- 1000+ books across various genres
- 50+ authors
- 100+ library patrons
- Sample circulation records

### Step 5: Verify Installation
```bash
# Run tests to ensure everything is working
just test

# Check the server can start
just dev
# Press Ctrl+C to stop
```

---

## Running the Server

### Method 1: Using Just (Recommended)
```bash
# Start the development server
just dev

# The server will start and display:
# MCP Server running on stdio
# Transport: stdio
# Use Ctrl+C to stop
```

### Method 2: Direct Python Execution
```bash
# Ensure virtual environment is activated
source .venv/bin/activate

# Run the server
python -m virtual-library-mcp.server
```

### Method 3: Using uv run
```bash
uv run mcp-dev virtual-library-mcp.server
```

### Server Configuration

The server uses environment variables for configuration. Create a `.env` file:

```bash
cp .env.sample .env
```

Edit `.env` to customize:
```env
# Server Configuration
MCP_SERVER_NAME="virtual-library"
MCP_SERVER_VERSION="0.3.0"

# Transport (stdio or sse)
MCP_TRANSPORT="stdio"

# Database
MCP_DATABASE_PATH="data/library.db"

# Logging
MCP_LOG_LEVEL="INFO"
MCP_LOG_TO_FILE="true"
MCP_LOG_FILE_PATH="logs/server.log"

# Features
MCP_ENABLE_SAMPLING="true"
MCP_ENABLE_SUBSCRIPTIONS="true"
```

---

## MCP Client Options

### MCP Client Support Status (August 2025)

| Client | Type | MCP Support | Sampling Support | Notes |
|--------|------|------------|------------------|-------|
| **VS Code + GitHub Copilot** | VS Code Extension | ✅ Full | ✅ Yes | Full MCP spec support including sampling (GA as of VS Code 1.102, June 2025) |
| **Cline** | VS Code Extension | ✅ Full | ✅ Likely | Autonomous coding agent with MCP support |
| **Continue** | VS Code Extension | ✅ Full | ✅ Likely | Open-source with MCP connectivity |
| **Claude Desktop** | Standalone App | ✅ Partial | ❌ No | MCP connections work but no sampling support |
| **Claude Code** | Standalone App | ✅ Partial | ❌ No | MCP connections work but no sampling support (Feature request #1785 open) |
| **Windsurf** | Standalone IDE | ✅ Full | ✅ Likely | Full MCP implementation, popular AI code editor |
| **Cursor** | Standalone IDE | ✅ Full | ✅ Likely | Integrated MCP support |

**Important**: Sampling support allows MCP servers to request AI completions through the client. Without it, servers must make direct API calls, incurring additional costs.

---

## VS Code Integration

### Option 1: VS Code with GitHub Copilot (Recommended - Full Sampling Support)

1. **Install GitHub Copilot Extension**
   - Open VS Code
   - Go to Extensions (Cmd+Shift+X on macOS, Ctrl+Shift+X on Windows/Linux)
   - Search for "GitHub Copilot Chat"
   - Install the official extension
   - Sign in with your GitHub account

2. **Configure MCP Server**
   - VS Code 1.102+ has MCP support generally available
   - Use Command Palette: `MCP: List Servers` to add your server
   - Configure the server path to point to your virtual-library-mcp directory

3. **Enable Sampling**
   - First sampling request will prompt for authorization
   - Use `MCP: List Servers > Configure Model Access` to set allowed models
   - View request logs in the MCP server list

### Option 2: Cline Extension (Autonomous Agent)

1. **Install Cline**
   - Search for "Cline" in VS Code Extensions marketplace
   - Install and configure with your API keys
   - Cline can create and manage MCP servers autonomously

2. **Connect to Virtual Library**
   - Cline will auto-discover MCP servers in your workspace
   - Or manually add via Cline's configuration

### Option 3: Continue Extension (Open Source)

1. **Install Continue**
   - Search for "Continue" in VS Code Extensions marketplace
   - Configure with your preferred AI model provider
   - Supports local models and cloud providers

---

## Standalone Client Setup

### Claude Desktop (Limited - No Sampling Support)

**Note**: Claude Desktop doesn't support sampling, so AI features will use fallback responses.

1. **Download Claude Desktop**
   - Get it from https://claude.ai/download
   - Install and sign in with your Anthropic account

2. **Configure MCP Connection**
   
   Create or edit `~/.claude/claude_desktop_config.json`:

   ```json
   {
     "mcpServers": {
       "virtual-library": {
         "command": "uv",
         "args": [
           "--directory",
           "/absolute/path/to/virtual-library-mcp",
           "run",
           "mcp-dev",
           "virtual-library-mcp.server"
         ],
         "env": {
           "MCP_SERVER_NAME": "virtual-library",
           "MCP_LOG_LEVEL": "INFO"
         }
       }
     }
   }
   ```

   **Important**: Replace `/absolute/path/to/virtual-library-mcp` with your actual path.

3. **Restart Claude Desktop**
   - Quit Claude Desktop completely
   - Restart the application
   - The Virtual Library server should appear in the MCP servers list

### Verifying Connection (Any Client)

Test with a simple command:
```
What books are available in the virtual library?
```

For sampling support test:
```
Generate an AI summary for book 9780134190440
```
- With sampling: Returns AI-generated content
- Without sampling: Returns book info with fallback message

---

## Testing MCP Features

### 1. Resources (Read-Only Data)

#### List All Books
```
Show me all books in the library catalog
```

The server will return paginated results with book details including:
- ISBN, title, author
- Genre, publication year
- Availability status
- Description

#### Get Specific Book Details
```
Get details for book with ISBN 9780134190440
```

Returns comprehensive book information including circulation statistics.

#### Browse by Author
```
Show me all books by author_id author_tolkien01
```

#### Browse by Genre
```
List all Science Fiction books
```

#### View Patron Information
```
Show patron details for patron_p_anderson_01
```

#### Library Statistics
```
Show me library statistics and metrics
```

### 2. Tools (Actions with Side Effects)

#### Search Catalog
```
Search for books with "programming" in the title
```

Advanced search with filters:
```
Search for available Science Fiction books by Asimov, sorted by year
```

#### Checkout Operations
```
Checkout book 9780134190440 to patron p_anderson_01
```

Custom due date:
```
Checkout book 9780134190440 to patron p_anderson_01 with due date 2024-12-31
```

#### Return Operations
```
Return checkout checkout_2024_0001
```

With condition notes:
```
Return checkout checkout_2024_0001 with condition "Minor wear on cover"
```

#### Reserve Books
```
Reserve book 9780134190440 for patron p_anderson_01
```

#### Book Insights (Using Sampling)
```
Generate a summary for book 9780134190440
```

Other insight types:
```
Generate themes analysis for book 9780134190440
Generate discussion questions for book 9780134190440
Find similar books to 9780134190440
```

#### Bulk Import
```
Import books from data/samples/books_sample.csv
```

With custom batch size:
```
Import books from data/samples/books_sample.json with batch size 50
```

#### Catalog Maintenance
```
Regenerate the library catalog with maintenance checks
```

### 3. Prompts (LLM Templates)

#### Book Recommendations
```
Get book recommendations for mystery lovers
```

With parameters:
```
Recommend 5 science fiction books for a teenage reader interested in space exploration
```

#### Reading Plans
```
Create a 3-month reading plan for classic literature
```

Advanced plan:
```
Create a 6-month advanced reading plan for someone interested in philosophy with 10 hours per week available
```

#### Review Generation
```
Generate a review for book 9780134190440
```

Different review types:
```
Generate a critical academic review for book 9780134190440
Generate a casual reader review for book 9780134190440 for young adults
```

### 4. Sampling Features (Client-Dependent)

Sampling allows the server to request AI-generated content from the client. Support varies by MCP client:

#### Testing with VS Code + GitHub Copilot (Full Support)
```
Generate an AI-powered summary for The Pragmatic Programmer (9780134190440)
```
- **Expected**: AI-generated summary with insights
- **First time**: You'll be prompted to authorize sampling
- **Configure models**: Use `MCP: List Servers > Configure Model Access`

#### Testing with Claude Desktop/Code (No Support)
```
Generate an AI-powered summary for The Pragmatic Programmer (9780134190440)
```
- **Expected**: Fallback to book information with note about sampling requirements
- **Workaround**: Server would need direct API keys (not implemented for security)

#### What Happens Behind the Scenes
1. Server checks if client supports `sampling` capability
2. If yes: Sends `sampling/createMessage` request to client
3. Client uses its AI model to generate response
4. If no: Returns graceful fallback with existing book data

#### Sampling-Enabled Features in This Server
- Book summaries (`generate_book_insights` with type "summary")
- Theme analysis (`generate_book_insights` with type "themes")
- Discussion questions (`generate_book_insights` with type "discussion_questions")
- Similar book recommendations (`generate_book_insights` with type "similar_books")
- All prompts features (recommendations, reading plans, reviews)

### 5. Advanced Queries

#### Complex Circulation Workflow
```
1. Search for available Python books
2. Checkout the first result to patron p_anderson_01
3. Generate a reading plan based on the checkout
4. Get AI insights about the book
```

#### Catalog Analysis
```
1. Show library statistics
2. List overdue books
3. Show most popular genres
4. Identify patrons with outstanding fines
```

---

## Troubleshooting

### Common Issues and Solutions

#### 1. Server Won't Start

**Issue**: `ModuleNotFoundError: No module named 'virtual_library_mcp'`

**Solution**:
```bash
# Ensure you're in the correct directory
cd virtual-library-mcp

# Reinstall in development mode
uv pip install -e .
```

#### 2. Database Errors

**Issue**: `sqlite3.OperationalError: no such table: books`

**Solution**:
```bash
# Reinitialize the database
just init-db

# Or manually
rm data/library.db
python scripts/init_database.py
```

#### 3. VS Code Connection Failed

**Issue**: Claude Desktop doesn't show the server

**Solution**:
1. Check the config file path is correct
2. Ensure absolute paths are used in configuration
3. Restart Claude Desktop completely
4. Check logs:
   ```bash
   tail -f logs/server.log
   ```

#### 4. Sampling Not Working

**Issue**: "AI-generated summaries require a client with sampling support"

**Solution**:
- **Claude Desktop/Code**: These clients don't support sampling as of August 2025. The fallback message is expected behavior.
- **VS Code + GitHub Copilot**: Ensure you're using VS Code 1.102+ with GitHub Copilot Chat extension
- **First-time setup**: Accept the sampling authorization prompt when it appears
- **Configuration**: Use `MCP: List Servers > Configure Model Access` in VS Code
- Check that `MCP_ENABLE_SAMPLING=true` in your `.env`
- **Alternative clients**: Try Windsurf, Cline, Continue, or Cursor for potential sampling support

#### 5. Import Errors with CSV/JSON

**Issue**: "Failed to parse CSV file" or "Invalid JSON format"

**Solution**:
- Check file format matches extension
- Ensure required columns are present:
  - CSV: isbn, title, author_name, genre, publication_year
  - JSON: Same fields in array of objects
- Verify file encoding is UTF-8

### Checking Logs

The server provides detailed logging:

```bash
# View real-time logs
tail -f logs/server.log

# Check for errors
grep ERROR logs/server.log

# See detailed debug information
MCP_LOG_LEVEL=DEBUG just dev
```

### Database Inspection

```bash
# Open SQLite database directly
sqlite3 data/library.db

# Useful queries
.tables                    # List all tables
SELECT COUNT(*) FROM books;  # Count books
SELECT * FROM books LIMIT 5; # Sample books
.quit                      # Exit
```

---

## Quick Reference

### Essential Commands

| Command | Description |
|---------|-------------|
| `just install` | Install all dependencies |
| `just dev` | Start development server |
| `just test` | Run test suite |
| `just lint` | Run code linting |
| `just format` | Format code |
| `just init-db` | Initialize database |
| `just clean` | Clean temporary files |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_SERVER_NAME` | "virtual-library" | Server identifier |
| `MCP_SERVER_VERSION` | "0.3.0" | Server version |
| `MCP_TRANSPORT` | "stdio" | Transport protocol |
| `MCP_DATABASE_PATH` | "data/library.db" | Database location |
| `MCP_LOG_LEVEL` | "INFO" | Logging verbosity |
| `MCP_ENABLE_SAMPLING` | "true" | Enable AI features |

### File Structure

```
virtual-library-mcp/
├── server.py           # Main server entry point
├── config.py           # Configuration management
├── sampling.py         # AI sampling implementation
├── database/           # Database layer
│   ├── schema.py       # SQLAlchemy models
│   └── *_repository.py # Repository patterns
├── models/             # Pydantic models
├── resources/          # MCP resources (read-only)
├── tools/              # MCP tools (actions)
├── prompts/            # MCP prompts (templates)
├── data/               # Database and samples
│   ├── library.db      # SQLite database
│   └── samples/        # Import samples
└── logs/               # Server logs
```

### Testing Checklist

- [ ] Server starts without errors
- [ ] VS Code connection established
- [ ] Can list books (resources)
- [ ] Can search catalog (tools)
- [ ] Can checkout/return books (tools)
- [ ] Can generate recommendations (prompts)
- [ ] Can generate AI summaries (sampling)
- [ ] Can import bulk data (tools)
- [ ] Error handling works correctly

---

## Next Steps

1. **Explore the Code**: Review the implementation in `server.py` and related modules
2. **Extend Features**: Add new tools, resources, or prompts
3. **Custom Integrations**: Connect to other MCP clients
4. **Production Deployment**: Configure for production use with proper authentication

## Support

For issues or questions:
1. Check the [MCP Documentation](https://modelcontextprotocol.io)
2. Review `docs/mcp/` for protocol details
3. See `DEVELOPMENT.md` for contribution guidelines
4. Open an issue on GitHub for bugs or feature requests

---

*Last Updated: December 2024*
*Version: 0.3.0*