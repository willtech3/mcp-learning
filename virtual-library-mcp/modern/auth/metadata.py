"""
Protected Resource Metadata (RFC 9728) and WWW-Authenticate challenges.

MCP 2026-07-28 makes RFC 9728 the mandatory discovery bridge between an MCP
server and its authorization server: MCP servers MUST publish a Protected
Resource Metadata (PRM) document, and MCP clients MUST use it to find the
AS.  The choreography is deliberately bootstrappable from nothing but the
server URL:

1. The client POSTs to the MCP endpoint with no token and receives ``401``
   with ``WWW-Authenticate: Bearer resource_metadata="<PRM URL>"``.
2. It fetches the PRM document, reads ``authorization_servers`` (the only
   MCP-mandated field — at least one entry), and runs AS metadata discovery
   against the chosen issuer.
3. ``resource`` in the PRM names this server's RFC 8707 canonical URI — the
   exact string clients must send as the ``resource`` parameter and that
   :class:`modern.auth.bearer.TokenVerifier` later demands in ``aud``.
   Clients MUST verify a present ``resource`` matches the server they
   actually connected to (anti-phishing: a PRM served by evil.example that
   claims ``resource: https://honest.example/mcp`` is a lie).

The spec allows a server to publish PRM through the challenge header OR a
well-known URI; we do both, and we serve BOTH well-known forms clients are
required to try, in their required order:

- path-inserted (tried first): MCP endpoint ``https://host/mcp`` ->
  ``https://host/.well-known/oauth-protected-resource/mcp`` — required so
  that several MCP servers can share one host without their PRM documents
  colliding;
- root fallback: ``https://host/.well-known/oauth-protected-resource``.

Challenge builders live here too because they are the OTHER half of RFC
9728 discovery.  Their parameter sets come straight from the spec's wire
examples (authorization core page §Protected Resource Metadata and §Error
Handling):

- 401: token missing/invalid/expired.  Carries ``resource_metadata`` and
  SHOULD carry ``scope`` (RFC 6750 §3) so the client knows what to ask for.
- 403: token VALID but insufficient scope.  Carries
  ``error="insufficient_scope"`` plus the scopes needed for THIS operation —
  and per a 2026-07-28 change, servers need NOT echo previously granted
  scopes: accumulating the union across re-authorizations is now the
  client's job, which keeps the server stateless about client scope sets.

Spec references: MCP 2026-07-28 basic/authorization, RFC 9728 (§3.1, §5.1),
RFC 6750 §3/§3.1, RFC 8707 §2.
"""

from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

#: Scopes this library server understands.  Advertised in PRM
#: ``scopes_supported`` as the minimal set for basic functionality — the
#: spec's client scope-selection priority uses these when the 401 challenge
#: itself names no scope.  Note the ABSENCE of ``offline_access``: protected
#: resources SHOULD NOT advertise refresh-token scopes (refresh is a
#: client<->AS concern, not a resource requirement).
DEFAULT_SCOPES: tuple[str, ...] = ("library:read", "library:write")

#: RFC 9728 well-known path segment (registered with IANA).
PRM_WELL_KNOWN_PREFIX = "/.well-known/oauth-protected-resource"


# ---------------------------------------------------------------------------
# PRM document + routes
# ---------------------------------------------------------------------------


def build_prm_document(
    *,
    canonical_resource_url: str,
    issuer: str,
    scopes_supported: Sequence[str] = DEFAULT_SCOPES,
) -> dict[str, Any]:
    """Build the RFC 9728 Protected Resource Metadata document.

    ``authorization_servers`` is the only field MCP itself mandates (with at
    least one entry); when several are listed each is an independent AS and
    the CLIENT picks — keeping separate credentials per issuer (SEP-2352).
    Our educational deployment has exactly one AS, the built-in demo AS.
    """
    return {
        # The RFC 8707 canonical URI of this MCP server — lowercase scheme/
        # host, no fragment, no gratuitous trailing slash.  Everything in the
        # authorization story keys off this exact string: the client echoes
        # it as the `resource` parameter, the AS mints it into `aud`, and the
        # TokenVerifier requires it back out of `aud`.
        "resource": canonical_resource_url,
        "authorization_servers": [issuer],
        "scopes_supported": list(scopes_supported),
        # We only read tokens from the Authorization header (RFC 6750 §2.1).
        # The body and query-string methods from RFC 6750 are historically
        # allowed but MCP forbids query-string tokens outright.
        "bearer_methods_supported": ["header"],
    }


def prm_well_known_paths(canonical_resource_url: str) -> list[str]:
    """The well-known paths at which the PRM document must be served.

    Ordered as clients are required to try them: path-inserted form first
    (RFC 9728 path insertion mirrors the MCP endpoint's path under the
    well-known prefix), then the host-root fallback.  An MCP endpoint at the
    host root collapses both forms into one.
    """
    resource_path = urlsplit(canonical_resource_url).path.rstrip("/")
    paths = [PRM_WELL_KNOWN_PREFIX]
    if resource_path:
        paths.insert(0, PRM_WELL_KNOWN_PREFIX + resource_path)
    return paths


def prm_url_for(canonical_resource_url: str) -> str:
    """Absolute URL of the PRM document, for ``resource_metadata=`` params.

    Uses the path-inserted form — the one clients try first — so the
    challenge header and well-known discovery land on the same document.
    """
    parts = urlsplit(canonical_resource_url)
    return f"{parts.scheme}://{parts.netloc}{prm_well_known_paths(canonical_resource_url)[0]}"


def shared_discovery_paths(canonical_resource_url: str) -> set[str]:
    """Well-known paths BOTH protocol eras want to serve — the dual-era rub.

    A dual-era server has two authorization stories publishing discovery
    documents, but RFC 9728 and RFC 8414 pin those documents to fixed
    well-known locations, so exactly one era can own each path:

    - both PRM forms (path-inserted and host-root fallback): the modern era
      serves its own PRM here, and a legacy OAuth stack (e.g. FastMCP's
      OAuth proxy) serves ITS protected-resource metadata at the very same
      paths — the resource URI is the same ``/mcp`` endpoint in both eras.
    - the host-root RFC 8414 form ``/.well-known/oauth-authorization-server``:
      the demo AS serves it as a convenience fallback, and a legacy stack
      whose issuer is the host root serves it as its PRIMARY metadata URL.

    NOT shared — and deliberately excluded — is the path-inserted AS
    metadata form (``/.well-known/oauth-authorization-server/auth``): the
    demo AS issuer has a ``/auth`` path component, so RFC 8414 §3.1 gives it
    a collision-free home of its own. That is what keeps the modern era
    discoverable even when the legacy era owns every shared path: a client
    told the issuer directly can still fetch metadata and run the flow.
    """
    return set(prm_well_known_paths(canonical_resource_url)) | {
        "/.well-known/oauth-authorization-server"
    }


def filter_shared_discovery_routes(routes: list[Route], canonical_resource_url: str) -> list[Route]:
    """Drop the shared well-known routes so they fall through to the legacy era.

    The dual-era front door (:func:`modern.http.create_dual_era_app`) routes
    a non-MCP path to the modern app only when the modern app registered it;
    everything else goes legacy. So ceding a discovery document to the
    legacy era is done by NOT registering it here — no special cases in the
    router itself.

    Used when ``discovery_era = "legacy"``: interactive chat clients that
    speak the legacy protocol walk PRM -> AS metadata -> PKCE from the
    shared paths, so the legacy OAuth stack must own them for those clients
    to onboard at all. The modern era keeps every era-specific route (the
    ``/auth/*`` endpoints and the path-inserted metadata form).
    """
    shared = shared_discovery_paths(canonical_resource_url)
    return [route for route in routes if route.path not in shared]


def build_prm_routes(
    *,
    canonical_resource_url: str,
    issuer: str,
    scopes_supported: Sequence[str] = DEFAULT_SCOPES,
) -> list[Route]:
    """Starlette routes serving the PRM document at BOTH well-known forms.

    These routes MUST be mounted OUTSIDE any auth middleware: PRM is how an
    unauthenticated client learns where to authenticate, so gating it behind
    the very tokens it helps obtain would deadlock discovery.
    """
    document = build_prm_document(
        canonical_resource_url=canonical_resource_url,
        issuer=issuer,
        scopes_supported=scopes_supported,
    )

    def serve_prm(_request: Request) -> JSONResponse:
        # RFC 9728 §3.2: the response is a plain JSON document.  It is
        # public and stable, so intermediaries may cache it freely.
        return JSONResponse(document)

    return [
        Route(path, serve_prm, methods=["GET"])
        for path in prm_well_known_paths(canonical_resource_url)
    ]


# ---------------------------------------------------------------------------
# WWW-Authenticate challenge builders
# ---------------------------------------------------------------------------


def _quote(value: str) -> str:
    """Render an RFC 7235 quoted-string auth-param value.

    Backslash-escapes ``\\`` and ``"`` — the only characters that need it in
    a quoted-string.  Challenge parameters are attacker-visible but server-
    authored; escaping still matters because ``error_description`` may
    interpolate operation names.
    """
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def challenge_401(prm_url: str, scope: str | None = None) -> str:
    """``WWW-Authenticate`` value for a 401 (no token / invalid / expired).

    Wire format per the spec's own example::

        Bearer resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource", scope="files:read"

    ``resource_metadata`` (RFC 9728 §5.1) is the discovery bootstrap —
    clients MUST prefer this URL over constructing well-known paths.
    ``scope`` (RFC 6750 §3) is a SHOULD: it is authoritative for the current
    operation, taking precedence over PRM ``scopes_supported`` in the
    client's scope-selection priority order.
    """
    params = [f"resource_metadata={_quote(prm_url)}"]
    if scope is not None:
        params.append(f"scope={_quote(scope)}")
    return "Bearer " + ", ".join(params)


def challenge_403(scope: str, prm_url: str, description: str | None = None) -> str:
    """``WWW-Authenticate`` value for a 403 (valid token, missing scope).

    Wire format per the spec's example (RFC 6750 §3.1)::

        Bearer error="insufficient_scope", scope="files:write", resource_metadata="...", error_description="..."

    ``scope`` here lists ALL scopes the current operation needs, in a single
    challenge (no drip-feeding one scope per retry) — but deliberately NOT
    the client's previously granted scopes: 2026-07-28 moved scope
    accumulation client-side (the client unions this with what it already
    requested before stepping up).
    """
    params = [
        f"error={_quote('insufficient_scope')}",
        f"scope={_quote(scope)}",
        f"resource_metadata={_quote(prm_url)}",
    ]
    if description is not None:
        params.append(f"error_description={_quote(description)}")
    return "Bearer " + ", ".join(params)
