#!/usr/bin/env python3
"""Demonstration of MCP server configuration usage.

This script shows how MCP servers use configuration for:
1. Protocol compliance
2. Transport selection
3. Capability negotiation
4. Security management
"""

import json

# Add parent directory to path for imports
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from virtual_library_mcp.config import ServerConfig, get_config


def demonstrate_configuration():
    """Show how MCP servers use configuration."""

    print("=== MCP Server Configuration Demo ===\n")

    # 1. Default Configuration
    print("1. Default Configuration:")
    config = get_config()
    print(f"   Server: {config.server_name} v{config.server_version}")
    print(f"   Transport: {config.transport}")
    print(f"   Database: {config.database_path}")
    print(f"   Debug Mode: {config.debug}")
    print()

    # 2. MCP Protocol Information
    print("2. MCP Protocol Handshake Information:")
    print(f"   Server Info: {json.dumps(config.server_info, indent=6)}")
    print()

    # 3. MCP Capabilities
    print("3. MCP Capabilities (for client negotiation):")
    for capability, enabled in config.capabilities.items():
        status = "✓ Enabled" if enabled else "✗ Disabled"
        print(f"   {capability}: {status}")
    print()

    # 4. Transport Configuration
    print("4. Transport Configuration:")
    if config.transport == "stdio":
        print("   Using stdio transport (process communication)")
        print("   Perfect for: CLI tools, local development")
    elif config.transport == "streamable_http":
        print(f"   Using Streamable HTTP on {config.http_host}:{config.http_port}")
        print("   Perfect for: Web clients, remote access, optional streaming")
    print()

    # 5. Security Configuration
    print("5. Security Configuration:")
    if config.external_api_key:
        # Never print actual keys!
        print("   External API Key: ***CONFIGURED***")
    else:
        print("   External API Key: Not configured")
    print(f"   Max Concurrent Operations: {config.max_concurrent_operations}")
    print()

    # 6. Development vs Production
    print("6. Environment Detection:")
    if config.is_development:
        print("   Running in DEVELOPMENT mode")
        print("   - Detailed error messages enabled")
        print("   - Debug logging active")
        print("   - Test data available")
    else:
        print("   Running in PRODUCTION mode")
        print("   - Optimized for performance")
        print("   - Security hardened")
        print("   - Minimal logging")
    print()

    # 7. Configuration Validation Example
    print("7. Configuration Validation:")
    try:
        # This would fail validation
        ServerConfig(
            server_name="Invalid Name!",  # Contains invalid characters
            server_version="1.0",  # Invalid version format
            http_port=80,  # Reserved port
        )
    except Exception as e:
        print("   Validation prevented invalid configuration:")
        print(f"   {type(e).__name__}: {str(e)[:60]}...")
    print()

    # 8. Database Configuration
    print("8. Database Configuration:")
    print(f"   SQLAlchemy URL: {config.get_database_url()}")
    print(f"   Parent directory exists: {config.database_path.parent.exists()}")
    print()


def demonstrate_environment_override():
    """Show how environment variables override defaults."""

    print("\n=== Environment Variable Override Demo ===\n")

    import os

    # Simulate environment variables
    os.environ["VIRTUAL_LIBRARY_SERVER_NAME"] = "demo-library"
    os.environ["VIRTUAL_LIBRARY_DEBUG"] = "true"
    os.environ["VIRTUAL_LIBRARY_LOG_LEVEL"] = "DEBUG"
    os.environ["VIRTUAL_LIBRARY_ENABLE_SAMPLING"] = "false"

    # Create new config (bypassing singleton for demo)
    config = ServerConfig()

    print("Environment variables set:")
    print("   VIRTUAL_LIBRARY_SERVER_NAME=demo-library")
    print("   VIRTUAL_LIBRARY_DEBUG=true")
    print("   VIRTUAL_LIBRARY_LOG_LEVEL=DEBUG")
    print("   VIRTUAL_LIBRARY_ENABLE_SAMPLING=false")
    print()

    print("Resulting configuration:")
    print(f"   Server Name: {config.server_name} (overridden)")
    print(f"   Debug: {config.debug} (overridden)")
    print(f"   Log Level: {config.log_level} (overridden)")
    print(f"   Sampling: {config.enable_sampling} (overridden)")
    print(f"   Subscriptions: {config.enable_subscriptions} (default)")

    # Clean up
    for key in [
        "VIRTUAL_LIBRARY_SERVER_NAME",
        "VIRTUAL_LIBRARY_DEBUG",
        "VIRTUAL_LIBRARY_LOG_LEVEL",
        "VIRTUAL_LIBRARY_ENABLE_SAMPLING",
    ]:
        os.environ.pop(key, None)


def demonstrate_mcp_use_cases():
    """Show real-world MCP configuration scenarios."""

    print("\n=== MCP Configuration Use Cases ===\n")

    # Use Case 1: Local CLI Tool
    print("1. Local CLI Tool Configuration:")
    local_config = ServerConfig(
        transport="stdio",
        debug=True,
        log_level="DEBUG",
    )
    print(f"   Transport: {local_config.transport}")
    print(f"   Debug logging for protocol messages: {local_config.debug}")
    print("   Use case: Claude Desktop, VS Code Extension")
    print()

    # Use Case 2: Web Service
    print("2. Web Service Configuration:")
    web_config = ServerConfig(
        transport="streamable_http",
        http_host="0.0.0.0",  # Listen on all interfaces
        http_port=8080,
        enable_subscriptions=True,
        resource_cache_ttl=600,  # 10 minute cache
    )
    print(f"   Transport: {web_config.transport}")
    print(f"   Endpoint: http://{web_config.http_host}:{web_config.http_port}")
    print(f"   Caching: {web_config.resource_cache_ttl}s TTL")
    print("   Use case: Web-based MCP clients, remote access")
    print()

    # Use Case 3: High-Performance Server
    print("3. High-Performance Configuration:")
    perf_config = ServerConfig(
        max_concurrent_operations=50,
        resource_cache_ttl=1800,  # 30 minute cache
        debug=False,
        log_level="WARNING",
    )
    print(f"   Max concurrent operations: {perf_config.max_concurrent_operations}")
    print(f"   Aggressive caching: {perf_config.resource_cache_ttl}s")
    print(f"   Minimal logging: {perf_config.log_level}")
    print("   Use case: Production deployments")


if __name__ == "__main__":
    demonstrate_configuration()
    demonstrate_environment_override()
    demonstrate_mcp_use_cases()

    print("\n✅ Configuration system ready for MCP server implementation!")
