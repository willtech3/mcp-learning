# Virtual Library MCP Server - Feature Testing Guide

This guide provides step-by-step instructions for testing each implemented MCP feature.

## Quick Start Testing Script

First, ensure the server is running:
```bash
cd virtual-library-mcp
just dev
```

## 1. Testing Resources (Read-Only Operations)

### Basic Book Listing
```javascript
// Test command in Claude Desktop
"Show me the first 10 books in the library"

// Expected: List of books with ISBN, title, author, availability
```

### URI Template Resources
```javascript
// Get books by a specific author
"Show books by author_tolkien01"

// Get books in a specific genre
"List all Mystery books"

// Get patron details
"Show details for patron p_anderson_01"
```

### Advanced Resources
```javascript
// Get book with full details
"Get complete details for book 9780134190440"

// Library statistics
"Show library statistics including total books, checkouts, and popular genres"

// Get recommendations (requires populated circulation data)
"Show personalized recommendations for patron p_anderson_01"
```

## 2. Testing Tools (Write Operations)

### Search Functionality
```javascript
// Basic search
"Search for books with 'programming' in the title"

// Advanced search with filters
"Search for available Science Fiction books published after 2010"

// Author search
"Find all books by authors with 'King' in their name"

// Combined filters
"Search for Mystery books that are currently available, sorted by publication year"
```

### Circulation Operations

#### Checkout Flow
```javascript
// Step 1: Find an available book
"Search for available Fiction books"

// Step 2: Note an ISBN from results, then checkout
"Checkout book [ISBN] to patron p_anderson_01"

// Step 3: Verify checkout
"Show current checkouts for patron p_anderson_01"

// Custom due date checkout
"Checkout book [ISBN] to patron p_smith_02 with due date 2024-12-31"
```

#### Return Flow
```javascript
// Step 1: Get active checkouts
"Show all active checkouts"

// Step 2: Note a checkout ID and return it
"Return checkout [checkout_id]"

// With condition notes
"Return checkout [checkout_id] with condition 'Minor wear on spine'"
```

#### Reservation Flow
```javascript
// Step 1: Find a book with no available copies
"Search for books with 0 available copies"

// Step 2: Create reservation
"Reserve book [ISBN] for patron p_johnson_03"

// Step 3: Check reservation queue
"Show all active reservations"
```

### Book Insights (Sampling Feature)

Test if your client supports sampling:
```javascript
// Generate AI summary
"Generate a summary for book 9780134190440"

// If sampling is supported, you'll get an AI-generated summary
// If not, you'll get book information with a note about sampling requirements

// Other insight types
"Generate themes analysis for book 9780141439518"
"Create discussion questions for book 9780062316110"
"Find books similar to 9780765377142"
```

### Bulk Import

Test with sample files:
```javascript
// Import CSV file
"Import books from data/samples/books_sample.csv"

// Import JSON file with custom batch size
"Import books from data/samples/books_sample.json with batch size 25"

// Monitor import progress (if supported by client)
// The tool will report progress updates during import
```

### Catalog Maintenance
```javascript
// Run full catalog regeneration
"Regenerate the library catalog"

// This will:
// 1. Check data integrity
// 2. Rebuild search indexes
// 3. Update circulation statistics
// 4. Generate recommendation cache
```

## 3. Testing Prompts (LLM Templates)

### Book Recommendations
```javascript
// Basic recommendation
"Get book recommendations"

// With genre preference
"Recommend mystery books"

// For specific patron
"Recommend books for patron p_anderson_01 based on their reading history"

// Complex recommendation
"Recommend 5 science fiction books for a teenager who likes action and space exploration"
```

### Reading Plans
```javascript
// Basic reading plan
"Create a reading plan"

// With parameters
"Create a 6-month reading plan for classic literature"

// Advanced plan
"Create a 3-month intermediate reading plan for mystery novels with 5 hours per week available"
```

### Review Generation
```javascript
// Basic review
"Generate a review for book 9780134190440"

// Different review styles
"Generate a critical review for book 9780141439518"
"Generate a casual review for book 9780062316110 targeted at young adults"

// With circulation data
"Generate a review for book 9780765377142 including its popularity data"
```

## 4. Testing Complex Workflows

### Complete Patron Journey
```javascript
// 1. Search for interesting books
"Search for highly-rated Science Fiction books"

// 2. Get details on a specific book
"Show details for book [ISBN from search]"

// 3. Generate insights
"Generate a summary for book [ISBN]"

// 4. Checkout the book
"Checkout book [ISBN] to patron p_anderson_01"

// 5. Get a reading plan
"Create a reading plan starting with [book title]"
```

### Library Management Workflow
```javascript
// 1. Check library statistics
"Show library statistics"

// 2. Identify overdue books
"Show all overdue checkouts"

// 3. Process returns
"Return checkout [overdue_checkout_id] with late fee"

// 4. Update catalog
"Regenerate catalog to update statistics"
```

### Data Import and Verification
```javascript
// 1. Check current book count
"How many books are in the library?"

// 2. Import new books
"Import books from data/samples/books_sample.csv"

// 3. Verify import
"Search for newly imported books published in 2024"

// 4. Check updated statistics
"Show library statistics"
```

## 5. Testing Error Handling

### Invalid Operations
```javascript
// Invalid ISBN
"Get details for book INVALID_ISBN"
// Expected: Error message about invalid ISBN format

// Non-existent patron
"Checkout book 9780134190440 to patron non_existent"
// Expected: Patron not found error

// Checkout unavailable book
"Checkout book [ISBN with 0 copies] to patron p_anderson_01"
// Expected: No copies available error

// Invalid date
"Checkout book 9780134190440 to patron p_anderson_01 with due date 2020-01-01"
// Expected: Due date must be in the future error
```

### Validation Testing
```javascript
// Search with invalid parameters
"Search for books with page size 1000"
// Expected: Page size limited to 100

// Empty search
"Search for books with empty query"
// Expected: Returns all books or requires search criteria

// Duplicate operations
"Reserve book [already reserved ISBN] for patron [same patron]"
// Expected: Duplicate reservation error
```

## 6. Performance Testing

### Large Dataset Operations
```javascript
// Get maximum results
"List 100 books"

// Complex search
"Search for books with 'the' in title or description"

// Bulk operations
"Import books from data/samples/books_medium.csv"
// Note: This file should contain 500+ books for performance testing
```

## 7. Client Capability Testing

### Check Sampling Support
```javascript
"Generate AI insights for book 9780134190440"
// If supported: Returns AI-generated content
// If not supported: Returns fallback content with explanation
```

### Check Progress Notification Support
```javascript
"Import books from a large CSV file"
// If supported: Shows progress updates during import
// If not supported: Shows final result only
```

## Test Sequences by Feature

### Complete Resource Test
1. List all books
2. Get specific book by ISBN
3. Browse by author
4. Browse by genre
5. View patron details
6. Check library statistics

### Complete Tool Test
1. Search catalog with various filters
2. Checkout a book
3. Return the book
4. Reserve an unavailable book
5. Generate insights (if sampling available)
6. Import new books
7. Regenerate catalog

### Complete Prompt Test
1. Get basic recommendations
2. Create a reading plan
3. Generate book reviews
4. Test with different parameters

## Verification Checklist

- [ ] **Resources**: All read operations return expected data
- [ ] **Tools**: All write operations modify database correctly
- [ ] **Prompts**: All templates generate appropriate responses
- [ ] **Sampling**: AI features work when available, fallback when not
- [ ] **Error Handling**: Invalid inputs return helpful error messages
- [ ] **Performance**: Large operations complete within reasonable time
- [ ] **Data Integrity**: Database remains consistent after operations

## Tips for Testing

1. **Start Fresh**: Initialize a clean database for consistent testing
   ```bash
   just init-db
   ```

2. **Use Logging**: Monitor server logs during testing
   ```bash
   tail -f logs/server.log
   ```

3. **Check Database**: Verify changes directly in SQLite
   ```bash
   sqlite3 data/library.db "SELECT * FROM checkouts ORDER BY checkout_date DESC LIMIT 5;"
   ```

4. **Test Edge Cases**: Try boundary values, empty inputs, and invalid data

5. **Document Issues**: Note any unexpected behavior with:
   - Exact command used
   - Expected vs actual result
   - Error messages
   - Log output

## Sample Test Session

Here's a complete test session you can run:

```javascript
// 1. Initial state
"Show library statistics"

// 2. Search and browse
"Search for Python programming books"
"Get details for book 9780134190440"

// 3. Patron operations
"Show patron p_anderson_01 details"
"Checkout book 9780134190440 to patron p_anderson_01"

// 4. AI features (if available)
"Generate a summary for book 9780134190440"
"Recommend similar books"

// 5. Management
"Show all active checkouts"
"Return checkout [checkout_id from previous step]"

// 6. Bulk operations
"Import books from data/samples/books_sample.csv"

// 7. Final state
"Show library statistics"
```

This sequence tests all major features and validates the complete workflow.

---

*For more details, see the main USER_GUIDE.md*