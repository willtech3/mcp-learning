# Virtual Library MCP Server Implementation Plan

## Project Overview
A Python-based MCP server simulating a library management system to demonstrate all MCP concepts through hands-on exploration.

## Technology Stack
- **Python**: Latest (3.12+)
- **Framework**: FastMCP 2.0
- **Type Checking**: Pyright (best VS Code integration, comprehensive checking)
- **Data Validation**: Pydantic v2
- **Package Manager**: uv
- **Testing**: pytest
- **Linting/Formatting**: ruff
- **Task Runner**: just (justfile)
- **Database**: SQLite with SQLAlchemy
- **MCP SDK**: Official Python SDK via FastMCP

## Project Structure
```
virtual-library-mcp/
├── pyproject.toml          # Project configuration
├── justfile                # Task automation
├── .python-version         # Python version (3.12)
├── README.md               # Project documentation
├── src/
│   └── virtual_library_mcp/
│       ├── __init__.py
│       ├── server.py       # FastMCP server setup
│       ├── config.py       # Configuration with Pydantic
│       ├── models/         # Pydantic models
│       │   ├── __init__.py
│       │   ├── book.py
│       │   ├── author.py
│       │   ├── patron.py
│       │   └── circulation.py
│       ├── database/       # Database layer
│       │   ├── __init__.py
│       │   ├── schema.py   # SQLAlchemy models
│       │   ├── session.py  # Database connection
│       │   └── seed.py     # Data generation
│       ├── resources/      # MCP resources
│       │   ├── __init__.py
│       │   ├── books.py
│       │   ├── authors.py
│       │   └── patrons.py
│       ├── tools/          # MCP tools
│       │   ├── __init__.py
│       │   ├── circulation.py
│       │   └── search.py
│       └── prompts/        # MCP prompts
│           ├── __init__.py
│           └── recommendations.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py         # pytest fixtures
│   ├── test_resources.py
│   ├── test_tools.py
│   └── test_integration.py
├── data/
│   └── .gitkeep           # Generated database location
└── scripts/
    ├── generate_data.py    # Standalone data generator
    └── test_client.py      # Example MCP client

```

## Implementation Steps

### Phase 1: Project Setup (Steps 1-5)

#### Step 1: Initialize Project Structure
- Create project directory
- Initialize git repository
- Create basic directory structure
- **Verification**: Directory tree matches specification

#### Step 2: Configure Development Environment
- Create `pyproject.toml` with dependencies:
  - fastmcp
  - pydantic>=2.0
  - sqlalchemy>=2.0
  - faker (for data generation)
  - python-dotenv
- Create `.python-version` file (3.12)
- Create `justfile` with tasks:
  - `just install`: Install dependencies
  - `just dev`: Run development server
  - `just test`: Run tests
  - `just lint`: Run ruff
  - `just typecheck`: Run pyright
  - `just format`: Format code
- **Verification**: `uv sync` completes successfully

#### Step 3: Setup Development Tools
- Configure ruff in `pyproject.toml`
- Configure pyright in `pyproject.toml`
- Setup pre-commit hooks (optional)
- Create `.gitignore`
- **Verification**: `just lint` and `just typecheck` run without errors

#### Step 4: Create Configuration System
- Implement `config.py` with Pydantic settings
- Environment variables support
- Database path configuration
- Server settings (name, version)
- **Verification**: Configuration loads from environment

#### Step 5: Setup Testing Framework
- Configure pytest in `pyproject.toml`
- Create `conftest.py` with fixtures
- Create test database fixture
- **Verification**: `just test` runs dummy test

### Phase 2: Data Models and Database (Steps 6-10)

#### Step 6: Define Pydantic Models
- Create `models/book.py`:
  - ISBN, title, author_id, genre, publication_year
  - Available copies, total copies
- Create `models/author.py`:
  - Name, biography, birth_date
- Create `models/patron.py`:
  - Name, email, membership_date
- Create `models/circulation.py`:
  - Checkout, return, reservation records
- **Verification**: Models instantiate with validation

#### Step 7: Create Database Schema
- Setup SQLAlchemy models in `database/schema.py`
- Define relationships (books ↔ authors)
- Create database session management
- **Verification**: Tables create successfully

#### Step 8: Implement Data Generation
- Create `database/seed.py` with Faker
- Generate 1000+ books with realistic data
- Generate 100+ authors with relationships
- Generate 50+ patrons
- Create circulation history
- **Verification**: Database populated with realistic data

#### Step 9: Create Data Access Layer
- Implement repository pattern for each model
- Add pagination support
- Add filtering and sorting
- **Verification**: Can query data with various filters

#### Step 10: Add Database Utilities
- Create backup/restore functions
- Add migration support (alembic optional)
- Create indexes for performance
- **Verification**: Database operations are performant

### Phase 3: MCP Server Core (Steps 11-15)

#### Step 11: Initialize FastMCP Server
- Create `server.py` with FastMCP setup
- Configure server metadata
- Setup logging
- **Verification**: Server starts without errors

#### Step 12: Implement Basic Resources
- Create `/books/list` resource
- Add pagination to list endpoints
- Implement `/books/{isbn}` detail view
- **Verification**: Can retrieve book data via MCP

#### Step 13: Add Advanced Resources
- Implement URI templates (`/books/by-author/{id}`)
- Add `/stats/popular` aggregation endpoint
- Create `/recommendations/{patron_id}` 
- **Verification**: All resource endpoints return data

#### Step 14: Create First Tool
- Implement `search_catalog` tool
- Add input validation with JSON schema
- Return structured results
- **Verification**: Tool executes with valid/invalid inputs

#### Step 15: Add Circulation Tools
- Implement `checkout_book` with availability check
- Add `return_book` with optional review
- Create `reserve_book` for holds
- **Verification**: State changes persist correctly

### Phase 4: Advanced Features (Steps 16-20)

#### Step 16: Implement Subscriptions
- Add subscription support to FastMCP
- Create book availability notifications
- Implement reservation queue updates
- **Verification**: Clients receive real-time updates

#### Step 17: Add Progress Notifications
- Implement bulk import tool
- Add progress reporting for long operations
- Create catalog regeneration with updates
- **Verification**: Progress updates sent during operations

#### Step 18: Create Prompts System
- Implement `recommend_book` prompt
- Add `reading_plan` generator
- Create `summarize_book` prompt
- **Verification**: Prompts return formatted messages

#### Step 19: Add Error Handling
- Implement custom exception classes
- Add detailed error responses
- Create conflict scenarios (double checkout)
- **Verification**: Errors return appropriate codes/messages

#### Step 20: Implement Complex Queries
- Add multi-parameter search
- Implement faceted search results
- Add sorting options
- **Verification**: Complex queries return accurate results

### Phase 5: Testing and Documentation (Steps 21-25)

#### Step 21: Write Unit Tests
- Test all models with edge cases
- Test database operations
- Test individual resource handlers
- **Verification**: 80%+ code coverage

#### Step 22: Create Integration Tests
- Test full checkout/return flow
- Test subscription scenarios
- Test error conditions
- **Verification**: End-to-end flows work correctly

#### Step 23: Build Example Client
- Create Python client using MCP SDK
- Demonstrate all server features
- Add interactive CLI interface
- **Verification**: Client can perform all operations

#### Step 24: Write Documentation
- Create comprehensive README
- Document all resources and tools
- Add API examples
- Include setup instructions
- **Verification**: New user can follow docs to setup

#### Step 25: Performance Testing
- Load test with concurrent requests
- Optimize slow queries
- Add caching where appropriate
- **Verification**: Server handles 100+ concurrent requests

## Success Criteria

1. **All MCP Concepts Demonstrated**:
   - Resources with URI templates ✓
   - Tools with validation ✓
   - Prompts with arguments ✓
   - Subscriptions ✓
   - Progress notifications ✓
   - Error handling ✓

2. **Code Quality**:
   - Passes pyright type checking
   - Passes ruff linting
   - 80%+ test coverage
   - Clear documentation

3. **Learning Value**:
   - Easy to explore via client
   - Clear examples of each concept
   - Realistic data and scenarios
   - Extensible for experiments

## Next Steps

After implementation:
1. Create tutorial walkthrough
2. Add more complex scenarios
3. Build web UI client (optional)
4. Package for easy distribution