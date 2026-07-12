"""
Bearer-token verification for the MCP 2026-07-28 resource server.

In the modern authorization model the MCP server is an OAuth 2.1 RESOURCE
SERVER and nothing more: it never issues tokens, never sees passwords, and
never redirects browsers.  Its entire job on the authorization side is to
answer one question per HTTP request — "is this ``Authorization: Bearer``
token valid *for me*?" — and to answer it with the paranoia the spec
mandates (MCP 2026-07-28 authorization, "Access token usage and
validation"):

- **Audience binding (RFC 8707 / RFC 9068) — the core token rule.**  The
  client sent a ``resource`` parameter naming this server's canonical URI in
  both the authorization and token requests, so the authorization server
  minted the token with that URI in its ``aud`` claim.  We MUST reject any
  token whose audience does not contain our canonical resource URI.  This is
  what makes stolen-token replay against a *different* MCP server fail, and
  it is the normative anti-pattern the spec calls "token passthrough": a
  server MUST NOT accept tokens that were not explicitly issued for it, even
  tokens from the very same authorization server.

- **Standard JWT hygiene (OAuth 2.1 §5.2).**  ``exp`` (expiry) and ``nbf``
  (not-before) MUST be enforced; ``iss`` MUST exactly match the issuer we
  trust (the one advertised in our Protected Resource Metadata); the
  signature MUST verify against a key we obtained out-of-band (the demo AS's
  JWKS), and the algorithm MUST come from an explicit allowlist — accepting
  whatever ``alg`` the token header claims (especially ``none``) is the
  classic JWT downgrade attack.

- **Scopes.**  RFC 9068-style tokens carry a space-separated ``scope``
  string; some issuers (notably Azure AD) use an ``scp`` list instead.  We
  parse both into a ``frozenset`` so authorization checks upstream are set
  operations, not string parsing.

Failures raise :class:`InvalidTokenError` with a human-readable ``reason``.
The HTTP layer maps that to ``401 Unauthorized`` plus a ``WWW-Authenticate``
challenge (built by :mod:`modern.auth.metadata`) — the spec requires 401 for
invalid/expired tokens, reserving 403 for valid-but-insufficient scope.
Note this is deliberately NOT a JSON-RPC ``McpError``: authorization happens
at the HTTP envelope, before the request body is ever parsed as MCP.

Spec references: MCP 2026-07-28 basic/authorization (§Access Token Usage,
§Security Considerations), RFC 6750, RFC 8707 §2, RFC 9068, OAuth 2.1 §5.2.
"""

from dataclasses import dataclass, field
from typing import Any, cast

import jwt

# ---------------------------------------------------------------------------
# Errors and the verified identity
# ---------------------------------------------------------------------------


class InvalidTokenError(Exception):
    """A bearer token failed verification.

    ``reason`` is safe to log server-side but SHOULD NOT be echoed verbatim
    into the 401 response body — RFC 6750 keeps error detail out of the
    challenge beyond the registered ``error`` codes, and detailed failure
    reasons ("signature mismatch" vs "expired") are an oracle for attackers
    probing forged tokens.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Principal:
    """The authenticated identity extracted from a verified access token.

    This is what the dispatcher and handlers see instead of the raw JWT —
    once verification succeeds, downstream code reasons about *who* is
    calling and *what they may do* (``scopes``), never about token bytes.
    ``claims`` keeps the full verified payload for anything unusual
    (auditing, the ``jti`` for revocation lists, ...).
    """

    subject: str
    email: str | None
    scopes: frozenset[str] = field(default_factory=frozenset)
    claims: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# TokenVerifier
# ---------------------------------------------------------------------------


class TokenVerifier:
    """Validates ``Authorization: Bearer`` JWTs for one resource server.

    Two key-material modes, exactly one of which must be configured:

    - ``jwks``: an in-memory JWKS document (``{"keys": [...]}``) holding the
      authorization server's RS256 public key(s).  This is how the demo AS
      wires itself to the resource server — in production the RS would fetch
      ``jwks_uri`` from the AS metadata and cache it.
    - ``hs_secret``: an HS256 shared secret, for deployments where AS and RS
      are the same process and asymmetric keys are overkill.

    The mode fixes the algorithm allowlist.  We never take the allowlist
    from the token itself: the ``alg`` header is attacker-controlled, and
    honoring it enables both the ``none`` bypass and RS256->HS256 confusion
    (verifying an HMAC forged with the *public* key).
    """

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks: dict[str, Any] | None = None,
        hs_secret: bytes | None = None,
        leeway_seconds: float = 0.0,
    ) -> None:
        if (jwks is None) == (hs_secret is None):
            msg = "TokenVerifier requires exactly one of 'jwks' (RS256) or 'hs_secret' (HS256)"
            raise ValueError(msg)
        #: Trusted issuer — MUST equal the ``iss`` claim exactly (string
        #: comparison, no URL normalization: RFC 8414 issuers are opaque
        #: identifiers, and normalizing would let
        #: ``https://as.example/`` impersonate ``https://as.example``).
        self._issuer = issuer
        #: Canonical resource URI of THIS MCP server (RFC 8707 §2) — the
        #: value clients put in the ``resource`` parameter and the AS put in
        #: ``aud``.
        self._audience = audience
        self._hs_secret = hs_secret
        self._jwk_set = jwt.PyJWKSet.from_dict(jwks) if jwks is not None else None
        self._algorithms = ("HS256",) if hs_secret is not None else ("RS256",)
        self._leeway = leeway_seconds

    # -- key selection ------------------------------------------------------

    def _resolve_key(self, header: dict[str, Any]) -> Any:
        """Pick the verification key for this token's header.

        JWKS mode matches the header ``kid`` against the key set; a token
        without ``kid`` is accepted only when the set is unambiguous (single
        key).  An unknown ``kid`` is a verification failure, NOT a trigger to
        refetch arbitrary keys — key material comes from configuration, never
        from the token.
        """
        if self._hs_secret is not None:
            return self._hs_secret
        if self._jwk_set is None:  # unreachable: __init__ enforces one mode
            raise InvalidTokenError("verifier has no key material configured")
        keys = self._jwk_set.keys
        kid = header.get("kid")
        if kid is None:
            if len(keys) == 1:
                return keys[0].key
            raise InvalidTokenError("token header has no 'kid' and the JWKS holds multiple keys")
        for jwk in keys:
            if jwk.key_id == kid:
                return jwk.key
        raise InvalidTokenError(f"token 'kid' {kid!r} not found in the configured JWKS")

    # -- verification -------------------------------------------------------

    def verify(self, token: str) -> Principal:
        """Verify ``token`` and return the authenticated :class:`Principal`.

        Enforced, in order: well-formedness, algorithm allowlist, signature,
        ``exp``/``nbf`` timing, exact ``iss`` match, and RFC 8707 audience
        containment.  Any failure raises :class:`InvalidTokenError` with the
        reason — the HTTP layer turns every one of them into a 401.
        """
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise InvalidTokenError(f"malformed JWT: {exc}") from exc

        # Explicit allowlist check before decoding.  jwt.decode() would also
        # reject a foreign alg, but checking here yields a precise reason and
        # documents that the allowlist is OURS, not the token's.  "none" can
        # never appear in the allowlist by construction.
        alg = header.get("alg")
        if alg not in self._algorithms:
            raise InvalidTokenError(
                f"token algorithm {alg!r} is not in the allowlist {list(self._algorithms)}"
            )

        key = self._resolve_key(header)

        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=list(self._algorithms),
                issuer=self._issuer,
                leeway=self._leeway,
                options={
                    # Presence requirements: a token without exp never
                    # expires, a token without aud can't be audience-bound —
                    # both violate the MUSTs above, so absence is rejection.
                    "require": ["exp", "iss", "aud"],
                    # Audience containment is checked manually below —
                    # PyJWT's aud check works too, but doing it ourselves
                    # makes the RFC 8707 rule visible instead of implicit.
                    "verify_aud": False,
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise InvalidTokenError("token has expired (exp)") from exc
        except jwt.ImmatureSignatureError as exc:
            raise InvalidTokenError("token is not yet valid (nbf)") from exc
        except jwt.InvalidIssuerError as exc:
            raise InvalidTokenError(
                f"issuer mismatch: token was not issued by {self._issuer!r}"
            ) from exc
        except jwt.MissingRequiredClaimError as exc:
            raise InvalidTokenError(f"missing required claim: {exc}") from exc
        except jwt.InvalidSignatureError as exc:
            raise InvalidTokenError("signature verification failed") from exc
        except jwt.InvalidTokenError as exc:  # PyJWT's base class, catch last
            raise InvalidTokenError(f"invalid token: {exc}") from exc

        # RFC 8707 audience binding — the draft's core token rule.  ``aud``
        # may be a single string or a list; the canonical resource URI of
        # THIS server MUST be among the audiences.  Comparison is exact
        # string equality: canonical URIs are already normalized at mint
        # time, and fuzzy matching here would re-open the passthrough hole.
        aud = claims.get("aud")
        audiences: list[Any] = (
            [aud] if isinstance(aud, str) else list(aud) if isinstance(aud, list) else []
        )
        if self._audience not in audiences:
            raise InvalidTokenError(
                f"audience mismatch: token aud {audiences!r} does not include "
                f"this server's canonical resource URI {self._audience!r}"
            )

        return Principal(
            subject=str(claims.get("sub", "")),
            email=claims.get("email") if isinstance(claims.get("email"), str) else None,
            scopes=_extract_scopes(claims),
            claims=claims,
        )


def _extract_scopes(claims: dict[str, Any]) -> frozenset[str]:
    """Parse granted scopes from either standard claim shape.

    RFC 9068 access tokens carry ``scope`` as a single space-separated
    string (mirroring the OAuth wire format); several major issuers use an
    ``scp`` JSON list instead.  ``scope`` wins when both are present.  A
    token with neither simply has no scopes — that is a 403/insufficient-
    scope story, not a 401/invalid-token one.
    """
    scope = claims.get("scope")
    if isinstance(scope, str):
        return frozenset(scope.split())
    scp = claims.get("scp")
    if isinstance(scp, list):
        entries = cast("list[Any]", scp)
        return frozenset(str(entry) for entry in entries)
    return frozenset()
