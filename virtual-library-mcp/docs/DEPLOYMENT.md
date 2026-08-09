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
| OAuth 2.1 + PKCE | One Google-backed OAuth proxy serves both protocol eras — two console clicks, aided by Cloud Run's **deterministic URL** (register the redirect URI before first deploy) | Cognito user pool + domain + app client config; function URLs are random, so OAuth client registration needs a deployed URL or a custom domain first |
| Streamable HTTP / SSE | Native (request/response streaming) | Response streaming has payload/time limits and needs an adapter layer for ASGI |
| Container story | Runs the existing Dockerfile as-is | Needs Lambda-specific packaging or a web adapter |
| Idle cost | Scale-to-zero ≈ $0 | ≈ $0 (comparable) |

MCP-specific properties are handled explicitly:

| MCP property | Cloud Run answer |
|---|---|
| Legacy stateful sessions (sampling/elicitation ride a session SSE stream) | Deployed legacy path is stateless; session affinity remains a compatibility aid |
| Modern era is stateless (SEP-2575), but MRTR `requestState` retries may land on any instance | shared HMAC key in Secret Manager (`VIRTUAL_LIBRARY_REQUEST_STATE_SECRET`) |
| Demo SQLite baked into the image (per-instance, ephemeral) | `max_instances = 1` prevents divergent replicas; swap to Cloud SQL before scaling out |

## Architecture

```
                        GitHub Actions (push to main)
                        │  OIDC token ──> Workload Identity Federation
                        │  (keyless — no exported SA keys anywhere)
                        ▼
             build image ─> Artifact Registry ─> terraform apply (state in GCS)
                                                     │
MCP client ──OAuth 2.1 + PKCE──> Cloud Run (virtual-library-mcp)
   │                                 │ BOTH eras: Google OAuth + email allowlist
   │<──discovery, tokens─────────────│ one OAuth proxy; tokens checked every request
   │                                 │ encrypted OAuth state ──> Firestore
   │                                 │ SQLite catalog (baked into image)
   └──sign-in──> Google OAuth <──────┘ secrets from Secret Manager
```

Identity is enforced **in the application** (OAuth 2.1 resource server),
not at Cloud Run's IAM layer — MCP clients can't speak IAM, but they can
speak the MCP authorization spec. The platform invoker is therefore public
while the app fails closed: it refuses to serve HTTP unless *both*
protocol eras have authentication enabled.

### One production trust model, two protocol eras

- **Both eras:** Google is the upstream identity provider. FastMCP's OAuth
  proxy performs client discovery/registration and Authorization Code + PKCE,
  then issues audience-bound access tokens. The legacy FastMCP middleware and
  the modern verifier validate those same tokens on every request and enforce
  the same normalized `auth_allowed_emails` authorization list.
- **Built-in demo authorization server:** the educational `/auth/*` server
  still demonstrates PKCE S256, resource indicators, RFC 9207 `iss`, CIMD,
  and deprecated DCR in a self-contained local exercise. It has no identity
  database, so startup validation confines it to loopback development and the
  Cloud Run configuration keeps it disabled.
- **Shared discovery paths — `discovery_era`:** both eras publish OAuth
  discovery documents, but RFC 9728/8414 pin them to fixed well-known
  locations, so one era must own the shared paths. The deployment sets
  `discovery_era = "legacy"`: the Google OAuth stack serves
  `/.well-known/oauth-protected-resource*` and the host-root
  `/.well-known/oauth-authorization-server`, which is what lets
  interactive chat clients (Claude, ChatGPT — legacy-era speakers)
  complete discovery → registration → PKCE against this server. The
  modern client uses the same PRM and authorization-server metadata. This is
  intentional: the authorization specifications define the protected-resource
  relationship, not a requirement for separate authorization servers per MCP
  protocol revision.
- **Stateless legacy path — `http_stateless = true`:** hosted chat
  clients cache `Mcp-Session-Id` across server restarts and fail hard
  when an ephemeral instance recycles. The deployed legacy era therefore
  runs sessionless; the session-stream features (sampling, elicitation,
  subscriptions) are local-development demos, and the modern era is
  stateless by design.
- **Durable legacy OAuth state:** FastMCP defaults to process memory on Linux.
  That is not sufficient on Cloud Run: ChatGPT may dynamically register on
  one instance, then open `/authorize` after scale-to-zero or on another
  instance. The deployment therefore stores DCR registrations and upstream
  tokens in Firestore, encrypted by the application, and uses a stable JWT
  signing key from Secret Manager.

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
account (including the six-permission `roles/datastore.cloneAdmin` role needed
to create and inspect the Firestore OAuth database, without access to its
documents).
It prints four outputs used in the next steps, including the
service's **deterministic URL** (`base_url`) — knowable before anything
is deployed, which is what lets the OAuth client be registered up front.

The bootstrap state file stays local (gitignored); keep it — it's only
needed to change or destroy these few resources.

> **Existing deployment upgrading to persistent OAuth storage:** run this
> bootstrap command once from the updated branch before merging it. That adds
> the deployer's narrow Firestore database-creation role; the normal post-merge
> workflow creates the database and performs every remaining deployment step.
> If the gitignored local bootstrap state was not retained, do not approve a
> plan that proposes recreating the existing bootstrap resources. Recover or
> import that state, or grant only `roles/datastore.cloneAdmin` to the existing
> deployer service account before running the normal deployment.

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
HMAC key plus separate legacy OAuth signing and storage-encryption keys are
seeded automatically by the workflow (random bytes, first run only).

## Deploying (every time)

Push to `main` touching `virtual-library-mcp/**`, or run the **Deploy**
workflow manually. The pipeline: quality gates (ruff, pyright, pytest) →
WIF auth → build + push image tagged with the git SHA → `terraform apply`
→ smoke tests (health, a 401 from *each* era, legacy and modern discovery
documents).

Rollback: revert the commit on `main` and let the workflow redeploy —
images are tagged by SHA and stay in the registry. (Deploying non-`main`
refs is deliberately impossible: the WIF trust condition pins
`refs/heads/main`.)

## Verify by hand

```bash
BASE_URL=<base_url from Step 1>
curl "$BASE_URL/health"
# {"status":"ok","service":"virtual-library"}

# Protected-resource and authorization-server discovery (both eras):
curl "$BASE_URL/.well-known/oauth-protected-resource/mcp"
curl "$BASE_URL/.well-known/oauth-authorization-server"
```

Then connect a real client — the `mcp-client-learning` sibling repo
implements the full modern discovery → CIMD registration → PKCE →
bearer flow.

## Testing in chat clients (remote MCP + Apps UI)

State of the client world as of 2026-07-12 (verify against current docs —
this moves fast):

| Client | Remote MCP + OAuth | Protocol era | MCP Apps UI | Notes |
|---|---|---|---|---|
| Claude (web, Desktop, iOS/Android) | Custom connectors, OAuth 2.1 + PKCE + DCR/CIMD | Legacy (2025-11-25) | Yes (since 2026-01-26) | Free plan: 1 custom connector; connects from Anthropic's cloud |
| ChatGPT (web) | Developer mode (Plus/Pro/Business+), OAuth incl. DCR/CIMD | Legacy (version header unconfirmed — log it) | Yes — native MCP Apps standard; `openai/outputTemplate` is a legacy alias | Dev-mode connectors are web-only; mobile needs a published app |
| Anything speaking 2026-07-28 | — | Modern | — | No shipping chat client yet (spec finals 2026-07-28); use the sibling client repo or beta-SDK tools |

- **Claude:** Settings → Connectors → *Add custom connector* → URL
  `<base_url>/mcp`. Claude walks the legacy PRM (which `discovery_era =
  "legacy"` hands to the Google OAuth stack), registers dynamically, runs
  PKCE, and you sign in with an allowlisted Google account. The
  `browse_catalog_app` / `library_dashboard_app` tools render as
  interactive widgets in chat on desktop, web, and mobile.
- **ChatGPT:** Settings → Apps & Connectors → Advanced → Developer mode,
  then create a connector with the same `/mcp` URL and OAuth. Widgets use
  FastMCP's standard MCP Apps metadata, which ChatGPT consumes natively.
- **Modern era (2026-07-28):** chat clients can't exercise it yet. Verify
  it remotely with the sibling client repo against the deployed endpoint,
  using the same discovered Google-backed OAuth flow, or with a compatible
  beta-SDK client.

## Security checklist

- [x] OAuth 2.1 + PKCE (S256) on both eras; tokens validated on every request
- [x] Fail-closed startup: HTTP refuses to serve unless BOTH eras are authenticated
- [x] One Google identity and email allowlist policy on both eras
- [x] Identity-free demo authorization server rejected on non-loopback URLs
- [x] Keyless CI (Workload Identity Federation pinned to repo + branch); no SA keys exist
- [x] Secrets only in Secret Manager; never in Terraform state, git, or GitHub
- [x] Legacy OAuth registrations/tokens encrypted in Firestore; stable signing key across instances
- [x] Least-privilege runtime SA (logs + metrics + four secrets + Firestore data); deployer SA scoped to its job
- [x] Immutable image tags (git SHA); rate limiting; non-root container
- [x] Single Cloud Run instance while SQLite is per-instance; no divergent replicas

## Operational notes

- **Writes are ephemeral, but consistent within a live revision.** The SQLite
  catalog is baked into the image and Cloud Run is capped at one instance, so
  clients cannot land on divergent catalogs. Checkouts still vanish when the
  instance recycles. For durable state and horizontal scaling: Cloud SQL
  (Postgres) plus the SQLAlchemy URL in config.
- **Costs.** Scale-to-zero + `cpu_idle` keeps an idle demo inexpensive;
  Firestore's small OAuth workload, Secret Manager, Artifact Registry, and
  the state bucket should remain in their low/free usage tiers for a personal
  demo, but check current GCP pricing for your region.
- **Logs.** `gcloud run services logs read virtual-library-mcp --region=<region>`;
  Logfire tracing activates automatically when `LOGFIRE_TOKEN` is set.
- **Terraform state** lives in `gs://<PROJECT_ID>-tfstate` (versioned).
  `just tf-init && just tf-plan` locally is fine for *inspection*;
  applying locally is not the workflow — push to main instead.
