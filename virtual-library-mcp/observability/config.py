"""Configuration for Logfire observability."""

import os

from pydantic import BaseModel, Field


class ObservabilityConfig(BaseModel):
    """Configuration for Logfire observability."""

    # Connection
    token: str = Field(default_factory=lambda: os.getenv("LOGFIRE_TOKEN", ""))
    project_name: str = "virtual-library-mcp"
    environment: str = Field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))

    # Behavior
    enabled: bool = Field(
        default_factory=lambda: os.getenv("LOGFIRE_ENABLED", "true").lower() == "true"
    )
    console_output: bool = Field(
        default_factory=lambda: os.getenv("LOGFIRE_CONSOLE", "false").lower() == "true"
    )
    send_to_logfire: bool = Field(
        default_factory=lambda: os.getenv("LOGFIRE_SEND", "true").lower() == "true"
    )

    sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)

    max_span_attributes: int = 50
    max_attribute_length: int = 1000

    debug_mode: bool = Field(
        default_factory=lambda: os.getenv("LOGFIRE_DEBUG", "false").lower() == "true"
    )


class ProductionConfig(ObservabilityConfig):
    """Production-specific configuration."""

    sample_rate: float = 1.0
    console_output: bool = False
    send_to_logfire: bool = True
    max_span_attributes: int = 30


class DevelopmentConfig(ObservabilityConfig):
    """Development-specific configuration."""

    sample_rate: float = 1.0  # Sample everything
    console_output: bool = True
    send_to_logfire: bool = False  # Default to False in dev (no token required)
    debug_mode: bool = True


def get_environment_config() -> ObservabilityConfig:
    """Get configuration based on environment."""
    env = os.getenv("ENVIRONMENT", "development")

    if env == "production":
        return ProductionConfig()
    if env == "development":
        return DevelopmentConfig()
    return ObservabilityConfig()
