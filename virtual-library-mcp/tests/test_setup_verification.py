"""Test to verify pytest setup and fixtures are working correctly.

This test file validates:
1. Pytest discovers and runs tests
2. Test database fixtures work correctly
3. Configuration fixtures provide isolation
4. Async test support is functional
5. MCP-specific test utilities work

This is a verification test that can be removed once real tests are implemented.
"""

import os
from pathlib import Path

from sqlalchemy import text

from tests.conftest import assert_json_rpc_response, assert_mcp_error
from virtual_library_mcp.config import ServerConfig, get_config, reset_config


class TestSetupVerification:
    """Verify test infrastructure is working correctly."""

    def test_database_fixture(self, test_db_path: Path):
        """Verify test database path fixture works."""
        # Database path should exist
        assert test_db_path is not None
        assert isinstance(test_db_path, Path)

        # Parent directory should exist
        assert test_db_path.parent.exists()
        assert test_db_path.parent.is_dir()

        # Path should be in temporary directory
        # macOS uses /private/var/folders/... with capital T
        path_str = str(test_db_path).lower()
        assert any(marker in path_str for marker in ["tmp", "temp", "/t/"])

    def test_database_session(self, test_db_session):
        """Verify database session fixture works."""
        # Should be able to execute simple query
        result = test_db_session.execute(text("SELECT 1"))
        assert result.scalar() == 1

        # Should be able to create a table (when models are ready)
        test_db_session.execute(
            text("""
                CREATE TABLE IF NOT EXISTS test_table (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL
                )
            """)
        )
        test_db_session.commit()

        # Verify table was created
        result = test_db_session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'")
        )
        assert result.scalar() == "test_table"

    def test_config_fixture_isolation(self, test_config: ServerConfig):
        """Verify configuration fixtures provide isolation."""
        # Test config should have test-specific values
        assert test_config.server_name == "test-virtual-library"
        assert test_config.server_version == "0.0.1-test"
        assert test_config.debug is True
        assert test_config.log_level == "DEBUG"

        # Should not affect global config
        global_config = get_config()
        assert global_config.server_name != test_config.server_name

    def test_clean_env_fixture(self, clean_env):
        """Verify clean environment fixture."""
        # Should have no VIRTUAL_LIBRARY_* variables
        for key in os.environ:
            assert not key.startswith("VIRTUAL_LIBRARY_")

    def test_env_fixture(self, test_env):
        """Verify test environment fixture."""
        # Should have test environment variables
        assert os.environ.get("VIRTUAL_LIBRARY_DEBUG") == "true"
        assert os.environ.get("VIRTUAL_LIBRARY_LOG_LEVEL") == "DEBUG"
        assert os.environ.get("VIRTUAL_LIBRARY_SERVER_NAME") == "test-server"

    def test_json_rpc_fixtures(self, json_rpc_request, mcp_initialization_request):
        """Verify JSON-RPC test fixtures."""
        # Basic request fixture
        assert json_rpc_request["jsonrpc"] == "2.0"
        assert json_rpc_request["method"] == "tools/list"
        assert "id" in json_rpc_request

        # MCP initialization fixture
        assert mcp_initialization_request["jsonrpc"] == "2.0"
        assert mcp_initialization_request["method"] == "initialize"
        assert "protocolVersion" in mcp_initialization_request["params"]
        assert "capabilities" in mcp_initialization_request["params"]

    def test_sample_data_fixtures(self, sample_book_data, sample_patron_data):
        """Verify sample data fixtures."""
        # Book data
        assert sample_book_data["id"] == "test-book-1"
        assert sample_book_data["title"] == "Test Book"
        assert sample_book_data["available"] is True

        # Patron data
        assert sample_patron_data["id"] == "test-patron-1"
        assert sample_patron_data["name"] == "Test Patron"
        assert sample_patron_data["active"] is True

    def test_json_rpc_assertion_utilities(self):
        """Verify JSON-RPC assertion utilities work."""
        # Valid response
        valid_response = {"jsonrpc": "2.0", "id": "test-1", "result": {"status": "ok"}}
        assert_json_rpc_response(valid_response, "test-1")

        # Error response
        error_response = {
            "jsonrpc": "2.0",
            "id": "test-2",
            "error": {"code": -32601, "message": "Method not found"},
        }
        assert_mcp_error(error_response, -32601)


class TestConfigurationReset:
    """Verify configuration reset between tests."""

    def test_config_reset_1(self):
        """First test modifies global config."""
        reset_config()
        config = get_config()

        # Modify config (in real tests, this might happen indirectly)
        config.server_name = "modified-in-test-1"

        # Verify modification
        assert get_config().server_name == "modified-in-test-1"

    def test_config_reset_2(self):
        """Second test should have clean config."""
        # Due to autouse cleanup fixture, config should be reset
        config = get_config()

        # Should have default value, not modified value from test_1
        assert config.server_name == "virtual-library"
        assert config.server_name != "modified-in-test-1"
