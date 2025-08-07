"""Logfire observability for Virtual Library MCP Server."""

import logging
from typing import Any

from .config import ObservabilityConfig

logger = logging.getLogger(__name__)

# Try to import logfire, but gracefully handle if not available
try:
    import logfire

    LOGFIRE_AVAILABLE = True
except ImportError:
    LOGFIRE_AVAILABLE = False
    logger.info("Logfire not available - observability disabled. Install with: pip install logfire")

    # Create a mock logfire module for graceful degradation
    class MockLogfire:
        """Mock logfire for when the library is not installed."""

        def configure(self, **kwargs):
            """No-op configure method."""

        def instrument_system_metrics(self):
            """No-op system metrics method."""

        def span(self, name: str, **kwargs):  # noqa: ARG002
            """No-op context manager for spans."""
            return MockSpan()

        def metric_counter(self, name: str, **kwargs):  # noqa: ARG002
            """No-op metric counter."""
            return MockMetric()

        def metric_histogram(self, name: str, **kwargs):  # noqa: ARG002
            """No-op metric histogram."""
            return MockMetric()

        def metric_gauge(self, name: str, **kwargs):  # noqa: ARG002
            """No-op metric gauge."""
            return MockMetric()

    class MockSpan:
        """Mock span context manager."""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def set_attribute(self, key: str, value: Any):
            """No-op set attribute."""

    class MockMetric:
        """Mock metric object."""

        def add(self, value: float, attributes: dict[str, Any] | None = None):
            """No-op add method."""

        def set(self, value: float, attributes: dict[str, Any] | None = None):
            """No-op set method."""

    # Replace logfire with mock
    logfire = MockLogfire()

_config: ObservabilityConfig | None = None


def initialize_observability(config: ObservabilityConfig | None = None):
    """Initialize Logfire with configuration."""
    global _config  # noqa: PLW0603
    _config = config or ObservabilityConfig()

    if not _config.enabled:
        logger.debug("Observability disabled via configuration")
        return

    if not LOGFIRE_AVAILABLE:
        logger.warning(
            "Logfire library not installed. Observability features will be disabled. "
            "To enable, install with: pip install logfire"
        )
        return

    # Configure logfire with appropriate parameters
    # Note: console_colors, console_include_timestamp, and console_verbose
    # are not direct parameters, they're part of ConsoleOptions
    logfire.configure(
        token=_config.token,
        environment=_config.environment,
        send_to_logfire=_config.send_to_logfire,
        console=_config.console_output,
    )

    # Optionally instrument system metrics
    if _config.environment == "production":
        logfire.instrument_system_metrics()


def get_config() -> ObservabilityConfig:
    """Get current observability configuration."""
    global _config  # noqa: PLW0603
    if _config is None:
        _config = ObservabilityConfig()
    return _config


__all__ = [
    "LOGFIRE_AVAILABLE",
    "ObservabilityConfig",
    "get_config",
    "initialize_observability",
    "logfire",
]
