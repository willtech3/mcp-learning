"""
MCP 2026-07-28 authorization for the modern era — resource server + demo AS.

The draft authorization model splits cleanly into three roles, and this
package implements two of them so the whole flow runs locally end-to-end:

- :mod:`modern.auth.bearer` — the RESOURCE SERVER half the spec actually
  requires of an MCP server: validate ``Authorization: Bearer`` JWTs with
  RFC 8707 audience binding (the token's ``aud`` MUST contain this server's
  canonical resource URI), exact issuer match, exp/nbf, and an algorithm
  allowlist.  Produces a :class:`~modern.auth.bearer.Principal`.

- :mod:`modern.auth.metadata` — RFC 9728 Protected Resource Metadata (the
  MUST-implement discovery document, served at both well-known forms) and
  the exact ``WWW-Authenticate`` challenge strings for 401 (need a token /
  bad token) and 403 (good token, insufficient scope).

- :mod:`modern.auth.demo_as` — an EDUCATIONAL, in-memory OAuth 2.1
  authorization server (normally out of scope for MCP — "its implementation
  is out of scope" says the spec — which is precisely why building a toy
  one teaches so much): RFC 8414 metadata, PKCE S256-only, CIMD client
  identification with a deprecated-DCR fallback (SEP-837 application_type
  enforcement), RFC 8707 resource -> ``aud`` minting, RFC 9207 ``iss`` on
  every authorization response, single-use codes, refresh rotation.

:func:`build_demo_auth` is the one-call wiring helper for the integrator:
it constructs the demo AS, a :class:`TokenVerifier` keyed to the AS's JWKS
and the server's canonical resource URI, and every public route the auth
story needs (AS endpoints + AS metadata + PRM at both well-known paths).
All of those routes MUST be mounted OUTSIDE bearer-auth enforcement —
well-known discovery documents exist precisely for clients that do not
have a token yet.

Spec references: MCP 2026-07-28 basic/authorization and subpages
(authorization-server-discovery, client-registration,
security-considerations); SEP-837, SEP-2352, SEP-2468.
"""

from starlette.routing import Route

from modern.auth.bearer import InvalidTokenError, Principal, TokenVerifier
from modern.auth.demo_as import DemoAuthorizationServer
from modern.auth.metadata import (
    DEFAULT_SCOPES,
    build_prm_document,
    build_prm_routes,
    challenge_401,
    challenge_403,
    prm_url_for,
    prm_well_known_paths,
)


def build_demo_auth(
    base_url: str,
    canonical_resource_url: str,
    auto_approve: bool = True,
) -> tuple[list[Route], TokenVerifier, str]:
    """Wire up the complete local authorization stack for the dual-era server.

    Args:
        base_url: The public origin the server is reachable at
            (e.g. ``http://127.0.0.1:8080``).  The demo AS's issuer becomes
            ``{base_url}/auth`` — AS co-hosted with the resource server,
            which the spec explicitly allows.
        canonical_resource_url: The RFC 8707 canonical URI of the MCP
            endpoint (e.g. ``http://127.0.0.1:8080/mcp``).  Appears as
            ``resource`` in the PRM document, is what clients must send as
            the ``resource`` parameter, and is the audience the verifier
            demands in every token's ``aud``.
        auto_approve: When True (the default, and what tests use) the demo
            AS skips the consent page and immediately redirects back with a
            code; when False it renders a minimal HTML consent form first.

    Returns:
        ``(routes, verifier, issuer)`` — mount ``routes`` on the ASGI app
        OUTSIDE auth enforcement; pass ``verifier`` to the HTTP layer's
        bearer check; use ``issuer`` anywhere the AS identity is needed
        (logs, config echoes).  The verifier trusts the demo AS's freshly
        generated JWKS, so tokens minted by these routes — and only those —
        authenticate against this server.
    """
    issuer = base_url.rstrip("/") + "/auth"
    demo_as = DemoAuthorizationServer(issuer=issuer, auto_approve=auto_approve)
    verifier = TokenVerifier(
        issuer=demo_as.issuer,
        audience=canonical_resource_url,
        jwks=demo_as.jwks(),
    )
    routes = [
        *demo_as.routes(),
        *build_prm_routes(
            canonical_resource_url=canonical_resource_url,
            issuer=demo_as.issuer,
        ),
    ]
    return routes, verifier, demo_as.issuer


__all__ = [
    "DEFAULT_SCOPES",
    "DemoAuthorizationServer",
    "InvalidTokenError",
    "Principal",
    "TokenVerifier",
    "build_demo_auth",
    "build_prm_document",
    "build_prm_routes",
    "challenge_401",
    "challenge_403",
    "prm_url_for",
    "prm_well_known_paths",
]
