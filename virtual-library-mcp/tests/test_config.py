"""Tests for MCP server configuration.

These tests demonstrate:
1. Configuration validation
2. Environment variable loading
3. Default value behavior
4. Security considerations
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from virtual_library_mcp.config import ServerConfig, get_config, reset_config


class TestServerConfig:
    """Test MCP server configuration behavior."""
    
    def test_default_configuration(self):
        """Test that default configuration meets MCP requirements."""
        config = ServerConfig()
        
        # Server metadata required by MCP protocol
        assert config.server_name == "virtual-library"
        assert config.server_version == "0.1.0"
        
        # Default transport is stdio (simplest for development)
        assert config.transport == "stdio"
        
        # Database path is relative by default
        assert config.database_path == Path("virtual_library.db").absolute()
        
        # Security: sensitive fields are None by default
        assert config.external_api_key is None
        
        # MCP capabilities enabled by default
        assert config.enable_sampling is True
        assert config.enable_subscriptions is True
        assert config.enable_progress_notifications is True
    
    def test_environment_variable_loading(self):
        """Test loading configuration from environment variables."""
        # MCP servers must handle environment-based configuration
        # for different deployment scenarios
        
        env_vars = {
            "VIRTUAL_LIBRARY_SERVER_NAME": "test-library",
            "VIRTUAL_LIBRARY_SERVER_VERSION": "2.0.0",
            "VIRTUAL_LIBRARY_DATABASE_PATH": "/tmp/test.db",
            "VIRTUAL_LIBRARY_DEBUG": "true",
            "VIRTUAL_LIBRARY_LOG_LEVEL": "DEBUG",
            "VIRTUAL_LIBRARY_EXTERNAL_API_KEY": "secret-key-123",
        }
        
        with patch.dict(os.environ, env_vars):
            config = ServerConfig()
            
            assert config.server_name == "test-library"
            assert config.server_version == "2.0.0"
            assert config.database_path == Path("/tmp/test.db")
            assert config.debug is True
            assert config.log_level == "DEBUG"
            assert config.external_api_key == "secret-key-123"
    
    def test_server_name_validation(self):
        """Test MCP server name validation rules."""
        # Valid names
        valid_names = ["mcp-server", "test-123", "virtual-library"]
        for name in valid_names:
            config = ServerConfig(server_name=name)
            assert config.server_name == name
        
        # Invalid names (MCP requires URL-safe names)
        invalid_names = [
            "MCP_Server",  # Uppercase not allowed
            "mcp server",  # Spaces not allowed
            "mcp@server",  # Special chars not allowed
            "ab",          # Too short
            "a" * 51,      # Too long
        ]
        
        for name in invalid_names:
            with pytest.raises(ValidationError):
                ServerConfig(server_name=name)
    
    def test_version_validation(self):
        """Test semantic versioning validation."""
        # Valid versions
        valid_versions = [
            "1.0.0",
            "0.1.0",
            "2.3.4",
            "1.0.0-alpha",
            "1.0.0-beta.1",
        ]
        
        for version in valid_versions:
            config = ServerConfig(server_version=version)
            assert config.server_version == version
        
        # Invalid versions
        invalid_versions = ["1.0", "v1.0.0", "1.0.0.0", "latest"]
        
        for version in invalid_versions:
            with pytest.raises(ValidationError):
                ServerConfig(server_version=version)
    
    def test_transport_validation(self):
        """Test transport mechanism validation."""
        # MCP supports multiple transports
        valid_transports = ["stdio", "streamable_http"]
        
        for transport in valid_transports:
            config = ServerConfig(transport=transport)
            assert config.transport == transport
        
        # Invalid transports
        with pytest.raises(ValidationError):
            ServerConfig(transport="http")  # Not a valid MCP transport
        with pytest.raises(ValidationError):
            ServerConfig(transport="sse")  # SSE is deprecated
        with pytest.raises(ValidationError):
            ServerConfig(transport="websocket")  # WebSocket is future transport
    
    def test_port_validation(self):
        """Test HTTP port validation for Streamable HTTP transport."""
        # Valid ports
        config = ServerConfig(http_port=8080)
        assert config.http_port == 8080
        
        # Reserved ports should be rejected
        reserved_ports = [22, 25, 80, 443]
        for port in reserved_ports:
            with pytest.raises(ValidationError, match="reserved"):
                ServerConfig(http_port=port)
        
        # Out of range ports
        with pytest.raises(ValidationError):
            ServerConfig(http_port=1023)  # Below minimum
        with pytest.raises(ValidationError):
            ServerConfig(http_port=65536)  # Above maximum
    
    def test_database_path_validation(self, tmp_path):
        """Test database path validation and directory creation."""
        # Test with temporary directory
        db_path = tmp_path / "subdir" / "test.db"
        config = ServerConfig(database_path=db_path)
        
        # Parent directory should be created
        assert db_path.parent.exists()
        assert db_path.parent.is_dir()
        
        # Path should be absolute
        assert config.database_path.is_absolute()
    
    def test_computed_properties(self):
        """Test computed configuration properties."""
        # Development mode detection
        config = ServerConfig(debug=False, log_level="INFO")
        assert config.is_development is False
        
        config = ServerConfig(debug=True, log_level="INFO")
        assert config.is_development is True
        
        config = ServerConfig(debug=False, log_level="DEBUG")
        assert config.is_development is True
        
        # Server info for MCP handshake
        config = ServerConfig()
        info = config.server_info
        assert info["name"] == "virtual-library"
        assert info["version"] == "0.1.0"
        assert info["transport"] == "stdio"
        
        # MCP capabilities
        capabilities = config.capabilities
        assert capabilities["sampling"] is True
        assert capabilities["subscriptions"] is True
        assert capabilities["progressNotifications"] is True
    
    def test_database_url_generation(self):
        """Test SQLAlchemy database URL generation."""
        config = ServerConfig(database_path="test.db")
        url = config.get_database_url()
        assert url.startswith("sqlite:///")
        assert "test.db" in url
    
    def test_sensitive_data_repr(self):
        """Test that sensitive data is hidden in string representation."""
        config = ServerConfig(external_api_key="secret-key")
        
        # The API key should not appear in the string representation
        config_str = repr(config)
        assert "secret-key" not in config_str
        
        # But the value should still be accessible
        assert config.external_api_key == "secret-key"
    
    def test_global_config_singleton(self):
        """Test global configuration singleton pattern."""
        # Reset to ensure clean state
        reset_config()
        
        # First call creates instance
        config1 = get_config()
        assert config1 is not None
        
        # Subsequent calls return same instance
        config2 = get_config()
        assert config1 is config2
        
        # Reset clears the singleton
        reset_config()
        config3 = get_config()
        assert config3 is not config1
    
    def test_extra_fields_allowed(self):
        """Test that extra fields are allowed for extensibility."""
        # MCP protocol may add new fields in future versions
        config = ServerConfig(
            custom_field="custom_value",
            future_capability=True,
        )
        
        # Extra fields should be preserved
        assert config.custom_field == "custom_value"  # type: ignore
        assert config.future_capability is True  # type: ignore
    
    def test_case_insensitive_env_vars(self):
        """Test case-insensitive environment variable handling."""
        # MCP servers should be forgiving with env var casing
        env_vars = {
            "virtual_library_server_name": "lower-case",
            "VIRTUAL_LIBRARY_DEBUG": "true",
            "Virtual_Library_Log_Level": "ERROR",
        }
        
        with patch.dict(os.environ, env_vars):
            config = ServerConfig()
            
            assert config.server_name == "lower-case"
            assert config.debug is True
            assert config.log_level == "ERROR"


class TestConfigurationScenarios:
    """Test real-world MCP configuration scenarios."""
    
    def test_development_configuration(self):
        """Test typical development configuration."""
        env_vars = {
            "VIRTUAL_LIBRARY_DEBUG": "true",
            "VIRTUAL_LIBRARY_LOG_LEVEL": "DEBUG",
            "VIRTUAL_LIBRARY_DATABASE_PATH": "./dev.db",
        }
        
        with patch.dict(os.environ, env_vars):
            config = ServerConfig()
            
            assert config.is_development is True
            assert config.debug is True
            assert config.log_level == "DEBUG"
    
    def test_production_configuration(self):
        """Test typical production configuration."""
        env_vars = {
            "VIRTUAL_LIBRARY_DEBUG": "false",
            "VIRTUAL_LIBRARY_LOG_LEVEL": "WARNING",
            "VIRTUAL_LIBRARY_DATABASE_PATH": "/var/lib/virtual-library/data.db",
            "VIRTUAL_LIBRARY_EXTERNAL_API_KEY": "prod-api-key",
            "VIRTUAL_LIBRARY_MAX_CONCURRENT_OPERATIONS": "50",
        }
        
        with patch.dict(os.environ, env_vars):
            config = ServerConfig()
            
            assert config.is_development is False
            assert config.debug is False
            assert config.log_level == "WARNING"
            assert config.max_concurrent_operations == 50
    
    def test_minimal_configuration(self):
        """Test that minimal configuration works for MCP."""
        # MCP servers should work with zero configuration
        config = ServerConfig()
        
        # All required fields have sensible defaults
        assert config.server_name
        assert config.server_version
        assert config.transport
        assert config.database_path
        
        # Server can provide required protocol information
        assert config.server_info
        assert config.capabilities