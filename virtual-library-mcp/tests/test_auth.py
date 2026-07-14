"""Tests for OAuth 2.1 configuration and wiring.

These don't talk to Google — they verify the parts we own: configuration
validation (fail closed), provider construction, and that the OAuth
discovery endpoints required by the MCP 2025-11-25 authorization spec
are actually mounted on the HTTP app.
"""

import logging

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.server.auth.providers.google import GoogleProvider
from key_value.aio.stores.memory import MemoryStore
from pydantic import ValidationError

from auth import build_auth_provider, build_oauth_client_storage
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

    def test_provider_suppresses_sensitive_http_client_logs(self, clean_env, monkeypatch, caplog):
        """Dependency request logs must not expose bearer tokens in URLs or headers."""
        httpx_logger = logging.getLogger("httpx")
        httpcore_logger = logging.getLogger("httpcore")
        monkeypatch.setattr(httpx_logger, "level", logging.INFO)
        monkeypatch.setattr(httpcore_logger, "level", logging.DEBUG)
        fake_token = "fake-google-oauth-token-for-log-test"

        build_auth_provider(_config(**FAKE_AUTH))

        transport = httpx.MockTransport(lambda request: httpx.Response(200, request=request))
        with caplog.at_level(logging.DEBUG), httpx.Client(transport=transport) as client:
            client.get(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"access_token": fake_token},
            )

        assert httpx_logger.getEffectiveLevel() >= logging.WARNING
        assert httpcore_logger.getEffectiveLevel() >= logging.WARNING
        assert fake_token not in caplog.text

    def test_firestore_storage_is_encrypted_and_sanitized(self, clean_env, monkeypatch):
        calls = {}

        class StubFirestoreStore:
            def __init__(self, **kwargs):
                calls["firestore"] = kwargs

        class StubEncryptedStore:
            def __init__(self, **kwargs):
                calls["encryption"] = kwargs

        monkeypatch.setattr("auth.FirestoreStore", StubFirestoreStore)
        monkeypatch.setattr("auth.FernetEncryptionWrapper", StubEncryptedStore)

        config = _config(
            **FAKE_AUTH,
            legacy_oauth_firestore_project="library-project",
            legacy_oauth_jwt_signing_key="jwt-key",
            legacy_oauth_storage_encryption_key="storage-key",
        )
        storage = build_oauth_client_storage(config)

        assert isinstance(storage, StubEncryptedStore)
        assert calls["firestore"]["project"] == "library-project"
        assert calls["firestore"]["database"] == "(default)"
        assert calls["firestore"]["default_collection"] == "virtual-library-oauth"
        assert calls["firestore"]["key_sanitization_strategy"] is not None
        assert calls["firestore"]["collection_sanitization_strategy"] is not None
        assert calls["encryption"]["source_material"] == "storage-key"

    async def test_shared_storage_survives_provider_instance_change(self, clean_env):
        """A client registered on one instance must authorize on another."""
        shared_storage = MemoryStore()
        provider_kwargs = {
            "client_id": "google-client-id",
            "client_secret": "google-client-secret",
            "base_url": "https://library.example.app",
            "required_scopes": [
                "openid",
                "https://www.googleapis.com/auth/userinfo.email",
            ],
            "client_storage": shared_storage,
            "jwt_signing_key": "stable-test-signing-key",
        }
        registration_app = FastMCP(
            "registration-instance", auth=GoogleProvider(**provider_kwargs)
        ).http_app()
        authorization_app = FastMCP(
            "authorization-instance", auth=GoogleProvider(**provider_kwargs)
        ).http_app()
        redirect_uri = "https://chatgpt.com/connector/oauth/test"

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=registration_app),
            base_url="https://library.example.app",
        ) as registration_client:
            registered = await registration_client.post(
                "/register",
                json={
                    "client_name": "ChatGPT",
                    "redirect_uris": [redirect_uri],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "token_endpoint_auth_method": "client_secret_post",
                    "scope": "openid https://www.googleapis.com/auth/userinfo.email",
                },
            )

        assert registered.status_code == 201, registered.text
        client_id = registered.json()["client_id"]

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=authorization_app),
            base_url="https://library.example.app",
        ) as authorization_client:
            authorized = await authorization_client.get(
                "/authorize",
                params={
                    "response_type": "code",
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "scope": "openid https://www.googleapis.com/auth/userinfo.email",
                    "code_challenge": "x" * 43,
                    "code_challenge_method": "S256",
                    "resource": "https://library.example.app/mcp",
                },
            )

        assert authorized.status_code == 302
        assert authorized.headers["location"].startswith("https://library.example.app/consent?")
        assert "Client Not Registered" not in authorized.text


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
