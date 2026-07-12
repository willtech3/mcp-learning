# Deploying to Google Cloud Run (via GitHub Actions)

This guide takes the Virtual Library MCP Server from repository to a
public, OAuth-protected, **dual-era** Streamable HTTP endpoint on Cloud
Run. After a one-time bootstrap, every deploy happens exclusively through
GitHub Actions — a human never runs `terraform apply` or `docker push`
against production again.

## Why Cloud Run (and not AWS Lambda)

Both were evaluated; the deciding criterion was **how much friction the
OAuth 2.1 + PKCE story adds**:

| Concern | Cloud Run | AWS Lambda |
|---|---|---|
| OAuth 2.1 + PKCE | Modern era: self-contained (bundled AS), zero cloud config. Legacy era: Google OAuth client — two console clicks, aided by Cloud Run's **deterministic URL** (register the redirect URI before first deploy) | Cognito user pool + domain + app client config; function URLs are random, so OAuth client registration needs a deployed URL or a custom domain first |
| Streamable HTTP / SSE | Native (request/response streaming) | Response streaming has payload/time limits and needs an adapter layer for ASGI |
| Container story | Runs the existing Dockerfile as-is | Needs Lambda-specific packaging or a web adapter |
| Idle cost | Scale-to-zero ≈ $0 | ≈ $0 (comparable) |

MCP-specific properties are handled explicitly:

| MCP property | Cloud Run answer |
|---|---|
| Legacy stateful sessions (sampling/elicitation ride a session SSE stream) | `session_affinity = true` + small `max_instances` |
| Modern era is stateless (SEP-2575), but MRTR `requestState` retries may land on any instance | shared HMAC key in Secret Manager (`VIRTUAL_LIBRARY_REQUEST_STATE_SECRET`) |
| Demo SQLite baked into the image (per-instance, ephemeral) | acceptable for a demo; swap to Cloud SQL for durable writes |

## Architecture

```
                        GitHub Actions (push to main)
                        │  OIDC token ──> Workload Identity Federation
                        │  (keyless — no exported SA keys anywhere)
                        ▼
             build image ─> Artifact Registry ─> terraform apply (state in GCS)
                                                     │
MCP client ──OAuth 2.1 + PKCE──> Cloud Run (virtual-library-mcp)
   │                                 │ LEGACY era: Google OAuth + email allowlist
   │<──discovery, tokens─────────────│ MODERN era: bearer JWTs from bundled demo AS
   │                                 │ SQLite catalog (baked into image)
   └──sign-in──> Google OAuth <──────┘ secrets from Secret Manager
```

Identity is enforced **in the application** (OAuth 2.1 resource server),
not at Cloud Run's IAM layer — MCP clients can't speak IAM, but they can
speak the MCP authorization spec. The platform invoker is therefore public
while the app fails closed: it refuses to serve HTTP unless *both*
protocol eras have authentication enabled.

### The two eras have different trust models — read this

- **Legacy era (2025-11-25, FastMCP):** Google is the identity provider
  and `auth_allowed_emails` is the authorization list. Real identity,
  real access control.
- **Modern era (2026-07-28, `modern/`):** tokens come from the bundled
  **educational** authorization server (`/auth/*`). It demonstrates the
  full draft flow — PKCE S256, resource indicators, RFC 9207 `iss`, CIMD —
  but it has **no user database**: anyone who completes the PKCE flow
  (with a consent click; auto-approve is off in production) gets a token.
  Treat the modern era of a public deployment as effectively public.
  That is fine for this demo catalog (per-instance, self-resetting
  SQLite) and would be unacceptable for real data — this is exactly the
  kind of trade-off the deployment is meant to teach.
- **Discovery shadowing:** both eras publish OAuth discovery documents,
  and the modern era's routes win at `/.well-known/oauth-protected-resource*`
  and `/.well-known/oauth-authorization-server`. Remote clients should
  therefore speak the **modern** era (the sibling `mcp-client-learning`
  repo does); the legacy era still *enforces* its Google bearer auth, but
  its self-discovery documents are shadowed, so exercise the legacy OAuth
  flow locally rather than against this deployment.

## One-time setup

Everything below happens exactly once. Steps 1 and 4 are the only local
commands; they are bootstrap, not deployment.

### Prerequisites

- `gcloud` CLI authenticated (`gcloud auth login` **and**
  `gcloud auth application-default login`), pointed at a project with
  billing enabled (`gcloud config set project <PROJECT_ID>`)
- `terraform` >= 1.7, `gh` CLI authenticated
- Repo admin rights (to set GitHub variables/secrets)

### Step 1 — Bootstrap (local, once)

```bash
just bootstrap <PROJECT_ID>
```

This applies `terraform/bootstrap/`: the Terraform state bucket, the
Workload Identity Federation pool/provider (trusting only
`willtech3/mcp-learning` on `refs/heads/main`), and the deployer service
account. It prints four outputs used in the next steps, including the
service's **deterministic URL** (`base_url`) — knowable before anything
is deployed, which is what lets the OAuth client be registered up front.

The bootstrap state file stays local (gitignored); keep it — it's only
needed to change or destroy these few resources.

### Step 2 — Create the Google OAuth client (console, once)

Terraform cannot create standard OAuth clients (a GCP API limitation), so
this is the one console task:

1. Console → **APIs & Services → OAuth consent screen**: configure
   (External; adding yourself as a test user is fine for a demo).
2. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Web application**
   - Authorized redirect URI: `<base_url>/auth/callback` (from Step 1's output)
3. Note the client ID (used in Step 3) and client secret (used in Step 4).

### Step 3 — Configure GitHub (once)

```bash
gh variable set GCP_PROJECT_ID          --body "<PROJECT_ID>"
gh variable set GCP_REGION              --body "us-central1"
gh variable set GCP_WIF_PROVIDER        --body "<workload_identity_provider output>"
gh variable set GCP_DEPLOYER_SA         --body "<deployer_service_account output>"
gh variable set GOOGLE_OAUTH_CLIENT_ID  --body "<client id from Step 2>"
gh secret   set AUTH_ALLOWED_EMAILS     --body '["you@gmail.com"]'
```

`AUTH_ALLOWED_EMAILS` is a JSON array and lives in a secret (personal
addresses stay out of logs; the Terraform variable is also marked
`sensitive`).

### Step 4 — Seed the OAuth client secret (local, once)

The first Deploy run creates the Secret Manager *containers*, then stops
with an explicit error before deploying — the Google client secret can
only come from a human. So: push (or `gh workflow run deploy.yml`), wait
for the run to fail at "Verify Google OAuth client secret is set", then:

```bash
just secret-set     # prompts for the secret from Step 2; pipes it to gcloud
```

Secrets never touch Terraform state, the repo, or GitHub — Terraform
manages the containers, values go straight to Secret Manager. The MRTR
HMAC key is seeded automatically by the workflow (random bytes, first run
only).

## Deploying (every time)

Push to `main` touching `virtual-library-mcp/**`, or run the **Deploy**
workflow manually. The pipeline: quality gates (ruff, pyright, pytest) →
WIF auth → build + push image tagged with the git SHA → `terraform apply`
→ smoke tests (health, a 401 from *each* era, discovery documents).

Rollback: revert the commit on `main` and let the workflow redeploy —
images are tagged by SHA and stay in the registry. (Deploying non-`main`
refs is deliberately impossible: the WIF trust condition pins
`refs/heads/main`.)

## Verify by hand

```bash
BASE_URL=<base_url from Step 1>
curl "$BASE_URL/health"
# {"status":"ok","service":"virtual-library"}

# Modern era discovery chain (what a 2026-07-28 client walks):
curl "$BASE_URL/.well-known/oauth-protected-resource/mcp"
curl "$BASE_URL/.well-known/oauth-authorization-server/auth"
```

Then connect a real client — the `mcp-client-learning` sibling repo
implements the full modern discovery → CIMD registration → PKCE →
bearer flow.

## Security checklist

- [x] OAuth 2.1 + PKCE (S256) on both eras; tokens validated on every request
- [x] Fail-closed startup: HTTP refuses to serve unless BOTH eras are authenticated
- [x] Email allowlist on the legacy era (authorization, not just authentication)
- [x] Keyless CI (Workload Identity Federation pinned to repo + branch); no SA keys exist
- [x] Secrets only in Secret Manager; never in Terraform state, git, or GitHub
- [x] Least-privilege runtime SA (logs + metrics + two secrets); deployer SA scoped to its job
- [x] Immutable image tags (git SHA); rate limiting; non-root container
- [ ] Known, documented gap: the modern era's demo AS issues tokens without identity — demo data only

## Operational notes

- **Writes are per-instance and ephemeral.** The SQLite catalog is baked
  into the image; checkouts vanish when an instance recycles. Intentional
  for a self-resetting demo. For durable state: Cloud SQL (Postgres) +
  the SQLAlchemy URL in config.
- **Costs.** Scale-to-zero + `cpu_idle` keeps an idle demo at ~$0/month;
  Secret Manager, Artifact Registry, and the state bucket are pennies.
- **Logs.** `gcloud run services logs read virtual-library-mcp --region=<region>`;
  Logfire tracing activates automatically when `LOGFIRE_TOKEN` is set.
- **Terraform state** lives in `gs://<PROJECT_ID>-tfstate` (versioned).
  `just tf-init && just tf-plan` locally is fine for *inspection*;
  applying locally is not the workflow — push to main instead.
