"""URI Utilities for MCP Resources

This module provides a unified approach to parsing MCP resource URIs.
It demonstrates important software engineering principles:
1. DRY (Don't Repeat Yourself) - Extracting common patterns
2. Single Responsibility - Each function has one clear purpose
3. Educational Documentation - Explains MCP concepts alongside code

MCP URI STRUCTURE:
All MCP resources use URIs to uniquely identify resources. In our library:
- Scheme: Always "library://" for our virtual library
- Path: Hierarchical structure like "/books/{isbn}" or "/patrons/{id}/history"
- Parameters: Dynamic values extracted from the path

LEARNING OBJECTIVES:
- Understanding URI parsing and validation
- Building reusable abstractions
- Proper error handling with context
- Type safety with clear contracts
"""

import logging
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)


class URIParseError(ValueError):
    """Raised when a URI cannot be parsed according to expected format.

    This custom exception provides better error context than generic ValueError.
    """


def parse_library_uri(uri: str) -> list[str]:
    """Parse a library:// URI into its path components.

    This is the foundation for all URI parsing in our MCP server.
    It handles the quirks of urlparse with custom schemes.

    IMPLEMENTATION NOTES:
    - urlparse treats "library://books/123" as having "books" as the netloc
    - We need to reconstruct the full path from netloc + path
    - This abstraction hides these implementation details

    Args:
        uri: Full MCP resource URI (e.g., "library://books/978-0-123")

    Returns:
        List of path components (e.g., ["books", "978-0-123"])

    Raises:
        URIParseError: If the URI is malformed or uses wrong scheme
    """
    try:
        parsed = urlparse(uri)

        # Validate scheme
        if parsed.scheme != "library":
            raise URIParseError(
                f"Invalid URI scheme '{parsed.scheme}'. "
                f"Expected 'library://' but got '{parsed.scheme}://'"
            )

        # Reconstruct full path from urlparse components
        # This handles the various ways urlparse might split the URI
        if parsed.netloc and parsed.path:
            # Standard case: library://books/isbn
            full_path = f"{parsed.netloc}{parsed.path}"
        elif parsed.netloc:
            # Edge case: library://books (no trailing content)
            full_path = parsed.netloc
        elif parsed.path:
            # Edge case: library:///books/isbn (triple slash)
            full_path = parsed.path.lstrip("/")
        else:
            raise URIParseError(f"No path found in URI: {uri}")

        # Split into components and filter empty strings
        components = [part for part in full_path.split("/") if part]

        if not components:
            raise URIParseError(f"Empty path in URI: {uri}")

        return components

    except Exception as e:
        if isinstance(e, URIParseError):
            raise
        raise URIParseError(f"Failed to parse URI '{uri}': {e}") from e


def extract_path_parameter(
    uri: str,
    expected_path: list[str],
    parameter_index: int,
    parameter_name: str,
    decode: bool = True,
) -> str:
    """Extract a parameter from a structured URI path.

    This is the main abstraction that eliminates redundancy across our resources.
    It validates the URI structure and extracts the requested parameter.

    DESIGN DECISIONS:
    - Uses explicit expected_path for validation (fail fast principle)
    - Supports URL decoding for parameters with special characters
    - Provides clear error messages for debugging
    - Parameter index is 0-based after the expected path

    Args:
        uri: Full MCP resource URI
        expected_path: Expected path structure (e.g., ["books", "by-author"])
        parameter_index: Index of parameter after expected path (0-based)
        parameter_name: Human-readable name for error messages
        decode: Whether to URL-decode the parameter

    Returns:
        The extracted parameter value

    Raises:
        URIParseError: If URI doesn't match expected structure

    Examples:
        >>> extract_path_parameter("library://books/978-0-123", ["books"], 0, "ISBN")
        "978-0-123"

        >>> extract_path_parameter(
        ...     "library://books/by-author/Jane%20Doe",
        ...     ["books", "by-author"],
        ...     0,
        ...     "author ID",
        ... )
        "Jane Doe"
    """
    components = parse_library_uri(uri)

    # Validate path structure
    if len(components) < len(expected_path):
        raise URIParseError(
            f"Invalid URI structure. Expected path starting with "
            f"'/{'/'.join(expected_path)}' but got '/{'/'.join(components)}'"
        )

    # Check each expected path component
    for i, expected in enumerate(expected_path):
        if components[i] != expected:
            raise URIParseError(
                f"Invalid URI structure at position {i}. "
                f"Expected '{expected}' but got '{components[i]}'"
            )

    # Calculate actual parameter position
    param_position = len(expected_path) + parameter_index

    # Validate parameter exists
    if len(components) <= param_position:
        raise URIParseError(
            f"Missing {parameter_name} in URI. Expected at least "
            f"{param_position + 1} path components but got {len(components)}"
        )

    # Extract parameter
    parameter = components[param_position]

    if not parameter:
        raise URIParseError(f"Empty {parameter_name} in URI")

    # Decode if requested
    if decode:
        parameter = unquote(parameter)

    return parameter


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================
# These wrap the generic function for specific use cases
# providing clear, self-documenting APIs


def extract_isbn_from_uri(uri: str) -> str:
    """Extract ISBN from library://books/{isbn} URI.

    Args:
        uri: Full resource URI

    Returns:
        The ISBN string

    Raises:
        URIParseError: If URI format is invalid
    """
    return extract_path_parameter(
        uri=uri,
        expected_path=["books"],
        parameter_index=0,
        parameter_name="ISBN",
        decode=False,  # ISBNs shouldn't need decoding
    )


def extract_patron_id_from_uri(uri: str) -> str:
    """Extract patron ID from library://patrons/{id} URI.

    Args:
        uri: Full resource URI

    Returns:
        The patron ID

    Raises:
        URIParseError: If URI format is invalid
    """
    return extract_path_parameter(
        uri=uri,
        expected_path=["patrons"],
        parameter_index=0,
        parameter_name="patron ID",
        decode=True,  # Patron IDs might have special chars
    )


def extract_author_id_from_books_uri(uri: str) -> str:
    """Extract author ID from library://books/by-author/{id} URI.

    Args:
        uri: Full resource URI

    Returns:
        The decoded author ID

    Raises:
        URIParseError: If URI format is invalid
    """
    return extract_path_parameter(
        uri=uri,
        expected_path=["books", "by-author"],
        parameter_index=0,
        parameter_name="author ID",
        decode=True,  # Author names need decoding
    )


def extract_genre_from_books_uri(uri: str) -> str:
    """Extract genre from library://books/by-genre/{genre} URI.

    Args:
        uri: Full resource URI

    Returns:
        The decoded genre name

    Raises:
        URIParseError: If URI format is invalid
    """
    return extract_path_parameter(
        uri=uri,
        expected_path=["books", "by-genre"],
        parameter_index=0,
        parameter_name="genre",
        decode=True,  # Genres might have spaces
    )


def extract_patron_id_from_history_uri(uri: str) -> str:
    """Extract patron ID from library://patrons/{id}/history URI.

    Args:
        uri: Full resource URI

    Returns:
        The patron ID

    Raises:
        URIParseError: If URI format is invalid
    """
    # For history URIs, we still want the patron ID (first parameter)
    return extract_path_parameter(
        uri=uri,
        expected_path=["patrons"],
        parameter_index=0,
        parameter_name="patron ID",
        decode=True,
    )


def extract_patron_id_from_recommendations_uri(uri: str) -> str:
    """Extract patron ID from library://recommendations/{id} URI.

    Args:
        uri: Full resource URI

    Returns:
        The patron ID

    Raises:
        URIParseError: If URI format is invalid
    """
    return extract_path_parameter(
        uri=uri,
        expected_path=["recommendations"],
        parameter_index=0,
        parameter_name="patron ID",
        decode=True,
    )


# =============================================================================
# VALIDATION UTILITIES
# =============================================================================


def validate_resource_uri(uri: str, _expected_pattern: str) -> bool:
    """Validate that a URI matches an expected pattern.

    This is useful for early validation in resource handlers.

    Args:
        uri: URI to validate
        _expected_pattern: Pattern like "library://books/{isbn}" (placeholder for future use)

    Returns:
        True if URI matches pattern

    Example:
        >>> validate_resource_uri("library://books/123", "library://books/{isbn}")
        True
    """
    try:
        # Simple validation - just check if we can parse it
        parse_library_uri(uri)
        # In a more sophisticated implementation, we could parse
        # _expected_pattern and validate the structure matches
        return True
    except URIParseError:
        return False
