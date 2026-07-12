"""
An EDUCATIONAL, in-memory OAuth 2.1 authorization server for the demo stack.

*** THIS IS A TEACHING TOY.  NEVER, EVER USE IT IN PRODUCTION. ***

It has no user database (everyone is "demo-user"), no real login, no
persistent storage (restart = every token orphaned), no rate limiting, no
TLS enforcement, no consent auditing, and it will happily hand a token to
anyone who completes the dance.  Its sole purpose is to let the MCP
2026-07-28 authorization flow run end-to-end on localhost so you can watch
every message — the parts that are usually hidden inside Okta/Auth0/Google.

What it DOES implement faithfully, because these are the lessons:

- **RFC 8414 AS metadata** at the well-known URL(s), advertising
  ``code_challenge_methods_supported: ["S256"]`` (clients MUST refuse to
  proceed when this field is absent — its presence is the client's proof of
  PKCE support), ``authorization_response_iss_parameter_supported: true``
  (RFC 9207: an AS that emits ``iss`` MUST advertise it), and
  ``client_id_metadata_document_supported: true`` (CIMD, the draft's
  replacement for Dynamic Client Registration).

- **PKCE, S256 only (OAuth 2.1 §7.5.2).**  ``plain`` is rejected outright:
  it offers no protection against an attacker who can see the authorization
  request, which is the whole threat model.

- **CIMD (draft-ietf-oauth-client-id-metadata-document-00, SEP-991/spec
  client-registration page).**  A ``client_id`` that is an https URL with a
  path names a JSON document the AS fetches; the document MUST contain a
  ``client_id`` equal to the URL *exactly* (the self-reference is what makes
  the URL an identity), and redirect URIs are validated against the
  document's ``redirect_uris``.  Loopback redirects match port-agnostically
  per RFC 8252 §7.3 (native apps bind an ephemeral port at runtime).  The
  fetcher is injectable so tests never touch the network — and so the SSRF
  surface (the AS fetching an attacker-supplied URL!) is explicit.

- **Deprecated-DCR fallback (RFC 7591).**  Retained for compatibility, but
  registrations missing ``application_type`` are REJECTED with a teaching
  error: SEP-837 makes ``application_type`` mandatory for MCP clients
  because OIDC registries default to ``"web"``, which then refuses the
  loopback redirect URIs native clients need.

- **RFC 8707 resource indicators -> audience binding.**  The ``resource``
  parameter from the authorization request is recorded with the code,
  demanded again (consistently) at the token endpoint, and minted into the
  access token's ``aud`` claim — closing the loop that
  :class:`modern.auth.bearer.TokenVerifier` checks on every MCP request.

- **RFC 9207 ``iss`` on EVERY authorization response** (success and error):
  the mix-up-attack countermeasure.  The client recorded which issuer it
  sent the user to; the ``iss`` parameter lets it verify the answer came
  from that same issuer before shipping the code to a token endpoint.

- **Single-use, short-lived authorization codes** (60 s, burned on first
  redemption attempt) and **refresh-token rotation** — OAuth 2.1 §4.3.1
  makes rotation a MUST for public clients, so a replayed refresh token is
  dead on arrival.

Tokens are RS256 JWTs signed with a keypair generated at process start; the
public half is served as a JWKS at ``{issuer}/jwks.json`` and handed
directly to the in-process :class:`~modern.auth.bearer.TokenVerifier`.
15-minute expiry: short-lived access tokens are the spec's SHOULD, with
refresh tokens carrying the long-term grant.

Spec references: MCP 2026-07-28 basic/authorization (+ authorization-server-
discovery, client-registration, security-considerations subpages), OAuth 2.1
(draft-ietf-oauth-v2-1-13), RFC 8414, RFC 8707, RFC 9207, RFC 8252 §7.3,
SEP-837, SEP-2352 (issuer-keyed credentials, the client-side dual).
"""

import base64
import hashlib
import hmac
import html
import secrets
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from modern.auth.metadata import DEFAULT_SCOPES

#: Async callable that fetches a CIMD document: url -> parsed JSON.  It is a
#: constructor parameter (1) so tests can stub it with canned documents and
#: (2) because fetching an attacker-chosen URL is an SSRF vector the spec
#: calls out — a production AS would pin schemes, block private IP ranges,
#: and respect HTTP cache headers in this function.
CimdFetcher = Callable[[str], Awaitable[Any]]

#: Hosts whose http redirect URIs match port-agnostically (RFC 8252 §7.3).
#: The RFC recommends the loopback IP literals; we include "localhost"
#: pragmatically because the spec's own CIMD example registers
#: ``http://localhost:3000/callback``.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

_ACCESS_TOKEN_TTL_SECONDS = 15 * 60  # short-lived per spec SHOULD
_AUTH_CODE_TTL_SECONDS = 60  # codes are a one-shot, minutes-scale credential


# ---------------------------------------------------------------------------
# Internal control-flow errors
# ---------------------------------------------------------------------------


class _ClientValidationError(Exception):
    """Authorization request failed BEFORE the redirect URI was trusted.

    OAuth 2.1 §7.12.2: the AS MUST NOT redirect to a URI it has not
    validated against the client's registration — an open redirector is
    exactly what that would build.  So unknown clients and bad redirect URIs
    get a direct 400 response, never a redirect.
    """

    def __init__(self, error: str, description: str) -> None:
        super().__init__(description)
        self.error = error
        self.description = description


class _AuthorizeError(Exception):
    """Authorization request failed AFTER the redirect URI was validated.

    These errors ARE delivered by redirect (with ``state`` and — per RFC
    9207, which applies to error responses too — ``iss``), because the
    redirect target is now known to belong to the legitimate client.
    """

    def __init__(self, error: str, description: str) -> None:
        super().__init__(description)
        self.error = error
        self.description = description


# ---------------------------------------------------------------------------
# In-memory records
# ---------------------------------------------------------------------------


@dataclass
class _RegisteredClient:
    """A client created through the deprecated-DCR fallback."""

    client_id: str
    client_name: str
    redirect_uris: list[str]
    application_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _AuthorizationCode:
    """One single-use authorization code and everything bound to it.

    The token endpoint re-checks each binding: the SAME client, the SAME
    redirect URI, the SAME resource, and possession of the PKCE verifier.
    A code is a claim ticket, not a bearer credential.
    """

    client_id: str
    redirect_uri: str
    code_challenge: str
    scope: str
    resource: str
    expires_at: float
    used: bool = False


@dataclass
class _RefreshToken:
    client_id: str
    scope: str
    resource: str


class DemoAuthorizationServer:
    """The in-memory demo AS: a bag of Starlette routes plus signing keys.

    ``issuer`` is the AS's identity — the exact string that appears in RFC
    8414 metadata, in the RFC 9207 ``iss`` parameter, and in every token's
    ``iss`` claim.  Clients key their stored credentials by it (SEP-2352).
    For the demo it is ``{server base URL}/auth``, i.e. the AS is co-hosted
    with the resource server, which the spec explicitly permits.
    """

    def __init__(
        self,
        *,
        issuer: str,
        auto_approve: bool = True,
        cimd_fetcher: CimdFetcher | None = None,
        scopes_supported: Sequence[str] = DEFAULT_SCOPES,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        #: Path prefix the AS endpoints live under, derived from the issuer
        #: (e.g. issuer http://127.0.0.1:8080/auth -> prefix "/auth").
        self._prefix = urlsplit(self._issuer).path
        self._auto_approve = auto_approve
        self._cimd_fetcher = cimd_fetcher or _default_cimd_fetcher
        self._scopes_supported = tuple(scopes_supported)

        # RS256 keypair, generated fresh at startup.  Educational trade-off:
        # a restart invalidates every outstanding token (verification fails
        # against the new JWKS), which is actually a nice property for a toy.
        self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._kid = uuid4().hex

        # All state is process-local dicts — the "in-memory" in the name.
        self._clients: dict[str, _RegisteredClient] = {}
        self._codes: dict[str, _AuthorizationCode] = {}
        self._refresh_tokens: dict[str, _RefreshToken] = {}

    # -- public wiring ------------------------------------------------------

    @property
    def issuer(self) -> str:
        return self._issuer

    def jwks(self) -> dict[str, Any]:
        """The public JWKS — what a resource server verifies tokens against."""
        public_jwk = dict(RSAAlgorithm.to_jwk(self._private_key.public_key(), as_dict=True))
        public_jwk.update({"kid": self._kid, "use": "sig", "alg": "RS256"})
        return {"keys": [public_jwk]}

    def routes(self) -> list[Route]:
        """Starlette routes for the whole AS, ready to mount on the app.

        The RFC 8414 metadata is served at BOTH well-known forms: the
        path-inserted form (``/.well-known/oauth-authorization-server/auth``)
        is the one RFC 8414 §3.1 actually specifies for an issuer with a
        path component — and the first URL spec-conformant clients try —
        while the host-root form is served as a convenience for simpler
        clients.  MCP uses the DEFAULT well-known suffix; it defines no
        application-specific one.
        """
        metadata_routes = [
            Route(
                "/.well-known/oauth-authorization-server" + self._prefix,
                self._metadata_endpoint,
                methods=["GET"],
            ),
            Route(
                "/.well-known/oauth-authorization-server",
                self._metadata_endpoint,
                methods=["GET"],
            ),
        ]
        if not self._prefix:  # issuer at host root: both forms are one path
            metadata_routes = metadata_routes[1:]
        return [
            *metadata_routes,
            Route(f"{self._prefix}/authorize", self._authorize_endpoint, methods=["GET"]),
            Route(f"{self._prefix}/consent", self._consent_endpoint, methods=["POST"]),
            Route(f"{self._prefix}/token", self._token_endpoint, methods=["POST"]),
            Route(f"{self._prefix}/register", self._register_endpoint, methods=["POST"]),
            Route(f"{self._prefix}/jwks.json", self._jwks_endpoint, methods=["GET"]),
        ]

    # -- RFC 8414 metadata ---------------------------------------------------

    def _metadata_endpoint(self, _request: Request) -> JSONResponse:
        return JSONResponse(
            {
                # RFC 8414 §3.3: clients MUST verify this equals the issuer
                # they derived the well-known URL from, else discard the
                # document — the check that stops an attacker's well-known
                # endpoint from impersonating an honest issuer.
                "issuer": self._issuer,
                "authorization_endpoint": f"{self._issuer}/authorize",
                "token_endpoint": f"{self._issuer}/token",
                "registration_endpoint": f"{self._issuer}/register",
                "jwks_uri": f"{self._issuer}/jwks.json",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                # S256 only.  Clients MUST refuse to proceed when this field
                # is absent — advertising it is not optional politeness.
                "code_challenge_methods_supported": ["S256"],
                # Public clients: no secret at the token endpoint.
                "token_endpoint_auth_methods_supported": ["none"],
                # RFC 9207 §2.3: we emit `iss` on authorization responses,
                # therefore we MUST say so — clients use this flag to REJECT
                # responses that arrive without `iss`.
                "authorization_response_iss_parameter_supported": True,
                # CIMD (SEP-991): URL-shaped client_ids welcome; DCR below is
                # the deprecated fallback.
                "client_id_metadata_document_supported": True,
                "scopes_supported": list(self._scopes_supported),
            }
        )

    def _jwks_endpoint(self, _request: Request) -> JSONResponse:
        return JSONResponse(self.jwks())

    # -- client resolution (CIMD + DCR store) --------------------------------

    async def _resolve_client(self, client_id: str | None) -> tuple[str, str, list[str]]:
        """Resolve ``client_id`` -> (client_id, display name, redirect_uris).

        Two id namespaces coexist: URL-shaped ids are CIMD documents to
        fetch and validate; everything else must be a client the deprecated
        DCR endpoint registered earlier.
        """
        if not client_id:
            raise _ClientValidationError("invalid_request", "client_id is required")
        if "://" in client_id:
            return await self._resolve_cimd_client(client_id)
        stored = self._clients.get(client_id)
        if stored is None:
            raise _ClientValidationError("invalid_client", f"unknown client_id {client_id!r}")
        return stored.client_id, stored.client_name, list(stored.redirect_uris)

    async def _resolve_cimd_client(self, client_id: str) -> tuple[str, str, list[str]]:
        """Fetch and validate a Client ID Metadata Document.

        The validations here are the CIMD MUSTs for authorization servers:
        https+path URL shape, well-formed JSON object, required fields, and
        — the crux — ``client_id`` inside the document EXACTLY equal to the
        URL it was fetched from.  Without that self-reference check, anyone
        who can host a JSON file could claim to BE another client by copying
        its metadata (the document would be valid, but for a different id).
        """
        url = urlsplit(client_id)
        if url.scheme != "https" or not url.netloc or url.path in ("", "/"):
            raise _ClientValidationError(
                "invalid_client",
                "CIMD client_id must be an https URL with a path component "
                "(e.g. https://app.example.com/client-metadata.json)",
            )
        try:
            document = await self._cimd_fetcher(client_id)
        except Exception as exc:
            raise _ClientValidationError(
                "invalid_client", f"failed to fetch client metadata document: {exc}"
            ) from exc
        if not isinstance(document, dict):
            raise _ClientValidationError(
                "invalid_client", "client metadata document must be a JSON object"
            )
        missing = [k for k in ("client_id", "client_name", "redirect_uris") if k not in document]
        if missing:
            raise _ClientValidationError(
                "invalid_client",
                "client metadata document is missing required field(s): " + ", ".join(missing),
            )
        if document["client_id"] != client_id:
            raise _ClientValidationError(
                "invalid_client",
                "client metadata document client_id does not exactly match the document URL "
                f"(got {document['client_id']!r}, expected {client_id!r})",
            )
        redirect_uris = document["redirect_uris"]
        if not isinstance(redirect_uris, list) or not all(
            isinstance(uri, str) for uri in redirect_uris
        ):
            raise _ClientValidationError(
                "invalid_client", "client metadata document redirect_uris must be a string array"
            )
        client_name = document["client_name"]
        return client_id, str(client_name), list(redirect_uris)

    # -- GET /authorize -------------------------------------------------------

    async def _authorize_endpoint(self, request: Request) -> Response:
        params = dict(request.query_params)

        # Phase 1: establish WHO is asking and WHERE we may redirect.
        # Failures here are 400s, never redirects (open-redirect defense).
        try:
            client_id, client_name, registered_uris = await self._resolve_client(
                params.get("client_id")
            )
            redirect_uri = _validate_redirect_uri(params.get("redirect_uri"), registered_uris)
        except _ClientValidationError as exc:
            return JSONResponse(
                {"error": exc.error, "error_description": exc.description}, status_code=400
            )

        # Phase 2: validate the request proper.  The redirect target is now
        # trusted, so errors flow back through it — WITH `state` (the
        # client's CSRF token) and `iss` (RFC 9207 applies to error
        # responses too: a client must be able to reject an error injected
        # by a different issuer without acting on it).
        try:
            scope = self._validate_authorization_request(params)
        except _AuthorizeError as exc:
            return self._error_redirect(redirect_uri, exc, params.get("state"))

        if not self._auto_approve:
            return self._consent_page(params, client_id, client_name, redirect_uri, scope)
        return self._issue_code_redirect(
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=params["code_challenge"],
            scope=scope,
            resource=params["resource"],
            state=params.get("state"),
        )

    def _validate_authorization_request(self, params: dict[str, str]) -> str:
        """Enforce the OAuth 2.1 + MCP MUSTs on an authorization request.

        Returns the effective scope string.  Raises :class:`_AuthorizeError`
        (delivered by redirect) on any violation.
        """
        if params.get("response_type") != "code":
            raise _AuthorizeError(
                "unsupported_response_type",
                "only response_type=code is supported (OAuth 2.1 removed implicit)",
            )
        # PKCE is REQUIRED, and only S256.  OAuth 2.1 folds PKCE into the
        # core flow; "plain" survives in the RFC for constrained devices but
        # is worthless against an attacker who can read the authorization
        # request, so we reject it as a matter of principle AND pedagogy.
        if not params.get("code_challenge"):
            raise _AuthorizeError(
                "invalid_request",
                "code_challenge is required: OAuth 2.1 makes PKCE mandatory for the "
                "authorization code grant",
            )
        if params.get("code_challenge_method") != "S256":
            raise _AuthorizeError(
                "invalid_request",
                "code_challenge_method must be S256 ('plain' offers no protection and "
                "this server rejects it)",
            )
        # RFC 8707: MCP clients MUST send `resource` in the authorization
        # request.  We hard-require it because the whole audience-binding
        # lesson collapses without it — the token would have no `aud`.
        if not params.get("resource"):
            raise _AuthorizeError(
                "invalid_target",
                "resource parameter is required (RFC 8707): MCP clients MUST identify "
                "the MCP server the token is for, using its canonical URI",
            )
        # Scope: absent means "AS default".  We grant everything we support,
        # matching the client-side rule that an omitted scope parameter is
        # used when neither the challenge nor PRM named scopes.
        return params.get("scope") or " ".join(self._scopes_supported)

    def _issue_code_redirect(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        scope: str,
        resource: str,
        state: str | None,
    ) -> RedirectResponse:
        """Mint a single-use authorization code and redirect back."""
        code = secrets.token_urlsafe(32)
        self._codes[code] = _AuthorizationCode(
            client_id=client_id,
            # Exact-match at the token endpoint uses the URI as REQUESTED
            # (not the registered pattern it matched): OAuth 2.1 binds the
            # code to the redirect_uri value used in the authorization
            # request.
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            scope=scope,
            resource=resource,
            expires_at=time.time() + _AUTH_CODE_TTL_SECONDS,
        )
        query: dict[str, str] = {"code": code}
        if state is not None:
            query["state"] = state
        # RFC 9207 (SEP-2468): `iss` tells the client which AS is answering.
        # The client compares it — exact string match, no URL normalization —
        # against the issuer it recorded before redirecting the user, which
        # is the defense against authorization-server mix-up attacks.
        query["iss"] = self._issuer
        return RedirectResponse(_append_query(redirect_uri, query), status_code=302)

    def _error_redirect(
        self, redirect_uri: str, error: _AuthorizeError, state: str | None
    ) -> RedirectResponse:
        query: dict[str, str] = {"error": error.error, "error_description": error.description}
        if state is not None:
            query["state"] = state
        # `iss` on ERROR responses too: without it, an attacker AS could
        # inject fake errors that the client cannot attribute (RFC 9207 §2).
        query["iss"] = self._issuer
        return RedirectResponse(_append_query(redirect_uri, query), status_code=302)

    # -- consent (the non-auto-approve mode) ----------------------------------

    def _consent_page(
        self,
        params: dict[str, str],
        client_id: str,
        client_name: str,
        redirect_uri: str,
        scope: str,
    ) -> HTMLResponse:
        """A minimal consent form, POSTing the request back to /consent.

        The spec's CIMD security guidance drives the display choices: the
        AS MUST clearly show the redirect URI hostname (localhost-redirect
        impersonation: an attacker reuses a legit client's CIMD URL with
        their own loopback port) and SHOULD prominently display the client
        identity.  A production consent page would also carry CSRF
        protection, ``frame-ancestors 'none'``, and __Host- cookies — all
        deliberately out of scope for the toy.
        """
        hidden = "".join(
            f'<input type="hidden" name="{html.escape(k, quote=True)}" '
            f'value="{html.escape(v, quote=True)}">'
            for k, v in params.items()
        )
        page = f"""<!DOCTYPE html>
<html><head><title>Demo AS — Consent</title></head><body>
<h1>Authorize {html.escape(client_name)}?</h1>
<p><strong>Client:</strong> <code>{html.escape(client_id)}</code></p>
<p><strong>Redirects to:</strong> <code>{html.escape(redirect_uri)}</code></p>
<p><strong>Requested scopes:</strong> <code>{html.escape(scope)}</code></p>
<p><em>Educational demo authorization server — never use in production.</em></p>
<form method="post" action="{html.escape(self._prefix)}/consent">
{hidden}
<button name="decision" value="approve">Approve</button>
<button name="decision" value="deny">Deny</button>
</form>
</body></html>"""
        return HTMLResponse(page)

    async def _consent_endpoint(self, request: Request) -> Response:
        form = await request.form()
        params = {k: v for k, v in form.items() if isinstance(v, str)}
        # Re-validate EVERYTHING from scratch: the form round-tripped through
        # the browser, so every field is untrusted user input again.
        try:
            client_id, _client_name, registered_uris = await self._resolve_client(
                params.get("client_id")
            )
            redirect_uri = _validate_redirect_uri(params.get("redirect_uri"), registered_uris)
        except _ClientValidationError as exc:
            return JSONResponse(
                {"error": exc.error, "error_description": exc.description}, status_code=400
            )
        try:
            scope = self._validate_authorization_request(params)
        except _AuthorizeError as exc:
            return self._error_redirect(redirect_uri, exc, params.get("state"))
        if params.get("decision") != "approve":
            return self._error_redirect(
                redirect_uri,
                _AuthorizeError("access_denied", "the resource owner denied the request"),
                params.get("state"),
            )
        return self._issue_code_redirect(
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=params["code_challenge"],
            scope=scope,
            resource=params["resource"],
            state=params.get("state"),
        )

    # -- POST /token -----------------------------------------------------------

    async def _token_endpoint(self, request: Request) -> JSONResponse:
        form = await request.form()
        params = {k: v for k, v in form.items() if isinstance(v, str)}
        grant_type = params.get("grant_type")
        try:
            if grant_type == "authorization_code":
                payload = self._redeem_authorization_code(params)
            elif grant_type == "refresh_token":
                payload = self._redeem_refresh_token(params)
            else:
                raise _TokenError(
                    "unsupported_grant_type",
                    "grant_type must be authorization_code or refresh_token",
                )
        except _TokenError as exc:
            return JSONResponse(
                {"error": exc.error, "error_description": exc.description},
                status_code=400,
                # OAuth 2.1 §3.2.3: token responses (including errors) carry
                # credentials or hints about them — never cacheable.
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    def _redeem_authorization_code(self, params: dict[str, str]) -> dict[str, Any]:
        """authorization_code grant: every binding on the code is re-checked."""
        code = params.get("code")
        if not code:
            raise _TokenError("invalid_request", "code is required")
        record = self._codes.get(code)
        if record is None:
            raise _TokenError("invalid_grant", "unknown authorization code")
        # Single-use, burned on FIRST redemption attempt (even a failed one):
        # OAuth 2.1 treats a replayed code as evidence of interception, and
        # a code that survives failed attempts gives an attacker retries.
        if record.used:
            raise _TokenError("invalid_grant", "authorization code has already been used")
        record.used = True
        if time.time() > record.expires_at:
            raise _TokenError(
                "invalid_grant",
                f"authorization code expired (codes live {_AUTH_CODE_TTL_SECONDS}s)",
            )
        if params.get("client_id") != record.client_id:
            raise _TokenError("invalid_grant", "code was issued to a different client_id")
        # redirect_uri: EXACT string match with the value from the
        # authorization request — the classic code-injection defense.
        if params.get("redirect_uri") != record.redirect_uri:
            raise _TokenError(
                "invalid_grant",
                "redirect_uri does not exactly match the authorization request",
            )
        # PKCE proof-of-possession: S256(code_verifier) must reproduce the
        # code_challenge sent (through the browser!) in the authorization
        # request.  Only the party that GENERATED the verifier can do this —
        # a stolen code alone is useless.  Constant-time compare out of
        # cryptographic good manners (the challenge isn't secret, but the
        # habit is worth teaching).
        verifier = params.get("code_verifier")
        if not verifier:
            raise _TokenError("invalid_request", "code_verifier is required (PKCE)")
        if not hmac.compare_digest(_s256_challenge(verifier), record.code_challenge):
            raise _TokenError(
                "invalid_grant",
                "PKCE verification failed: code_verifier does not match code_challenge",
            )
        # RFC 8707: the token request MUST repeat `resource`, and it must be
        # the SAME resource the code was authorized for — a client can't get
        # a code approved for server A and redeem it into a token for B.
        resource = params.get("resource")
        if not resource:
            raise _TokenError(
                "invalid_target", "resource parameter is required (RFC 8707) on token requests"
            )
        if resource != record.resource:
            raise _TokenError(
                "invalid_target",
                "resource does not match the resource from the authorization request",
            )
        return self._token_response(
            client_id=record.client_id, scope=record.scope, resource=record.resource
        )

    def _redeem_refresh_token(self, params: dict[str, str]) -> dict[str, Any]:
        """refresh_token grant with rotation (MUST for public clients)."""
        token = params.get("refresh_token")
        if not token:
            raise _TokenError("invalid_request", "refresh_token is required")
        # pop() IS the rotation: the presented token is consumed whether or
        # not everything else checks out.  A replayed (already-rotated)
        # refresh token therefore fails — OAuth 2.1 §4.3.1's detection
        # mechanism for stolen refresh tokens.
        record = self._refresh_tokens.pop(token, None)
        if record is None:
            raise _TokenError("invalid_grant", "unknown or already-rotated refresh token")
        if params.get("client_id") != record.client_id:
            raise _TokenError("invalid_grant", "refresh token was issued to a different client")
        resource = params.get("resource")
        if resource is not None and resource != record.resource:
            raise _TokenError(
                "invalid_target", "resource does not match the original grant's resource"
            )
        return self._token_response(
            client_id=record.client_id, scope=record.scope, resource=record.resource
        )

    def _token_response(self, *, client_id: str, scope: str, resource: str) -> dict[str, Any]:
        """Mint the access token (RS256 JWT) + a fresh rotated refresh token."""
        now = int(time.time())
        claims = {
            "iss": self._issuer,
            # No user database: everybody is the demo librarian.  `sub` is
            # the stable subject identifier a real AS would key to a user.
            "sub": "demo-user",
            # RFC 8707 -> RFC 9068: the resource from the (twice-validated)
            # `resource` parameter becomes the audience.  A list, because
            # `aud` is allowed to be multi-valued; the resource server only
            # requires that ITS canonical URI be contained.
            "aud": [resource],
            "scope": scope,
            # Matches the library's patron allowlist demos.
            "email": "librarian@example.com",
            "iat": now,
            "exp": now + _ACCESS_TOKEN_TTL_SECONDS,
            # Unique token id — what a revocation list or replay cache keys on.
            "jti": uuid4().hex,
        }
        access_token = jwt.encode(
            claims, self._private_key, algorithm="RS256", headers={"kid": self._kid}
        )
        refresh_token = secrets.token_urlsafe(32)
        self._refresh_tokens[refresh_token] = _RefreshToken(
            client_id=client_id, scope=scope, resource=resource
        )
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": _ACCESS_TOKEN_TTL_SECONDS,
            "scope": scope,
            "refresh_token": refresh_token,
        }

    # -- POST /register (deprecated DCR fallback) ------------------------------

    async def _register_endpoint(self, request: Request) -> JSONResponse:
        """RFC 7591 Dynamic Client Registration — DEPRECATED in MCP 2026-07-28.

        Kept as the fallback for authorization servers (and clients) that do
        not speak CIMD yet.  Two teaching enforcement points:

        - ``application_type`` is REQUIRED (SEP-837).  Under OIDC dynamic
          registration an omitted value defaults to ``"web"``, and web
          clients may not register the loopback/custom-scheme redirect URIs
          that native MCP clients (CLIs, desktop apps) depend on — a silent
          foot-gun the spec now closes by making the field mandatory.
        - clients here are PUBLIC: ``token_endpoint_auth_method`` is
          ``none`` and no secret is issued.  Native apps cannot keep a
          secret, so PKCE is their proof-of-possession instead.
        """
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            return JSONResponse(
                {
                    "error": "invalid_client_metadata",
                    "error_description": "registration body must be a JSON object",
                },
                status_code=400,
            )
        if not isinstance(body, dict):
            return JSONResponse(
                {
                    "error": "invalid_client_metadata",
                    "error_description": "registration body must be a JSON object",
                },
                status_code=400,
            )
        metadata: dict[str, Any] = {str(key): value for key, value in body.items()}
        if "application_type" not in metadata:
            return JSONResponse(
                {
                    "error": "invalid_client_metadata",
                    "error_description": (
                        "application_type is required: MCP 2026-07-28 (SEP-837) requires "
                        "clients to declare an application_type during dynamic client "
                        "registration — native apps (CLI, desktop, loopback-redirect web) "
                        "SHOULD use 'native', remote browser-based apps SHOULD use 'web'. "
                        "Omitting it defaults to 'web' under OIDC registration, which "
                        "then rejects the loopback redirect URIs native clients need. "
                        "Note: DCR itself is deprecated — prefer Client ID Metadata "
                        "Documents (client_id_metadata_document_supported: true)."
                    ),
                },
                status_code=400,
            )
        redirect_uris = metadata.get("redirect_uris")
        if (
            not isinstance(redirect_uris, list)
            or not redirect_uris
            or not all(isinstance(uri, str) for uri in redirect_uris)
        ):
            return JSONResponse(
                {
                    "error": "invalid_redirect_uri",
                    "error_description": "redirect_uris must be a non-empty array of strings",
                },
                status_code=400,
            )

        client = _RegisteredClient(
            client_id=f"demo-client-{secrets.token_urlsafe(16)}",
            client_name=str(metadata.get("client_name", "Unnamed MCP client")),
            redirect_uris=[str(uri) for uri in redirect_uris],
            application_type=str(metadata["application_type"]),
            metadata=metadata,
        )
        self._clients[client.client_id] = client
        return JSONResponse(
            {
                "client_id": client.client_id,
                "client_name": client.client_name,
                "redirect_uris": client.redirect_uris,
                "application_type": client.application_type,
                "grant_types": metadata.get("grant_types", ["authorization_code"]),
                # Public client: no client_secret in the response, ever.
                "token_endpoint_auth_method": "none",
                "client_id_issued_at": int(time.time()),
            },
            status_code=201,
        )


class _TokenError(Exception):
    """A token-endpoint failure -> RFC 6749 §5.2 error JSON (HTTP 400)."""

    def __init__(self, error: str, description: str) -> None:
        super().__init__(description)
        self.error = error
        self.description = description


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _s256_challenge(verifier: str) -> str:
    """PKCE S256: BASE64URL(SHA256(ascii(verifier))), unpadded (RFC 7636 §4.2)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _append_query(url: str, params: dict[str, str]) -> str:
    """Append query parameters to a redirect URI that may already have some."""
    separator = "&" if urlsplit(url).query else "?"
    return f"{url}{separator}{urlencode(params)}"


def _is_loopback_redirect(uri_parts: Any) -> bool:
    """RFC 8252 §7.3 loopback: http scheme + loopback host."""
    return uri_parts.scheme == "http" and (uri_parts.hostname or "") in _LOOPBACK_HOSTS


def _redirect_uri_matches(registered: str, requested: str) -> bool:
    """Match a requested redirect URI against one registered value.

    Exact string comparison is the rule (OAuth 2.1 §7.12.2 — pattern
    matching built every historical open-redirect), with ONE carve-out:
    RFC 8252 §7.3 requires the AS to ignore the PORT for http loopback
    redirects, because native apps bind whatever ephemeral port the OS
    hands them at runtime.  Everything else — scheme, host, path, query —
    still matches exactly even for loopback.
    """
    if registered == requested:
        return True
    reg, req = urlsplit(registered), urlsplit(requested)
    if not (_is_loopback_redirect(reg) and _is_loopback_redirect(req)):
        return False
    return (
        reg.scheme == req.scheme
        and reg.hostname == req.hostname
        and reg.path == req.path
        and reg.query == req.query
    )


def _validate_redirect_uri(requested: str | None, registered_uris: list[str]) -> str:
    """Validate the request's redirect_uri against the registered set."""
    if not requested:
        raise _ClientValidationError("invalid_request", "redirect_uri is required")
    if not any(_redirect_uri_matches(registered, requested) for registered in registered_uris):
        raise _ClientValidationError(
            "invalid_request",
            "redirect_uri is not registered for this client (exact match required; "
            "http loopback redirects match port-agnostically per RFC 8252 §7.3)",
        )
    return requested


async def _default_cimd_fetcher(url: str) -> Any:
    """Fetch a CIMD document over the network (the non-test default).

    A production AS hardens this function: https-only (already enforced by
    the caller), SSRF mitigations (block private/reserved IP ranges, no
    redirects to internal hosts), response size limits, and HTTP-cache-
    header-respecting caching.  The demo keeps it minimal and visible.
    """
    import httpx  # deferred: tests stub the fetcher and never import this

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()
        return response.json()
