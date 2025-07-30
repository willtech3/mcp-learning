"""Configuration management for Virtual Library MCP Server.

This module demonstrates MCP best practices for configuration:
1. Protocol Metadata - Required for server identification
2. Transport Configuration - Extensible for multiple transports
3. Security - Environment-based secrets management
4. Validation - Type-safe configuration with Pydantic v2
"""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerConfig(BaseSettings):
    """MCP Server configuration following protocol requirements.

    MCP servers MUST provide:
    - Server name and version for protocol handshake
    - Transport configuration (stdio, HTTP/SSE, etc.)
    - Resource paths and connection strings

    This configuration class demonstrates:
    1. Protocol-compliant metadata
    2. Environment variable integration
    3. Secure defaults
    4. Validation for MCP requirements
    """

    model_config = SettingsConfigDict(
        # Use VIRTUAL_LIBRARY_ prefix for all env vars
        # This prevents conflicts with other services
        env_prefix="VIRTUAL_LIBRARY_",
        # Load from .env file if present
        # Enables easy local development
        env_file=".env",
        # Allow .env.local for personal overrides
        env_file_encoding="utf-8",
        # Case-insensitive env vars for better UX
        case_sensitive=False,
        # Allow extra fields for future extensibility
        # MCP protocol may add new capabilities
        extra="allow",
    )

    # === Server Metadata (Required by MCP Protocol) ===

    server_name: str = Field(
        default="virtual-library",
        description="MCP server name used in protocol handshake",
        # MCP best practice: use lowercase with hyphens
        pattern=r"^[a-z0-9-]+$",
    )

    server_version: str = Field(
        default="0.1.0",
        description="Server version for capability negotiation",
        # Semantic versioning for clear compatibility
        pattern=r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$",
    )

    # === Database Configuration ===

    database_path: Path = Field(
        default=Path("data/library.db"),
        description="SQLite database file path",
    )

    # === Transport Configuration ===
    # MCP servers can support multiple transports

    transport: str = Field(
        default="stdio",
        description="Primary transport mechanism",
        # We start with stdio, but design for extensibility to Streamable HTTP
        pattern=r"^(stdio|streamable_http)$",
    )

    # Streamable HTTP configuration (for future use)
    # Demonstrates forward-thinking design
    http_host: str = Field(
        default="127.0.0.1",
        description="HTTP server host for Streamable HTTP transport",
    )

    http_port: int = Field(
        default=8080,
        description="HTTP server port for Streamable HTTP transport",
        ge=1024,  # Avoid privileged ports
        le=65535,
    )

    # === Security Configuration ===

    # API keys for external services (if needed)
    # MCP servers often integrate with external APIs
    external_api_key: str | None = Field(
        default=None,
        description="API key for external book data services",
        # Sensitive data - loaded from environment only
        repr=False,  # Hide from string representation
    )

    # === Performance Configuration ===

    max_concurrent_operations: int = Field(
        default=10,
        description="Maximum concurrent tool operations",
        ge=1,
        le=100,
    )

    resource_cache_ttl: int = Field(
        default=300,  # 5 minutes
        description="Resource cache time-to-live in seconds",
        ge=0,
    )

    # === Development Configuration ===

    debug: bool = Field(
        default=False,
        description="Enable debug logging for protocol messages",
    )

    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR)",
        pattern=r"^(DEBUG|INFO|WARNING|ERROR)$",
    )

    # === MCP Feature Flags ===
    # These control which MCP capabilities are exposed

    enable_sampling: bool = Field(
        default=True,
        description="Enable LLM sampling capability",
    )

    enable_subscriptions: bool = Field(
        default=True,
        description="Enable resource subscriptions",
    )

    enable_progress_notifications: bool = Field(
        default=True,
        description="Enable progress tracking for long operations",
    )

    # === Validation Methods ===

    @field_validator("database_path")
    @classmethod
    def validate_database_path(cls, v: Path) -> Path:
        """Ensure database directory exists and is writable.

        MCP servers need reliable data persistence.
        This validator ensures we can create/access the database.
        """
        # Convert to absolute path for clarity
        abs_path = v.absolute()

        # Ensure parent directory exists
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        # Check write permissions on parent directory
        if not abs_path.parent.is_dir():
            raise ValueError(f"Database directory {abs_path.parent} is not accessible")

        return abs_path

    @field_validator("server_name")
    @classmethod
    def validate_server_name(cls, v: str) -> str:
        """Validate server name meets MCP naming conventions.

        MCP clients use server names for identification and routing.
        Names should be URL-safe and human-readable.
        """
        if len(v) < 3:
            raise ValueError("Server name must be at least 3 characters")
        if len(v) > 50:
            raise ValueError("Server name must not exceed 50 characters")
        return v

    @field_validator("http_port")
    @classmethod
    def validate_http_port(cls, v: int) -> int:
        """Ensure HTTP port is available for binding.

        For production MCP servers, you'd want to check
        if the port is actually available.
        """
        # Reserved ports that should be avoided
        reserved_ports = {22, 25, 80, 443, 3306, 5432}
        if v in reserved_ports:
            raise ValueError(f"Port {v} is commonly reserved, choose another")
        return v

    # === Computed Properties ===

    @property
    def is_development(self) -> bool:
        """Check if running in development mode.

        Useful for enabling development-specific features
        like detailed error messages or test data.
        """
        return self.debug or self.log_level == "DEBUG"

    @property
    def server_info(self) -> dict[str, str]:
        """Get server information for MCP handshake.

        This is sent during the initialization phase
        of the MCP protocol.
        """
        return {
            "name": self.server_name,
            "version": self.server_version,
            "transport": self.transport,
        }

    @property
    def capabilities(self) -> dict[str, bool]:
        """Get enabled MCP capabilities.

        Used during capability negotiation with clients.
        """
        return {
            "sampling": self.enable_sampling,
            "subscriptions": self.enable_subscriptions,
            "progressNotifications": self.enable_progress_notifications,
        }

    def get_database_url(self) -> str:
        """Get SQLAlchemy database URL.

        Demonstrates how MCP servers integrate with
        persistence layers.
        """
        return f"sqlite:///{self.database_path}"


# === Global Configuration Instance ===
# This pattern allows easy access throughout the MCP server


class _ConfigStore:
    """Internal storage for configuration singleton."""

    _instance: ServerConfig | None = None


def get_config() -> ServerConfig:
    """Get or create the global configuration instance.

    This singleton pattern ensures consistent configuration
    across all MCP server components.
    """
    if _ConfigStore._instance is None:  # type: ignore[reportPrivateUsage]
        _ConfigStore._instance = ServerConfig()  # type: ignore[reportPrivateUsage]
    return _ConfigStore._instance  # type: ignore[reportPrivateUsage]


def reset_config() -> None:
    """Reset configuration (useful for testing).

    Allows tests to use different configurations
    without affecting other tests.
    """
    _ConfigStore._instance = None  # type: ignore[reportPrivateUsage]
