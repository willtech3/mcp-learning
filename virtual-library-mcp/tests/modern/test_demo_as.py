"""
Tests for modern/auth/demo_as.py — the educational OAuth 2.1 demo AS.

Everything runs over httpx's ASGITransport against a Starlette app mounting
the AS routes: no network, no browser — httpx plays both the MCP client
(register/token calls) and the user's browser (the authorize redirect).

Covered flows and MUSTs:

- RFC 8414 metadata advertising S256-only PKCE, RFC 9207 iss support, and
  CIMD support;
- the full authorization-code + PKCE + RFC 8707 resource flow, ending in an
  RS256 access token that the resource server's TokenVerifier accepts;
- RFC 9207: ``iss`` present on success AND error redirects;
- PKCE enforcement: missing challenge rejected, ``plain`` rejected, wrong
  verifier rejected at the token endpoint;
- single-use codes (reuse rejected) with 60 s expiry;
- audience binding end to end: a token authorized for another resource is
  rejected by this server's verifier;
- refresh-token grant with rotation (replayed refresh token rejected);
- deprecated-DCR fallback: registration without ``application_type``
  rejected with a teaching error citing SEP-837;
- CIMD via a stubbed fetcher: document client_id mismatch rejected,
  unregistered redirect_uri rejected, loopback port variance accepted
  (RFC 8252 §7.3);
- the optional consent-page mode (auto_approve=False).
"""

import base64
import hashlib
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from starlette.applications import Starlette

from modern.auth import InvalidTokenError, TokenVerifier, build_demo_auth
from modern.auth.demo_as import DemoAuthorizationServer

BASE_URL = "http://127.0.0.1:8080"
ISSUER = f"{BASE_URL}/auth"
CANONICAL = f"{BASE_URL}/mcp"
REDIRECT_URI = "http://127.0.0.1:3000/callback"
VERIFIER_STRING = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
STATE = "af0ifjsldkj"

CIMD_CLIENT_ID = "https://app.example.com/oauth/client-metadata.json"
CIMD_DOCUMENT: dict[str, Any] = {
    "client_id": CIMD_CLIENT_ID,
    "client_name": "Example MCP Client",
    "redirect_uris": [REDIRECT_URI, "http://localhost:3000/callback"],
    "grant_types": ["authorization_code"],
    "response_types": ["code"],
    "token_endpoint_auth_method": "none",
}


def s256(verifier: str) -> str:
    """PKCE S256 transform (RFC 7636 §4.2): unpadded base64url of SHA-256."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def make_client(demo_as: DemoAuthorizationServer) -> httpx.AsyncClient:
    app = Starlette(routes=demo_as.routes())
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL)


def authorize_params(client_id: str, **overrides: Any) -> dict[str, str]:
    """A fully valid authorization request; ``key=None`` drops a parameter."""
    params: dict[str, Any] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "state": STATE,
        "code_challenge": s256(VERIFIER_STRING),
        "code_challenge_method": "S256",
        "resource": CANONICAL,
        "scope": "library:read library:write",
    }
    params.update(overrides)
    return {k: v for k, v in params.items() if v is not None}


def redirect_query(response: httpx.Response) -> dict[str, str]:
    """Parse the query parameters out of an authorize redirect."""
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert location.startswith(REDIRECT_URI.rsplit("/", 1)[0])
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}


async def register_client(client: httpx.AsyncClient) -> str:
    """Register a native client through the deprecated-DCR fallback."""
    response = await client.post(
        "/auth/register",
        json={
            "client_name": "Test MCP Client",
            "redirect_uris": [REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_method": "none",
            # SEP-837: MUST be declared; this is a CLI-style native client.
            "application_type": "native",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["client_id"]


async def obtain_code(
    client: httpx.AsyncClient, client_id: str, **overrides: Any
) -> dict[str, str]:
    response = await client.get("/auth/authorize", params=authorize_params(client_id, **overrides))
    return redirect_query(response)


def token_request(client_id: str, code: str, **overrides: Any) -> dict[str, str]:
    data: dict[str, Any] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "code_verifier": VERIFIER_STRING,
        "resource": CANONICAL,
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


@pytest.fixture
def demo_as() -> DemoAuthorizationServer:
    return DemoAuthorizationServer(issuer=ISSUER)


@pytest.fixture
def verifier(demo_as: DemoAuthorizationServer) -> TokenVerifier:
    """A resource-server verifier trusting the demo AS's JWKS."""
    return TokenVerifier(issuer=ISSUER, audience=CANONICAL, jwks=demo_as.jwks())


# ---------------------------------------------------------------------------
# RFC 8414 metadata
# ---------------------------------------------------------------------------


class TestAuthorizationServerMetadata:
    async def test_metadata_document(self, demo_as):
        async with make_client(demo_as) as client:
            response = await client.get("/.well-known/oauth-authorization-server")

        assert response.status_code == 200
        body = response.json()
        # RFC 8414 §3.3: issuer in the doc must equal the issuer the URL was
        # built from — the client-side check needs this to be exact.
        assert body["issuer"] == ISSUER
        assert body["authorization_endpoint"] == f"{ISSUER}/authorize"
        assert body["token_endpoint"] == f"{ISSUER}/token"
        assert body["registration_endpoint"] == f"{ISSUER}/register"
        assert body["jwks_uri"] == f"{ISSUER}/jwks.json"
        # PKCE advertisement: absence would oblige clients to REFUSE.
        assert body["code_challenge_methods_supported"] == ["S256"]
        # RFC 9207 §2.3: emitting iss requires advertising it.
        assert body["authorization_response_iss_parameter_supported"] is True
        # CIMD is the draft's preferred registration mechanism.
        assert body["client_id_metadata_document_supported"] is True
        assert body["scopes_supported"] == ["library:read", "library:write"]

    async def test_metadata_also_served_at_path_inserted_form(self, demo_as):
        # RFC 8414 §3.1 path insertion for an issuer with a path component —
        # the FIRST url a spec-conformant client constructs.
        async with make_client(demo_as) as client:
            response = await client.get("/.well-known/oauth-authorization-server/auth")
        assert response.status_code == 200
        assert response.json()["issuer"] == ISSUER

    async def test_jwks_endpoint_serves_signing_key(self, demo_as):
        async with make_client(demo_as) as client:
            response = await client.get("/auth/jwks.json")
        keys = response.json()["keys"]
        assert len(keys) == 1
        assert keys[0]["kty"] == "RSA"
        assert keys[0]["alg"] == "RS256"
        assert keys[0]["use"] == "sig"
        assert "kid" in keys[0]
        # Public half only — a JWKS must never leak the private exponent.
        assert "d" not in keys[0]


# ---------------------------------------------------------------------------
# The full happy path: DCR -> authorize (PKCE+resource) -> token -> verify
# ---------------------------------------------------------------------------


class TestHappyPathFlow:
    async def test_full_code_flow_yields_verifiable_token(self, demo_as, verifier):
        async with make_client(demo_as) as client:
            client_id = await register_client(client)
            callback = await obtain_code(client, client_id)

            # RFC 9207: iss identifies the answering AS; state is the CSRF
            # token echoed back for the client to validate.
            assert callback["state"] == STATE
            assert callback["iss"] == ISSUER
            assert "code" in callback

            response = await client.post(
                "/auth/token", data=token_request(client_id, callback["code"])
            )

        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        body = response.json()
        assert body["token_type"] == "Bearer"
        assert body["expires_in"] == 15 * 60
        assert body["scope"] == "library:read library:write"
        assert "refresh_token" in body

        # The loop closes: the RESOURCE SERVER's verifier accepts the token
        # because iss matches, the signature checks out against the AS JWKS,
        # and aud contains the canonical resource URI it was minted for.
        principal = verifier.verify(body["access_token"])
        assert principal.subject == "demo-user"
        assert principal.email == "librarian@example.com"
        assert principal.scopes == frozenset({"library:read", "library:write"})
        assert principal.claims["aud"] == [CANONICAL]
        assert principal.claims["iss"] == ISSUER
        assert "jti" in principal.claims

    async def test_scope_defaults_to_supported_set_when_omitted(self, demo_as, verifier):
        async with make_client(demo_as) as client:
            client_id = await register_client(client)
            callback = await obtain_code(client, client_id, scope=None)
            response = await client.post(
                "/auth/token", data=token_request(client_id, callback["code"])
            )
        principal = verifier.verify(response.json()["access_token"])
        assert principal.scopes == frozenset({"library:read", "library:write"})

    async def test_refresh_token_grant_with_rotation(self, demo_as, verifier):
        async with make_client(demo_as) as client:
            client_id = await register_client(client)
            callback = await obtain_code(client, client_id)
            first = (
                await client.post("/auth/token", data=token_request(client_id, callback["code"]))
            ).json()

            refreshed = await client.post(
                "/auth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": first["refresh_token"],
                    "client_id": client_id,
                },
            )
            assert refreshed.status_code == 200
            body = refreshed.json()
            assert verifier.verify(body["access_token"]).subject == "demo-user"
            # Rotation: a NEW refresh token every time (OAuth 2.1 §4.3.1
            # MUST for public clients)...
            assert body["refresh_token"] != first["refresh_token"]

            # ...and the OLD one is dead — replay is how theft is detected.
            replayed = await client.post(
                "/auth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": first["refresh_token"],
                    "client_id": client_id,
                },
            )
            assert replayed.status_code == 400
            assert replayed.json()["error"] == "invalid_grant"


# ---------------------------------------------------------------------------
# PKCE enforcement
# ---------------------------------------------------------------------------


class TestPkceEnforcement:
    async def test_missing_code_challenge_rejected(self, demo_as):
        async with make_client(demo_as) as client:
            client_id = await register_client(client)
            callback = await obtain_code(
                client, client_id, code_challenge=None, code_challenge_method=None
            )

        # Redirect-uri was valid, so the error arrives BY redirect — with
        # state and iss (RFC 9207 covers error responses too).
        assert "code" not in callback
        assert callback["error"] == "invalid_request"
        assert "PKCE" in callback["error_description"]
        assert callback["state"] == STATE
        assert callback["iss"] == ISSUER

    async def test_plain_method_rejected(self, demo_as):
        # OAuth 2.1 + MCP security considerations: S256 when capable;
        # this AS goes further and refuses `plain` outright.
        async with make_client(demo_as) as client:
            client_id = await register_client(client)
            callback = await obtain_code(
                client,
                client_id,
                code_challenge=VERIFIER_STRING,
                code_challenge_method="plain",
            )

        assert "code" not in callback
        assert callback["error"] == "invalid_request"
        assert "S256" in callback["error_description"]

    async def test_wrong_verifier_rejected_at_token_endpoint(self, demo_as):
        async with make_client(demo_as) as client:
            client_id = await register_client(client)
            callback = await obtain_code(client, client_id)
            response = await client.post(
                "/auth/token",
                data=token_request(
                    client_id, callback["code"], code_verifier="wrong-verifier-wrong-wrong-wrong"
                ),
            )

        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"

    async def test_missing_verifier_rejected(self, demo_as):
        async with make_client(demo_as) as client:
            client_id = await register_client(client)
            callback = await obtain_code(client, client_id)
            response = await client.post(
                "/auth/token", data=token_request(client_id, callback["code"], code_verifier=None)
            )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_request"


# ---------------------------------------------------------------------------
# Authorization-code lifecycle
# ---------------------------------------------------------------------------


class TestCodeLifecycle:
    async def test_code_reuse_rejected(self, demo_as):
        async with make_client(demo_as) as client:
            client_id = await register_client(client)
            callback = await obtain_code(client, client_id)

            first = await client.post(
                "/auth/token", data=token_request(client_id, callback["code"])
            )
            assert first.status_code == 200

            # Single-use: the second redemption MUST fail (a replayed code
            # is treated as evidence of interception).
            second = await client.post(
                "/auth/token", data=token_request(client_id, callback["code"])
            )
            assert second.status_code == 400
            assert second.json()["error"] == "invalid_grant"

    async def test_expired_code_rejected(self, demo_as):
        async with make_client(demo_as) as client:
            client_id = await register_client(client)
            callback = await obtain_code(client, client_id)
            # Age the stored code past its 60 s lifetime.
            demo_as._codes[callback["code"]].expires_at = time.time() - 1

            response = await client.post(
                "/auth/token", data=token_request(client_id, callback["code"])
            )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"
        assert "expired" in response.json()["error_description"]

    async def test_redirect_uri_mismatch_at_token_rejected(self, demo_as):
        async with make_client(demo_as) as client:
            client_id = await register_client(client)
            callback = await obtain_code(client, client_id)
            response = await client.post(
                "/auth/token",
                data=token_request(
                    client_id, callback["code"], redirect_uri="http://127.0.0.1:3000/other"
                ),
            )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"

    async def test_code_bound_to_client_id(self, demo_as):
        async with make_client(demo_as) as client:
            client_id = await register_client(client)
            other_client_id = await register_client(client)
            callback = await obtain_code(client, client_id)
            response = await client.post(
                "/auth/token", data=token_request(other_client_id, callback["code"])
            )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"


# ---------------------------------------------------------------------------
# RFC 8707 resource indicators -> audience binding
# ---------------------------------------------------------------------------


class TestResourceAudienceBinding:
    async def test_missing_resource_on_authorize_rejected(self, demo_as):
        async with make_client(demo_as) as client:
            client_id = await register_client(client)
            callback = await obtain_code(client, client_id, resource=None)
        assert "code" not in callback
        assert callback["error"] == "invalid_target"

    async def test_resource_mismatch_at_token_rejected(self, demo_as):
        # A code authorized for THIS resource cannot be redeemed into a
        # token for another one.
        async with make_client(demo_as) as client:
            client_id = await register_client(client)
            callback = await obtain_code(client, client_id)
            response = await client.post(
                "/auth/token",
                data=token_request(
                    client_id, callback["code"], resource="https://other.example/mcp"
                ),
            )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_target"

    async def test_token_for_other_resource_rejected_by_verifier(self, demo_as, verifier):
        # End-to-end audience binding: the AS mints aud from the client's
        # `resource`, and OUR resource server rejects a token minted for a
        # different resource even though the AS and signature are trusted.
        other = "https://other-server.example/mcp"
        async with make_client(demo_as) as client:
            client_id = await register_client(client)
            callback = await obtain_code(client, client_id, resource=other)
            response = await client.post(
                "/auth/token", data=token_request(client_id, callback["code"], resource=other)
            )

        token = response.json()["access_token"]
        with pytest.raises(InvalidTokenError, match="audience"):
            verifier.verify(token)


# ---------------------------------------------------------------------------
# Client validation on /authorize (no-redirect failures)
# ---------------------------------------------------------------------------


class TestAuthorizeClientValidation:
    async def test_unknown_client_gets_400_not_redirect(self, demo_as):
        # Before the redirect_uri is validated the AS MUST NOT redirect —
        # an unvalidated redirect target is an open redirector.
        async with make_client(demo_as) as client:
            response = await client.get(
                "/auth/authorize", params=authorize_params("no-such-client")
            )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_client"

    async def test_unregistered_redirect_uri_gets_400(self, demo_as):
        async with make_client(demo_as) as client:
            client_id = await register_client(client)
            response = await client.get(
                "/auth/authorize",
                params=authorize_params(client_id, redirect_uri="https://evil.example/cb"),
            )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_request"


# ---------------------------------------------------------------------------
# Deprecated-DCR fallback (SEP-837)
# ---------------------------------------------------------------------------


class TestDynamicClientRegistration:
    async def test_registration_without_application_type_rejected(self, demo_as):
        async with make_client(demo_as) as client:
            response = await client.post(
                "/auth/register",
                json={
                    "client_name": "Legacy Client",
                    "redirect_uris": [REDIRECT_URI],
                    # application_type deliberately omitted.
                },
            )

        assert response.status_code == 400
        body = response.json()
        assert body["error"] == "invalid_client_metadata"
        # The teaching error names the SEP and the fix.
        assert "SEP-837" in body["error_description"]
        assert "application_type" in body["error_description"]

    async def test_registration_returns_public_client(self, demo_as):
        async with make_client(demo_as) as client:
            response = await client.post(
                "/auth/register",
                json={
                    "client_name": "CLI Client",
                    "redirect_uris": [REDIRECT_URI],
                    "application_type": "native",
                },
            )
        assert response.status_code == 201
        body = response.json()
        assert body["token_endpoint_auth_method"] == "none"
        assert "client_secret" not in body
        assert body["application_type"] == "native"

    async def test_registration_requires_redirect_uris(self, demo_as):
        async with make_client(demo_as) as client:
            response = await client.post(
                "/auth/register",
                json={"client_name": "No Redirects", "application_type": "native"},
            )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_redirect_uri"


# ---------------------------------------------------------------------------
# CIMD — Client ID Metadata Documents (stubbed fetcher, no network)
# ---------------------------------------------------------------------------


def stub_fetcher(documents: dict[str, Any]):
    """A CIMD fetcher serving canned documents from a dict."""

    async def fetch(url: str) -> Any:
        try:
            return documents[url]
        except KeyError as exc:
            msg = f"404 for {url}"
            raise RuntimeError(msg) from exc

    return fetch


class TestCimd:
    def make_as(self, documents: dict[str, Any]) -> DemoAuthorizationServer:
        return DemoAuthorizationServer(issuer=ISSUER, cimd_fetcher=stub_fetcher(documents))

    async def test_cimd_happy_path(self):
        demo_as = self.make_as({CIMD_CLIENT_ID: CIMD_DOCUMENT})
        verifier = TokenVerifier(issuer=ISSUER, audience=CANONICAL, jwks=demo_as.jwks())
        async with make_client(demo_as) as client:
            # No registration step at all: the https URL IS the client_id.
            callback = await obtain_code(client, CIMD_CLIENT_ID)
            assert callback["iss"] == ISSUER
            response = await client.post(
                "/auth/token", data=token_request(CIMD_CLIENT_ID, callback["code"])
            )

        assert response.status_code == 200
        assert verifier.verify(response.json()["access_token"]).subject == "demo-user"

    async def test_client_id_mismatch_inside_document_rejected(self):
        # The self-reference check: a document copied from another client
        # (or otherwise inconsistent) MUST be rejected — matching client_id
        # is what makes the URL an identity.
        documents = {CIMD_CLIENT_ID: {**CIMD_DOCUMENT, "client_id": "https://evil.example/c.json"}}
        demo_as = self.make_as(documents)
        async with make_client(demo_as) as client:
            response = await client.get("/auth/authorize", params=authorize_params(CIMD_CLIENT_ID))
        assert response.status_code == 400
        body = response.json()
        assert body["error"] == "invalid_client"
        assert "client_id" in body["error_description"]

    async def test_redirect_uri_not_in_document_rejected(self):
        demo_as = self.make_as({CIMD_CLIENT_ID: CIMD_DOCUMENT})
        async with make_client(demo_as) as client:
            response = await client.get(
                "/auth/authorize",
                params=authorize_params(
                    CIMD_CLIENT_ID, redirect_uri="https://attacker.example/callback"
                ),
            )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_request"

    async def test_loopback_port_variance_accepted(self):
        # RFC 8252 §7.3: the registered URI says port 3000, but native apps
        # bind an ephemeral port at runtime — the AS MUST ignore the port
        # for http loopback redirects.  Host/path still match exactly.
        demo_as = self.make_as({CIMD_CLIENT_ID: CIMD_DOCUMENT})
        ephemeral = "http://127.0.0.1:49152/callback"
        async with make_client(demo_as) as client:
            response = await client.get(
                "/auth/authorize",
                params=authorize_params(CIMD_CLIENT_ID, redirect_uri=ephemeral),
            )
            assert response.status_code == 302
            location = response.headers["location"]
            assert location.startswith("http://127.0.0.1:49152/callback?")
            query = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
            assert "code" in query

            # And the token exchange binds to the REQUESTED (ephemeral) uri.
            token = await client.post(
                "/auth/token",
                data=token_request(CIMD_CLIENT_ID, query["code"], redirect_uri=ephemeral),
            )
        assert token.status_code == 200

    async def test_loopback_path_still_must_match(self):
        demo_as = self.make_as({CIMD_CLIENT_ID: CIMD_DOCUMENT})
        async with make_client(demo_as) as client:
            response = await client.get(
                "/auth/authorize",
                params=authorize_params(
                    CIMD_CLIENT_ID, redirect_uri="http://127.0.0.1:3000/other-path"
                ),
            )
        assert response.status_code == 400

    async def test_http_scheme_client_id_rejected(self):
        demo_as = self.make_as({})
        async with make_client(demo_as) as client:
            response = await client.get(
                "/auth/authorize",
                params=authorize_params("http://app.example.com/client.json"),
            )
        assert response.status_code == 400
        assert "https" in response.json()["error_description"]

    async def test_client_id_url_without_path_rejected(self):
        demo_as = self.make_as({})
        async with make_client(demo_as) as client:
            response = await client.get(
                "/auth/authorize", params=authorize_params("https://app.example.com")
            )
        assert response.status_code == 400

    async def test_fetch_failure_rejected(self):
        demo_as = self.make_as({})  # fetcher 404s everything
        async with make_client(demo_as) as client:
            response = await client.get("/auth/authorize", params=authorize_params(CIMD_CLIENT_ID))
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_client"


# ---------------------------------------------------------------------------
# Consent-page mode (auto_approve=False)
# ---------------------------------------------------------------------------


class TestConsentMode:
    async def test_consent_page_then_approval_issues_code(self):
        demo_as = DemoAuthorizationServer(issuer=ISSUER, auto_approve=False)
        async with make_client(demo_as) as client:
            client_id = await register_client(client)

            page = await client.get("/auth/authorize", params=authorize_params(client_id))
            assert page.status_code == 200
            assert page.headers["content-type"].startswith("text/html")
            # CIMD security guidance: the consent UI must show who the
            # client is and where the user will be sent.
            assert client_id in page.text
            assert REDIRECT_URI in page.text

            form = dict(authorize_params(client_id), decision="approve")
            approved = await client.post("/auth/consent", data=form)
            callback = redirect_query(approved)
            assert "code" in callback
            assert callback["iss"] == ISSUER

    async def test_denial_redirects_with_access_denied(self):
        demo_as = DemoAuthorizationServer(issuer=ISSUER, auto_approve=False)
        async with make_client(demo_as) as client:
            client_id = await register_client(client)
            form = dict(authorize_params(client_id), decision="deny")
            denied = await client.post("/auth/consent", data=form)
            callback = redirect_query(denied)

        assert "code" not in callback
        assert callback["error"] == "access_denied"
        # iss on error responses too (RFC 9207 §2).
        assert callback["iss"] == ISSUER


# ---------------------------------------------------------------------------
# build_demo_auth — the integrator's one-call helper
# ---------------------------------------------------------------------------


class TestBuildDemoAuth:
    async def test_returns_wired_stack(self):
        routes, verifier, issuer = build_demo_auth(BASE_URL, CANONICAL)
        assert issuer == ISSUER

        app = Starlette(routes=routes)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE_URL
        ) as client:
            # PRM is mounted at BOTH well-known forms...
            prm_inserted = await client.get("/.well-known/oauth-protected-resource/mcp")
            prm_root = await client.get("/.well-known/oauth-protected-resource")
            assert prm_inserted.status_code == 200
            assert prm_root.json() == prm_inserted.json()
            # ...and points at the demo AS as the (only) authorization server.
            assert prm_inserted.json()["resource"] == CANONICAL
            assert prm_inserted.json()["authorization_servers"] == [issuer]

            # AS metadata resolves too.
            metadata = await client.get("/.well-known/oauth-authorization-server")
            assert metadata.json()["issuer"] == issuer

            # And a token minted through the mounted routes verifies with
            # the RETURNED verifier — the whole stack is self-consistent.
            client_id = await register_client(client)
            callback = await obtain_code(client, client_id)
            token = await client.post(
                "/auth/token", data=token_request(client_id, callback["code"])
            )
            principal = verifier.verify(token.json()["access_token"])
            assert principal.subject == "demo-user"
