"""Configuration management for Virtual Library MCP Server.

This module demonstrates MCP best practices for configuration:
1. Protocol Metadata - Required for server identification
2. Transport Configuration - Extensible for multiple transports
3. Security - Environment-based secrets management
4. Validation - Type-safe configuration with Pydantic v2
"""

from pathlib import Path

from pydantic import Field, field_validator, model_validator
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
        description=(
            "Transport: 'stdio' (legacy initialize-era protocol via FastMCP), "
            "'stdio-modern' (MCP 2026-07-28 stateless protocol, modern/ package), "
            "or 'http' (Streamable HTTP serving BOTH eras on one endpoint)"
        ),
        pattern=r"^(stdio|stdio-modern|http|streamable_http)$",
    )

    # Streamable HTTP configuration
    http_host: str = Field(
        default="127.0.0.1",  # localhost-only by default; 0.0.0.0 only in containers
        description="HTTP server bind host for Streamable HTTP transport",
    )

    http_port: int = Field(
        default=8080,
        description="HTTP server port for Streamable HTTP transport",
        ge=1024,  # Avoid privileged ports
        le=65535,
    )

    http_path: str = Field(
        default="/mcp",
        description="URL path where the MCP endpoint is mounted",
        pattern=r"^/[a-zA-Z0-9/_-]*$",
    )

    # === Authentication (OAuth 2.1, MCP 2025-11-25 authorization spec) ===
    # The server acts as an OAuth Protected Resource. FastMCP's GoogleProvider
    # implements the OAuth Proxy pattern: spec-compliant PRM metadata, dynamic
    # client registration, and PKCE toward MCP clients, bridged to Google's
    # fixed-credential OAuth upstream.

    auth_enabled: bool = Field(
        default=False,
        description="Require OAuth 2.1 bearer tokens on the HTTP transport",
    )

    base_url: str | None = Field(
        default=None,
        description=(
            "Public URL of this server (e.g. https://library.example.run.app). "
            "Required when auth is enabled; used for OAuth metadata and callbacks."
        ),
    )

    google_client_id: str | None = Field(
        default=None,
        description="Google OAuth client ID (from Google Cloud Console)",
    )

    google_client_secret: str | None = Field(
        default=None,
        description="Google OAuth client secret",
        repr=False,  # never appears in logs or repr
    )

    auth_required_scopes: list[str] = Field(
        default=["openid", "https://www.googleapis.com/auth/userinfo.email"],
        description="OAuth scopes every client token must carry",
    )

    auth_allowed_emails: list[str] = Field(
        default=[],
        description=(
            "Authorization allowlist: Google account emails permitted to use "
            "this server. Empty list = any authenticated Google account "
            "(authentication only, no authorization). For personal deployments, "
            "set this to your own address(es)."
        ),
    )

    allow_insecure_http: bool = Field(
        default=False,
        description=(
            "Explicitly allow running the HTTP transport WITHOUT authentication. "
            "Local development only - never enable in production."
        ),
    )

    # === MCP 2026-07-28 (modern era) Configuration ===
    # The modern/ package implements the stateless 2026-07-28 revision from
    # scratch (SEP-2575). These settings apply only to the modern protocol
    # path; the legacy (initialize-era) FastMCP path keeps the Google OAuth
    # settings above.

    modern_auth_enabled: bool = Field(
        default=False,
        description=(
            "Require OAuth 2.1 bearer tokens on the MODERN (2026-07-28) HTTP "
            "path. The server then acts as an RFC 9728 protected resource: "
            "PRM metadata, WWW-Authenticate challenges, JWT audience "
            "validation (RFC 8707)."
        ),
    )

    demo_as_enabled: bool = Field(
        default=False,
        description=(
            "Mount the EDUCATIONAL built-in authorization server under /auth "
            "(RFC 8414 metadata, PKCE S256, resource indicators, RFC 9207 iss, "
            "CIMD + deprecated-DCR registration). Never use in production; it "
            "exists so the whole draft auth model runs locally end to end."
        ),
    )

    demo_as_auto_approve: bool = Field(
        default=True,
        description=(
            "Demo AS skips the consent page and immediately redirects with a "
            "code (headless demos/tests). Set false to see the consent step."
        ),
    )

    request_state_secret: str | None = Field(
        default=None,
        description=(
            "HMAC secret protecting MRTR requestState blobs (SEP-2322). The "
            "spec REQUIRES integrity protection because requestState transits "
            "the client. Unset = random per-process secret (fine for a single "
            "instance; multi-instance deployments need a shared secret)."
        ),
        repr=False,  # never appears in logs or repr
    )

    modern_cache_ttl_ms: int = Field(
        default=300_000,  # 5 minutes, matches resource_cache_ttl
        description=(
            "ttlMs freshness hint on CacheableResult list/read responses "
            "(SEP-2549). 0 = immediately stale."
        ),
        ge=0,
    )

    allowed_origins: list[str] = Field(
        default=[],
        description=(
            "Extra Origin header values accepted on the HTTP transport. "
            "Localhost origins are always accepted. Origin validation is a "
            "MUST in the 2026-07-28 Streamable HTTP binding (DNS-rebinding "
            "protection); unknown origins get 403."
        ),
    )

    @property
    def canonical_url(self) -> str:
        """Canonical URI of the MCP endpoint (RFC 8707 resource identity).

        This exact string is the OAuth resource indicator, the PRM
        `resource` value, and the JWT audience the modern bearer verifier
        demands — audience binding only works if everyone agrees on one
        canonical form (lowercase scheme/host, no trailing slash).
        """
        base = self.base_url or f"http://{self.http_host}:{self.http_port}"
        return f"{base}{self.http_path}"

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

    @field_validator("transport")
    @classmethod
    def normalize_transport(cls, v: str) -> str:
        """Accept the legacy 'streamable_http' spelling but store 'http'."""
        return "http" if v == "streamable_http" else v

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str | None) -> str | None:
        """OAuth metadata URLs must be HTTPS except for local development.

        OAuth 2.1 requires TLS for every endpoint involved in the flow;
        the localhost exception exists only for development loops.
        """
        if v is None:
            return v
        v = v.rstrip("/")
        is_local = v.startswith(("http://localhost", "http://127.0.0.1"))
        if not v.startswith("https://") and not is_local:
            raise ValueError("base_url must use https:// (http:// allowed only for localhost)")
        return v

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> "ServerConfig":
        """Auth requires complete OAuth configuration before startup."""
        if self.auth_enabled:
            missing = [
                name
                for name, value in (
                    ("VIRTUAL_LIBRARY_BASE_URL", self.base_url),
                    ("VIRTUAL_LIBRARY_GOOGLE_CLIENT_ID", self.google_client_id),
                    ("VIRTUAL_LIBRARY_GOOGLE_CLIENT_SECRET", self.google_client_secret),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    f"auth_enabled=true but missing required settings: {', '.join(missing)}"
                )
        if self.modern_auth_enabled and not self.demo_as_enabled:
            # The modern resource-server path validates JWTs against an
            # authorization server's JWKS. This educational build bundles its
            # own AS; pointing at an external AS would need issuer + JWKS
            # settings that we deliberately keep out of scope (deployment).
            raise ValueError(
                "modern_auth_enabled=true requires demo_as_enabled=true "
                "(the educational build validates tokens from its built-in "
                "authorization server)"
            )
        return self

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
