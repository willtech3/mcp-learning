"""OAuth 2.1 authentication for the Virtual Library MCP Server.

MCP authorization (2025-11-25 spec) in one paragraph: the MCP server is an
OAuth 2.0 **Protected Resource**. It advertises RFC 9728 Protected Resource
Metadata at /.well-known/oauth-protected-resource pointing clients at an
authorization server. Clients register (dynamically, or via Client ID
Metadata Documents per SEP-991), run an Authorization Code + PKCE flow
(S256 — mandatory in OAuth 2.1), and present bearer tokens on every HTTP
request. The server validates each token and its scopes before serving.

This server uses FastMCP's GoogleProvider, an **OAuth Proxy**: toward MCP
clients it speaks the full spec-compliant flow above; upstream it bridges
to Google's fixed-credential OAuth (Google issues no dynamic clients).
Users therefore sign in with real Google accounts, and the deployment
needs exactly one Google OAuth client.

Security posture implemented here:
- PKCE (S256) enforced by the provider for every client
- Tokens are validated server-side on every request; scopes checked
- Authorization consent screen enabled (require_authorization_consent)
- Client ID Metadata Documents enabled (enable_cimd, SEP-991)
- HTTPS required for the public base URL (config validator)
- The HTTP transport refuses to start unauthenticated unless explicitly
  opted out via VIRTUAL_LIBRARY_ALLOW_INSECURE_HTTP (dev only)
"""

import logging

from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AuthProvider
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware, MiddlewareContext

from config import ServerConfig

logger = logging.getLogger(__name__)


class EmailAllowlistMiddleware(Middleware):
    """Authorization layer on top of authentication.

    Google sign-in proves WHO the caller is (authentication); this
    middleware decides whether that identity may use the server at all
    (authorization). Without it, "authenticated" means "anyone with a
    Google account" — fine for a public demo catalog, wrong for anything
    holding real data. Applied only when an allowlist is configured.
    """

    def __init__(self, allowed_emails: list[str]):
        self.allowed = {email.strip().lower() for email in allowed_emails if email.strip()}

    async def on_request(self, context: MiddlewareContext, call_next):
        token = get_access_token()
        email = (token.claims.get("email") or "").lower() if token else ""
        if email not in self.allowed:
            logger.warning("Authorization denied for %s", email or "<no email claim>")
            raise ToolError("This account is not authorized to use this server.")
        return await call_next(context)


def build_auth_provider(config: ServerConfig) -> AuthProvider | None:
    """Construct the OAuth provider from configuration, or None when disabled.

    Returns None for stdio transport and for explicitly-insecure local HTTP.
    The decision to refuse unauthenticated HTTP lives in server.main(), not
    here — this factory only reflects configuration.
    """
    if not config.auth_enabled:
        return None

    # The config model validator guarantees these are present.
    assert config.base_url is not None
    assert config.google_client_id is not None
    assert config.google_client_secret is not None

    logger.info("OAuth 2.1 enabled: Google identity, base_url=%s", config.base_url)
    return GoogleProvider(
        client_id=config.google_client_id,
        client_secret=config.google_client_secret,
        base_url=config.base_url,
        required_scopes=config.auth_required_scopes,
        # Defaults kept explicit for the reader:
        require_authorization_consent=True,  # user sees a consent page
        enable_cimd=True,  # SEP-991 client registration via metadata documents
    )
