"""Logfire observability for Virtual Library MCP Server."""


import logfire

from .config import ObservabilityConfig

_config: ObservabilityConfig | None = None


def initialize_observability(config: ObservabilityConfig | None = None):
    """Initialize Logfire with configuration."""
    global _config
    _config = config or ObservabilityConfig()

    if not _config.enabled:
        return

    logfire.configure(
        token=_config.token,
        project_name=_config.project_name,
        environment=_config.environment,
        send_to_logfire=_config.send_to_logfire,
        console=_config.console_output,
        console_colors="auto",
        console_include_timestamp=True,
        console_verbose=_config.debug_mode,
    )

    # Optionally instrument system metrics
    if _config.environment == "production":
        logfire.instrument_system_metrics()


def get_config() -> ObservabilityConfig:
    """Get current observability configuration."""
    global _config
    if _config is None:
        _config = ObservabilityConfig()
    return _config


__all__ = ["ObservabilityConfig", "get_config", "initialize_observability"]
