"""Tests for OAuth 2.1 configuration and wiring.

These don't talk to Google — they verify the parts we own: configuration
validation (fail closed), provider construction, and that the OAuth
discovery endpoints required by the MCP 2025-11-25 authorization spec
are actually mounted on the HTTP app.
"""

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.server.auth.providers.google import GoogleProvider
from pydantic import ValidationError

from auth import build_auth_provider
from config import ServerConfig

FAKE_AUTH = {
    "auth_enabled": True,
    "base_url": "https://library.example.app",
    "google_client_id": "1234567890.apps.googleusercontent.com",
    "google_client_secret": "GOCSPX-test-secret",
}


def _config(**overrides) -> ServerConfig:
    return ServerConfig(_env_file=None, **overrides)


class TestAuthConfiguration:
    def test_auth_disabled_needs_nothing(self, clean_env):
        config = _config()
        assert config.auth_enabled is False
        assert build_auth_provider(config) is None

    def test_auth_enabled_requires_credentials(self, clean_env):
        with pytest.raises(ValidationError, match="missing required settings"):
            _config(auth_enabled=True)

    def test_auth_enabled_names_each_missing_setting(self, clean_env):
        with pytest.raises(ValidationError, match="GOOGLE_CLIENT_SECRET"):
            _config(
                auth_enabled=True,
                base_url="https://library.example.app",
                google_client_id="x.apps.googleusercontent.com",
            )

    def test_base_url_must_be_https(self, clean_env):
        with pytest.raises(ValidationError, match="https"):
            _config(base_url="http://library.example.app")

    def test_localhost_http_base_url_allowed_for_dev(self, clean_env):
        config = _config(base_url="http://localhost:8080")
        assert config.base_url == "http://localhost:8080"

    def test_base_url_trailing_slash_stripped(self, clean_env):
        config = _config(base_url="https://library.example.app/")
        assert config.base_url == "https://library.example.app"

    def test_secret_never_appears_in_repr(self, clean_env):
        config = _config(**FAKE_AUTH)
        assert "GOCSPX-test-secret" not in repr(config)

    def test_legacy_transport_spelling_normalized(self, clean_env):
        config = _config(transport="streamable_http")
        assert config.transport == "http"


class TestProviderConstruction:
    def test_full_config_builds_google_provider(self, clean_env):
        provider = build_auth_provider(_config(**FAKE_AUTH))
        assert isinstance(provider, GoogleProvider)

    def test_provider_uses_configured_base_url(self, clean_env):
        provider = build_auth_provider(_config(**FAKE_AUTH))
        assert str(provider.base_url).rstrip("/") == "https://library.example.app"


class TestOAuthDiscoveryEndpoints:
    """The 2025-11-25 authorization spec requires discoverable metadata."""

    @pytest.fixture
    def auth_app(self, clean_env):
        provider = build_auth_provider(_config(**FAKE_AUTH))
        mcp = FastMCP("auth-test", auth=provider)
        return mcp.http_app()

    async def test_protected_resource_metadata_served(self, auth_app):
        """RFC 9728: /.well-known/oauth-protected-resource must resolve."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=auth_app), base_url="https://library.example.app"
        ) as http:
            response = await http.get("/.well-known/oauth-protected-resource/mcp")
            assert response.status_code == 200
            body = response.json()
            assert "authorization_servers" in body

    async def test_authorization_server_metadata_served(self, auth_app):
        """RFC 8414 metadata advertises PKCE support (OAuth 2.1 requires S256)."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=auth_app), base_url="https://library.example.app"
        ) as http:
            response = await http.get("/.well-known/oauth-authorization-server")
            assert response.status_code == 200
            body = response.json()
            assert "S256" in body.get("code_challenge_methods_supported", [])

    async def test_mcp_endpoint_rejects_unauthenticated_requests(self, auth_app):
        """Bearer-token enforcement: no token -> 401 with WWW-Authenticate."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=auth_app), base_url="https://library.example.app"
        ) as http:
            response = await http.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={"Accept": "application/json, text/event-stream"},
            )
            assert response.status_code == 401
            assert "www-authenticate" in {k.lower() for k in response.headers}


class TestHealthEndpoint:
    async def test_health_route_is_public(self):
        """Liveness probes must work without tokens (and expose nothing)."""
        import server

        app = server.mcp.http_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            response = await http.get("/health")
            assert response.status_code == 200
            assert response.json()["status"] == "ok"


class TestEmailAllowlist:
    """Authorization on top of authentication: only listed accounts pass."""

    class _Token:
        def __init__(self, email):
            self.claims = {"email": email} if email else {}

    @pytest.fixture
    def middleware(self):
        from auth import EmailAllowlistMiddleware

        return EmailAllowlistMiddleware(["Owner@Example.com"])

    async def test_allowed_email_passes(self, middleware, monkeypatch):
        monkeypatch.setattr("auth.get_access_token", lambda: self._Token("owner@example.com"))

        async def call_next(_ctx):
            return "served"

        assert await middleware.on_request(None, call_next) == "served"

    async def test_unlisted_email_rejected(self, middleware, monkeypatch):
        from fastmcp.exceptions import ToolError

        monkeypatch.setattr("auth.get_access_token", lambda: self._Token("intruder@example.com"))

        async def call_next(_ctx):  # pragma: no cover - must not be reached
            raise AssertionError("request must not be served")

        with pytest.raises(ToolError, match="not authorized"):
            await middleware.on_request(None, call_next)

    async def test_missing_email_claim_rejected(self, middleware, monkeypatch):
        from fastmcp.exceptions import ToolError

        monkeypatch.setattr("auth.get_access_token", lambda: self._Token(None))

        async def call_next(_ctx):  # pragma: no cover
            raise AssertionError("request must not be served")

        with pytest.raises(ToolError, match="not authorized"):
            await middleware.on_request(None, call_next)
