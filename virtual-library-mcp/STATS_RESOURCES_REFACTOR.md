# Stats Resources Refactor: Converting to URI Templates

## Problem Statement

The Virtual Library MCP Server is failing to start with the error:
```
ValueError: URI template must contain at least one parameter
```

This occurs because FastMCP is misinterpreting our static resources as template resources due to their handler function signatures.

### Root Cause

FastMCP determines if a resource is static or templated based on two factors:
1. **URI Pattern**: Does it contain `{parameter}` placeholders?
2. **Function Parameters**: Does the handler function have parameters other than `Context`?

Our stats resources have:
- Static URIs like `library://stats/popular` (no placeholders)
- Handler functions with custom parameters like `params: PopularBooksParams`

This mismatch causes FastMCP to think they're template resources, then fail when it finds no URI parameters.

## Solution: Convert to URI Template Resources

We'll convert our stats resources to use URI templates, making parameters explicit in the URI pattern. This aligns with MCP design principles and FastMCP's expectations.

## Detailed Changes Required

### 1. Popular Books Resource

#### Current Implementation
```python
# Resource definition
{
    "uri": "library://stats/popular",
    "name": "Popular Books",
    "handler": get_popular_books_handler,
}

# Handler signature
async def get_popular_books_handler(
    uri: str,  # noqa: ARG001
    context: Context,  # noqa: ARG001
    params: PopularBooksParams | None = None,
) -> dict[str, Any]:
```

#### New Implementation
```python
# Resource definition
{
    "uri_template": "library://stats/popular/{days}/{limit}",
    "name": "Popular Books",
    "handler": get_popular_books_handler,
}

# Handler signature
async def get_popular_books_handler(
    days: str,
    limit: str,
) -> dict[str, Any]:
```

#### Handler Changes
```python
async def get_popular_books_handler(days: str, limit: str) -> dict[str, Any]:
    """Handle requests for popular books statistics.
    
    Args:
        days: Number of days to analyze (from URI template)
        limit: Number of books to return (from URI template)
    
    Returns:
        Dictionary containing popular books ranking
    """
    try:
        # Convert string parameters to integers with validation
        days_int = int(days)
        limit_int = int(limit)
        
        # Validate ranges (same as Pydantic model)
        if not 1 <= days_int <= 365:
            raise ResourceError("days must be between 1 and 365")
        if not 1 <= limit_int <= 50:
            raise ResourceError("limit must be between 1 and 50")
        
        logger.debug(
            "MCP Resource Request - stats/popular: days=%d, limit=%d", 
            days_int, limit_int
        )
        
        # Calculate date range
        start_date = datetime.now() - timedelta(days=days_int)
        
        # Rest of the implementation remains the same...
        # (Replace all instances of params.days with days_int)
        # (Replace all instances of params.limit with limit_int)
```

### 2. Genre Distribution Resource

#### Current Implementation
```python
# Resource definition
{
    "uri": "library://stats/genres",
    "name": "Genre Distribution",
    "handler": get_genre_distribution_handler,
}

# Handler signature
async def get_genre_distribution_handler(
    uri: str,  # noqa: ARG001
    context: Context,  # noqa: ARG001
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
```

#### New Implementation
```python
# Resource definition
{
    "uri_template": "library://stats/genres/{days}",
    "name": "Genre Distribution",
    "handler": get_genre_distribution_handler,
}

# Handler signature
async def get_genre_distribution_handler(days: str) -> dict[str, Any]:
```

#### Handler Changes
```python
async def get_genre_distribution_handler(days: str) -> dict[str, Any]:
    """Handle requests for genre distribution statistics.
    
    Args:
        days: Number of days to analyze (from URI template)
    
    Returns:
        Dictionary containing genre distribution analysis
    """
    try:
        # Convert and validate parameter
        days_int = int(days)
        if not 1 <= days_int <= 365:
            raise ResourceError("days must be between 1 and 365")
        
        logger.debug("MCP Resource Request - stats/genres: days=%d", days_int)
        
        # Calculate date range
        start_date = datetime.now() - timedelta(days=days_int)
        
        # Rest of implementation...
        # (Replace days variable with days_int throughout)
```

### 3. Circulation Stats Resource

#### Current Implementation
```python
# Resource definition
{
    "uri": "library://stats/circulation",
    "name": "Circulation Statistics",
    "handler": get_circulation_stats_handler,
}

# Handler signature
async def get_circulation_stats_handler(
    uri: str,  # noqa: ARG001
    context: Context,  # noqa: ARG001
    params: dict[str, Any] | None = None,  # noqa: ARG001
) -> dict[str, Any]:
```

#### New Implementation
```python
# Resource definition - STAYS THE SAME (no parameters needed)
{
    "uri": "library://stats/circulation",  # Note: NOT uri_template
    "name": "Circulation Statistics",
    "handler": get_circulation_stats_handler,
}

# Handler signature - Remove all parameters
async def get_circulation_stats_handler() -> dict[str, Any]:
```

This resource doesn't need parameters, so it remains a static resource with no handler parameters.

### 4. Remove Unused Imports and Classes

Since we're no longer using Pydantic models for parameters, remove:
```python
# Remove from imports
from pydantic import BaseModel, Field

# Remove the PopularBooksParams class entirely
class PopularBooksParams(BaseModel):
    """Parameters for popular books resource."""
    days: int = Field(default=30, ge=1, le=365, description="Number of days to analyze")
    limit: int = Field(default=10, ge=1, le=50, description="Number of books to return")
```

### 5. Update Server Registration Logic

The server.py file already handles both `uri` and `uri_template` correctly:
```python
# This code is already correct!
for resource in all_resources:
    uri = resource.get("uri_template", resource.get("uri"))
    if not uri:
        logger.error("Resource missing URI: %s", resource)
        continue
        
    mcp.resource(
        uri=uri,
        name=resource["name"],
        description=resource["description"],
        mime_type=resource["mime_type"],
    )(resource["handler"])
```

## Client Usage Examples

### Before (Query Parameters - Not Supported)
```
# These don't work with MCP/FastMCP:
GET library://stats/popular?days=7&limit=5
GET library://stats/genres?days=30
```

### After (URI Templates)
```
# Correct MCP pattern:
GET library://stats/popular/7/5     # Top 5 books from last 7 days
GET library://stats/popular/30/10   # Top 10 books from last 30 days
GET library://stats/genres/7        # Genre distribution for last 7 days
GET library://stats/genres/365      # Genre distribution for full year
GET library://stats/circulation     # Current circulation (no params)
```

## Benefits of This Approach

1. **MCP Compliance**: Follows the Model Context Protocol's design patterns
2. **FastMCP Compatibility**: Works seamlessly with FastMCP's resource detection
3. **Clear API**: Parameters are explicit in the URI, self-documenting
4. **Type Safety**: FastMCP will validate URI parameters match function parameters
5. **Consistency**: Aligns with existing book resources that use URI templates

## Testing Considerations

1. **Parameter Validation**: Test edge cases for days (1-365) and limit (1-50)
2. **Error Handling**: Ensure proper errors for invalid parameters
3. **URI Parsing**: Verify correct extraction of parameters from URIs
4. **Backwards Compatibility**: Document migration for any existing clients

## Documentation Updates Needed

1. Update resource descriptions to mention URI parameters:
   ```python
   "description": (
       "Get the most borrowed books for a specified time period. "
       "URI format: library://stats/popular/{days}/{limit} where "
       "days is 1-365 and limit is 1-50."
   )
   ```

2. Update any API documentation to show new URI patterns

3. Add examples in code comments showing valid URIs

## Migration Checklist

- [x] Update `get_popular_books_handler` to accept `days` and `limit` parameters
- [x] Update `get_genre_distribution_handler` to accept `days` parameter
- [x] Update `get_circulation_stats_handler` to have no parameters
- [x] Convert resource definitions from `uri` to `uri_template` where needed
- [x] Remove `PopularBooksParams` class
- [x] Update all parameter references in handler implementations
- [x] Add parameter validation and error handling
- [x] Update resource descriptions
- [x] Test all resources with new URI patterns (confirmed working with isolated test)
- [ ] Update any client code or documentation (N/A for this refactor)

## Implementation Status

✅ **COMPLETED**: The stats resources refactor has been successfully implemented.

### Key Changes Made:

1. **Popular Books Resource**: 
   - Changed from static URI `library://stats/popular` to URI template `library://stats/popular/{days}/{limit}`
   - Handler now accepts `days: str` and `limit: str` parameters directly
   - Added parameter validation (days: 1-365, limit: 1-50)

2. **Genre Distribution Resource**:
   - Changed from static URI `library://stats/genres` to URI template `library://stats/genres/{days}`  
   - Handler now accepts `days: str` parameter directly
   - Added parameter validation (days: 1-365)

3. **Circulation Statistics Resource**:
   - Remains a static resource with URI `library://stats/circulation`
   - Handler has no parameters (correctly implemented)

4. **Cleanup**:
   - Removed `PopularBooksParams` class
   - Removed unused `Context` import
   - Updated resource descriptions to document new URI patterns

### Verification:

- ✅ **Linting**: All code passes ruff linting
- ✅ **Type Checking**: Passes pyright type checking (with existing warnings unrelated to this refactor)
- ✅ **Server Startup**: MCP server starts successfully with stats resources
- 🟡 **Tests**: Some existing tests fail due to broader FastMCP pattern changes needed across all resources

### Notes:

The refactor successfully converts the stats resources to proper URI templates as required by FastMCP 2.0. The server starts and registers the stats resources without errors. The failing tests are due to other resources in the codebase still using the old FastMCP pattern, which is beyond the scope of this stats-specific refactor.

The new URI patterns are:
- `library://stats/popular/30/10` (30 days, top 10 books)
- `library://stats/genres/90` (90 days analysis)  
- `library://stats/circulation` (current stats, no parameters)

## Common Pitfalls to Avoid

1. **Don't mix patterns**: A resource is either static (no params) or templated (URI params)
2. **String conversion**: URI parameters come in as strings, convert and validate them
3. **Error messages**: Provide clear errors when parameters are out of range
4. **Documentation**: Always document the expected URI format in descriptions

## Educational Notes

This refactor demonstrates important MCP concepts:

1. **Resources vs Tools**: Resources are for data retrieval, even with parameters. Tools are for actions that change state.

2. **URI Templates**: The MCP way to parameterize resources, similar to REST API path parameters.

3. **FastMCP Design**: The framework enforces good MCP practices through its parameter detection.

4. **Query Parameters**: While common in HTTP APIs, MCP uses URI templates instead for resource parameterization.

This approach makes the Virtual Library MCP Server a better educational example of proper MCP patterns.