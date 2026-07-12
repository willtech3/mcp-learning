# Deploying to Google Cloud Run

This guide takes the Virtual Library MCP Server from your laptop to a
public, OAuth-protected Streamable HTTP endpoint on Cloud Run.

## Why Cloud Run

For a containerized MCP server on GCP, Cloud Run is the right primitive:
serverless containers with scale-to-zero (≈ free when idle), native HTTPS,
SSE streaming support, and per-revision rollouts — without cluster
management (GKE) or VM patching (GCE). The two constraints that matter for
MCP are handled explicitly:

| MCP property | Cloud Run answer |
|---|---|
| Stateful sessions (sampling/elicitation/notifications ride a session SSE stream) | `session_affinity = true` + small `max_instances` |
| Demo SQLite baked into the image (per-instance, ephemeral) | acceptable for a demo; swap to Cloud SQL for durable writes |

## Architecture

```
MCP client ──OAuth 2.1 + PKCE──> Cloud Run (virtual-library-mcp)
   │                                 │ validates bearer tokens (GoogleProvider)
   │<──discovery, tokens─────────────│ email allowlist middleware
   │                                 │ SQLite catalog (baked into image)
   └──sign-in──> Google OAuth <──────┘ client secret from Secret Manager
```

Identity is enforced **in the application** (OAuth 2.1 resource server +
email allowlist), not at Cloud Run's IAM layer — MCP clients can't speak
IAM, but they can speak the MCP authorization spec. The platform invoker
is therefore public while the app fails closed.

## Prerequisites

- `gcloud` CLI authenticated (`gcloud auth login` and
  `gcloud auth application-default login`)
- `terraform` >= 1.7, `docker`
- A GCP project with billing enabled

## Step 1 — Bootstrap the infrastructure

```bash
cd virtual-library-mcp/terraform
cp terraform.tfvars.example terraform.tfvars   # fill in project_id + allowed emails
terraform init
terraform apply -var deploy_service=false      # APIs, registry, secret, SA
```

The bootstrap apply prints `base_url` — Cloud Run URLs are deterministic
(`https://<service>-<project-number>.<region>.run.app`), so the URL is
known **before** anything is deployed. That's what makes Step 2 possible
now instead of after a throwaway deploy.

## Step 2 — Create the Google OAuth client (one-time, manual)

Terraform cannot create standard OAuth clients (a GCP API limitation), so
this is the one console step:

1. Console → **APIs & Services → OAuth consent screen**: configure
   (External, add yourself as a test user is fine for a demo).
2. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Web application**
   - Authorized redirect URI: `<base_url>/auth/callback`
3. Copy the client ID into `terraform.tfvars`
   (`google_oauth_client_id = "..."`).
4. Store the client secret in Secret Manager — never in a file:

```bash
just secret-set     # prompts for the secret, pipes it to gcloud
```

## Step 3 — Build, push, deploy

```bash
just docker-push    # builds the image and pushes to Artifact Registry
cd terraform && terraform apply    # deploys the Cloud Run service
```

## Step 4 — Verify

```bash
curl "$(terraform -chdir=terraform output -raw base_url)/health"
# {"status":"ok","service":"virtual-library"}

curl -i "$(terraform -chdir=terraform output -raw mcp_endpoint)" -X POST \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# HTTP/2 401 + WWW-Authenticate: Bearer ... (auth is enforced)
```

Then connect a real MCP client (the `mcp-client-learning` sibling repo
implements the full discovery → registration → PKCE flow) and sign in with
an allowlisted Google account.

## Security checklist

- [x] OAuth 2.1 + PKCE (S256); tokens validated on every request
- [x] Email allowlist (`auth_allowed_emails`) — authorization, not just authentication
- [x] Client secret only in Secret Manager; read by a dedicated least-privilege SA
- [x] No secrets in Terraform state (secret *container* managed, value out-of-band)
- [x] Server fails closed: refuses unauthenticated HTTP, refuses incomplete auth config
- [x] Rate limiting middleware; non-root container; bulk-import path confinement
- [ ] Optional: Cloud Armor / Identity-Aware Proxy in front for defense in depth

## Operational notes

- **Writes are per-instance and ephemeral.** The SQLite catalog is baked
  into the image; checkouts vanish when an instance recycles. That's
  intentional for a self-resetting demo. For durable state: Cloud SQL
  (Postgres) + the SQLAlchemy URL in config.
- **Costs.** Scale-to-zero + `cpu_idle` keeps an idle demo at ~$0/month;
  Secret Manager and Artifact Registry are pennies.
- **Logs.** `gcloud run services logs read virtual-library-mcp --region=<region>`;
  Logfire tracing activates automatically when `LOGFIRE_TOKEN` is set.
- **Updating.** `just docker-push && terraform -chdir=terraform apply`
  (use `image_tag` for immutable tags if you outgrow `latest`).
