"""
Tests for modern/auth/bearer.py and modern/auth/metadata.py.

These exercise the RESOURCE-SERVER half of MCP 2026-07-28 authorization:

- TokenVerifier MUSTs: signature + algorithm allowlist, exp/nbf, exact
  issuer match, and the RFC 8707 audience-binding rule (the token's ``aud``
  MUST contain this server's canonical resource URI) — the draft's core
  token rule and its anti-token-passthrough enforcement point;
- scope parsing from both standard claim shapes (``scope`` string per
  RFC 9068, ``scp`` list);
- the RFC 9728 Protected Resource Metadata document, served at BOTH
  required well-known forms (path-inserted first, then root);
- exact ``WWW-Authenticate`` challenge strings for 401 and 403, matching
  the spec's wire examples byte for byte.
"""

import base64
import json
import time
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from starlette.applications import Starlette

from modern.auth import (
    InvalidTokenError,
    Principal,
    TokenVerifier,
    build_prm_document,
    build_prm_routes,
    challenge_401,
    challenge_403,
    prm_url_for,
    prm_well_known_paths,
)

ISSUER = "http://127.0.0.1:8080/auth"
CANONICAL = "http://127.0.0.1:8080/mcp"
OTHER_RESOURCE = "https://other-server.example/mcp"
KID = "test-key-1"


# ---------------------------------------------------------------------------
# Key material fixtures — one RSA keypair for the whole module (keygen is
# slow, and every test only needs "a key the verifier trusts" plus "a key it
# does not").
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def attacker_key() -> rsa.RSAPrivateKey:
    """A DIFFERENT keypair — signatures from it must never verify."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def jwks(private_key: rsa.RSAPrivateKey) -> dict[str, Any]:
    jwk = dict(RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True))
    jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


@pytest.fixture
def verifier(jwks: dict[str, Any]) -> TokenVerifier:
    return TokenVerifier(issuer=ISSUER, audience=CANONICAL, jwks=jwks)


def mint(
    private_key: rsa.RSAPrivateKey,
    *,
    kid: str = KID,
    algorithm: str = "RS256",
    **overrides: Any,
) -> str:
    """Mint a token with valid defaults, overridable per test.

    Pass ``claim=None`` to REMOVE a default claim entirely (e.g. no ``aud``).
    """
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "demo-user",
        "aud": [CANONICAL],
        "scope": "library:read library:write",
        "email": "librarian@example.com",
        "iat": now,
        "exp": now + 900,
        "jti": "test-jti",
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, private_key, algorithm=algorithm, headers={"kid": kid})


# ---------------------------------------------------------------------------
# TokenVerifier — happy path
# ---------------------------------------------------------------------------


class TestTokenVerifierHappyPath:
    def test_valid_token_yields_principal(self, verifier, private_key):
        principal = verifier.verify(mint(private_key))

        assert isinstance(principal, Principal)
        assert principal.subject == "demo-user"
        assert principal.email == "librarian@example.com"
        assert principal.scopes == frozenset({"library:read", "library:write"})
        assert principal.claims["jti"] == "test-jti"

    def test_string_aud_containing_canonical_accepted(self, verifier, private_key):
        # `aud` may be a bare string instead of a list (RFC 7519 §4.1.3).
        principal = verifier.verify(mint(private_key, aud=CANONICAL))
        assert principal.subject == "demo-user"

    def test_multi_audience_list_accepted(self, verifier, private_key):
        # Audience CONTAINMENT is the rule: extra audiences do not disqualify
        # a token as long as ours is among them.
        principal = verifier.verify(mint(private_key, aud=[OTHER_RESOURCE, CANONICAL]))
        assert principal.subject == "demo-user"

    def test_scp_list_claim_parsed(self, verifier, private_key):
        # Azure-style `scp` list instead of RFC 9068 `scope` string.
        token = mint(private_key, scope=None, scp=["library:read"])
        assert verifier.verify(token).scopes == frozenset({"library:read"})

    def test_no_scope_claims_means_empty_scopes(self, verifier, private_key):
        # Scopeless tokens are VALID (401 is for bad tokens); whether they
        # may do anything is the 403/insufficient_scope question.
        assert verifier.verify(mint(private_key, scope=None)).scopes == frozenset()

    def test_missing_email_is_none(self, verifier, private_key):
        assert verifier.verify(mint(private_key, email=None)).email is None


# ---------------------------------------------------------------------------
# TokenVerifier — the MUST-reject cases
# ---------------------------------------------------------------------------


class TestTokenVerifierRejections:
    def test_audience_mismatch_rejected(self, verifier, private_key):
        # RFC 8707 audience binding: a token minted for ANOTHER MCP server
        # MUST be rejected here even though issuer/signature/expiry are all
        # good — this is the anti-passthrough rule.
        with pytest.raises(InvalidTokenError, match="audience"):
            verifier.verify(mint(private_key, aud=[OTHER_RESOURCE]))

    def test_missing_aud_rejected(self, verifier, private_key):
        with pytest.raises(InvalidTokenError, match="aud"):
            verifier.verify(mint(private_key, aud=None))

    def test_expired_token_rejected(self, verifier, private_key):
        with pytest.raises(InvalidTokenError, match="expired"):
            verifier.verify(mint(private_key, exp=int(time.time()) - 60))

    def test_not_yet_valid_nbf_rejected(self, verifier, private_key):
        with pytest.raises(InvalidTokenError, match="nbf"):
            verifier.verify(mint(private_key, nbf=int(time.time()) + 3600))

    def test_missing_exp_rejected(self, verifier, private_key):
        # A token without exp never expires — presence is required.
        with pytest.raises(InvalidTokenError, match="exp"):
            verifier.verify(mint(private_key, exp=None))

    def test_issuer_mismatch_rejected(self, verifier, private_key):
        with pytest.raises(InvalidTokenError, match="issuer"):
            verifier.verify(mint(private_key, iss="https://evil-as.example"))

    def test_issuer_comparison_is_exact_no_normalization(self, verifier, private_key):
        # A trailing slash makes a DIFFERENT issuer string — exact match,
        # no URL normalization (same discipline as RFC 9207 iss checks).
        with pytest.raises(InvalidTokenError, match="issuer"):
            verifier.verify(mint(private_key, iss=ISSUER + "/"))

    def test_wrong_signing_key_rejected(self, verifier, attacker_key):
        with pytest.raises(InvalidTokenError):
            verifier.verify(mint(attacker_key))

    def test_unknown_kid_rejected(self, verifier, private_key):
        with pytest.raises(InvalidTokenError, match="kid"):
            verifier.verify(mint(private_key, kid="not-in-jwks"))

    def test_hs256_token_rejected_by_rs256_verifier(self, verifier):
        # Algorithm-confusion defense: the allowlist comes from verifier
        # configuration, never from the attacker-controlled `alg` header.
        forged = jwt.encode(
            {"iss": ISSUER, "aud": [CANONICAL], "exp": int(time.time()) + 900},
            "a-shared-secret-well-over-thirty-two-bytes-long",
            algorithm="HS256",
        )
        with pytest.raises(InvalidTokenError, match="allowlist"):
            verifier.verify(forged)

    def test_garbage_token_rejected(self, verifier):
        with pytest.raises(InvalidTokenError, match="malformed"):
            verifier.verify("not-a-jwt-at-all")

    def test_tampered_payload_rejected(self, verifier, private_key):
        header, _payload, signature = mint(private_key).split(".")
        # Re-use a valid signature with a swapped payload (sub escalation).
        tampered_claims = {
            "iss": ISSUER,
            "sub": "admin",
            "aud": [CANONICAL],
            "exp": int(time.time()) + 900,
        }
        tampered_payload = (
            base64.urlsafe_b64encode(json.dumps(tampered_claims).encode()).rstrip(b"=").decode()
        )
        with pytest.raises(InvalidTokenError):
            verifier.verify(f"{header}.{tampered_payload}.{signature}")


class TestTokenVerifierConfiguration:
    def test_requires_exactly_one_key_mode(self, jwks):
        with pytest.raises(ValueError, match="exactly one"):
            TokenVerifier(issuer=ISSUER, audience=CANONICAL)
        with pytest.raises(ValueError, match="exactly one"):
            TokenVerifier(issuer=ISSUER, audience=CANONICAL, jwks=jwks, hs_secret=b"secret")

    def test_hs256_shared_secret_mode(self):
        secret = b"a-shared-secret-for-co-hosted-deployments-32+"
        hs_verifier = TokenVerifier(issuer=ISSUER, audience=CANONICAL, hs_secret=secret)
        token = jwt.encode(
            {"iss": ISSUER, "aud": [CANONICAL], "exp": int(time.time()) + 900, "sub": "u"},
            secret,
            algorithm="HS256",
        )
        assert hs_verifier.verify(token).subject == "u"
        # And the mirror-image confusion: non-HS256 algs fail the allowlist.
        hs384_token = jwt.encode({"exp": 1}, "x" * 48, algorithm="HS384")
        with pytest.raises(InvalidTokenError, match="allowlist"):
            hs_verifier.verify(hs384_token)


# ---------------------------------------------------------------------------
# Protected Resource Metadata (RFC 9728)
# ---------------------------------------------------------------------------


class TestPrmDocument:
    def test_document_shape(self):
        doc = build_prm_document(canonical_resource_url=CANONICAL, issuer=ISSUER)

        assert doc == {
            "resource": CANONICAL,
            "authorization_servers": [ISSUER],
            "scopes_supported": ["library:read", "library:write"],
            "bearer_methods_supported": ["header"],
        }

    def test_well_known_paths_ordered_path_inserted_first(self):
        # Clients MUST try the path-inserted form first, then root.
        assert prm_well_known_paths(CANONICAL) == [
            "/.well-known/oauth-protected-resource/mcp",
            "/.well-known/oauth-protected-resource",
        ]

    def test_root_resource_collapses_to_single_path(self):
        assert prm_well_known_paths("http://127.0.0.1:8080") == [
            "/.well-known/oauth-protected-resource"
        ]
        assert prm_well_known_paths("http://127.0.0.1:8080/") == [
            "/.well-known/oauth-protected-resource"
        ]

    def test_prm_url_uses_path_inserted_form(self):
        assert (
            prm_url_for(CANONICAL)
            == "http://127.0.0.1:8080/.well-known/oauth-protected-resource/mcp"
        )


class TestPrmRoutes:
    @pytest.fixture
    def client(self) -> httpx.AsyncClient:
        app = Starlette(routes=build_prm_routes(canonical_resource_url=CANONICAL, issuer=ISSUER))
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8080"
        )

    async def test_served_at_path_inserted_well_known(self, client):
        async with client:
            response = await client.get("/.well-known/oauth-protected-resource/mcp")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        assert body["resource"] == CANONICAL
        assert body["authorization_servers"] == [ISSUER]

    async def test_served_at_root_well_known(self, client):
        async with client:
            root = await client.get("/.well-known/oauth-protected-resource")
            inserted = await client.get("/.well-known/oauth-protected-resource/mcp")

        assert root.status_code == 200
        # Both well-known forms serve the SAME document.
        assert root.json() == inserted.json()

    async def test_offline_access_not_advertised(self, client):
        # Protected resources SHOULD NOT advertise offline_access — refresh
        # tokens are a client<->AS concern.
        async with client:
            response = await client.get("/.well-known/oauth-protected-resource")
        assert "offline_access" not in response.json()["scopes_supported"]


# ---------------------------------------------------------------------------
# WWW-Authenticate challenge builders — exact wire formats
# ---------------------------------------------------------------------------


class TestChallengeHeaders:
    def test_401_challenge_matches_spec_example(self):
        # The spec's own 401 example (unfolded to one line).
        assert challenge_401(
            "https://mcp.example.com/.well-known/oauth-protected-resource",
            "files:read",
        ) == (
            "Bearer resource_metadata="
            '"https://mcp.example.com/.well-known/oauth-protected-resource", '
            'scope="files:read"'
        )

    def test_401_challenge_scope_optional(self):
        assert (
            challenge_401("http://h/.well-known/oauth-protected-resource")
            == 'Bearer resource_metadata="http://h/.well-known/oauth-protected-resource"'
        )

    def test_403_challenge_matches_spec_example(self):
        # The spec's exact 403 insufficient_scope example (unfolded).
        assert challenge_403(
            "files:write",
            "https://mcp.example.com/.well-known/oauth-protected-resource",
            "File write permission required for this operation",
        ) == (
            'Bearer error="insufficient_scope", scope="files:write", '
            "resource_metadata="
            '"https://mcp.example.com/.well-known/oauth-protected-resource", '
            'error_description="File write permission required for this operation"'
        )

    def test_403_description_optional(self):
        assert challenge_403("library:write", "http://h/prm") == (
            'Bearer error="insufficient_scope", scope="library:write", '
            'resource_metadata="http://h/prm"'
        )

    def test_quoted_string_escaping(self):
        # error_description is server-authored but may interpolate values;
        # quoted-string escaping keeps the header parseable regardless.
        header = challenge_403("s", "http://h/prm", 'needs "write" access')
        assert 'error_description="needs \\"write\\" access"' in header


class TestSharedDiscoveryFiltering:
    """discovery_era='legacy' support: ceding shared well-knowns to FastMCP.

    A dual-era server has TWO OAuth stacks that both want the fixed RFC
    9728/8414 well-known locations. ``shared_discovery_paths`` names the
    contested paths; ``filter_shared_discovery_routes`` removes them from
    the modern route set so the dual-era front door lets them fall through
    to the legacy app — that is how interactive chat clients (which speak
    the legacy era) complete OAuth discovery against a deployed dual-era
    server.
    """

    CANONICAL = "https://library.example.run.app/mcp"

    def test_shared_paths_are_the_three_contested_locations(self):
        from modern.auth import shared_discovery_paths

        assert shared_discovery_paths(self.CANONICAL) == {
            "/.well-known/oauth-protected-resource/mcp",
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-authorization-server",
        }

    def test_filter_keeps_every_era_specific_route(self):
        from modern.auth import build_demo_auth, filter_shared_discovery_routes

        routes, _verifier, _issuer = build_demo_auth(
            base_url="https://library.example.run.app",
            canonical_resource_url=self.CANONICAL,
        )
        kept = {r.path for r in filter_shared_discovery_routes(routes, self.CANONICAL)}

        # The path-inserted AS metadata form is the modern era's collision-
        # free discovery home (RFC 8414 §3.1 path insertion) — it MUST stay,
        # or a modern client pointed at the issuer could never bootstrap.
        assert "/.well-known/oauth-authorization-server/auth" in kept
        # The AS endpoints themselves are all under /auth and never contested.
        assert {
            "/auth/authorize",
            "/auth/consent",
            "/auth/token",
            "/auth/register",
            "/auth/jwks.json",
        } <= kept

    def test_filter_drops_exactly_the_shared_paths(self):
        from modern.auth import (
            build_demo_auth,
            filter_shared_discovery_routes,
            shared_discovery_paths,
        )

        routes, _verifier, _issuer = build_demo_auth(
            base_url="https://library.example.run.app",
            canonical_resource_url=self.CANONICAL,
        )
        before = {r.path for r in routes}
        after = {r.path for r in filter_shared_discovery_routes(routes, self.CANONICAL)}

        assert before - after == shared_discovery_paths(self.CANONICAL)
