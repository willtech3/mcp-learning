# The Cloud Run service.
#
# Two deliberate, documented choices:
#
# 1. SESSION AFFINITY ON, SMALL MAX INSTANCES. MCP's Streamable HTTP
#    transport here is stateful — sampling, elicitation, and notifications
#    are server->client requests riding the session's SSE stream, and the
#    demo's SQLite catalog is per-instance. Affinity pins a client to one
#    instance; the small cap keeps behavior predictable. Stateless wide
#    scaling would require externalizing sessions and the database.
#
# 2. PUBLIC INVOKER, AUTH AT THE APP LAYER. MCP clients authenticate with
#    OAuth 2.1 bearer tokens validated by the server itself (plus the
#    email allowlist). Cloud Run's IAM-based invoker auth can't speak the
#    MCP authorization flow, so the platform layer stays open and the
#    application enforces identity. The app fails closed if misconfigured.

data "google_project" "current" {
  project_id = var.project_id
}

locals {
  # Cloud Run deterministic URL — knowable BEFORE the first deploy, which
  # is what lets the OAuth client be registered ahead of time.
  base_url = "https://${var.service_name}-${data.google_project.current.number}.${var.region}.run.app"
}

resource "google_cloud_run_v2_service" "server" {
  count = var.deploy_service ? 1 : 0

  name                = var.service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = google_service_account.run_service.email
    session_affinity                 = true
    max_instance_request_concurrency = 40

    scaling {
      min_instance_count = 0 # scale to zero: free when idle
      max_instance_count = var.max_instances
    }

    containers {
      image = local.image

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true # CPU only during requests (cheapest tier)
      }

      env {
        name  = "VIRTUAL_LIBRARY_TRANSPORT"
        value = "http"
      }
      env {
        name  = "VIRTUAL_LIBRARY_HTTP_HOST"
        value = "0.0.0.0"
      }
      env {
        name  = "VIRTUAL_LIBRARY_AUTH_ENABLED"
        value = "true"
      }
      env {
        name  = "VIRTUAL_LIBRARY_BASE_URL"
        value = local.base_url
      }
      env {
        name  = "VIRTUAL_LIBRARY_GOOGLE_CLIENT_ID"
        value = var.google_oauth_client_id
      }
      env {
        name  = "VIRTUAL_LIBRARY_AUTH_ALLOWED_EMAILS"
        value = jsonencode(var.auth_allowed_emails)
      }
      env {
        name  = "VIRTUAL_LIBRARY_LEGACY_OAUTH_FIRESTORE_PROJECT"
        value = var.project_id
      }
      env {
        name = "VIRTUAL_LIBRARY_GOOGLE_CLIENT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.oauth_client_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "VIRTUAL_LIBRARY_LEGACY_OAUTH_JWT_SIGNING_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.oauth_jwt_signing_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "VIRTUAL_LIBRARY_LEGACY_OAUTH_STORAGE_ENCRYPTION_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.oauth_storage_encryption_key.secret_id
            version = "latest"
          }
        }
      }

      # Stateless legacy path + legacy-owned discovery: what interactive
      # chat clients need from an ephemeral-compute deployment (see
      # variables.tf for both stories).
      env {
        name  = "VIRTUAL_LIBRARY_HTTP_STATELESS"
        value = tostring(var.http_stateless)
      }
      env {
        name  = "VIRTUAL_LIBRARY_DISCOVERY_ERA"
        value = var.discovery_era
      }

      # --- MODERN era (2026-07-28) ---------------------------------------
      # Bearer validation on the modern protocol path, tokens issued by the
      # bundled educational AS (see variables.tf for the security caveat).
      env {
        name  = "VIRTUAL_LIBRARY_MODERN_AUTH_ENABLED"
        value = tostring(var.modern_auth_enabled)
      }
      env {
        name  = "VIRTUAL_LIBRARY_DEMO_AS_ENABLED"
        value = tostring(var.demo_as_enabled)
      }
      env {
        name  = "VIRTUAL_LIBRARY_DEMO_AS_AUTO_APPROVE"
        value = tostring(var.demo_as_auto_approve)
      }
      # Shared MRTR requestState HMAC key — see secrets.tf for why this
      # must be identical across instances.
      env {
        name = "VIRTUAL_LIBRARY_REQUEST_STATE_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.request_state_secret.secret_id
            version = "latest"
          }
        }
      }

      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 2
        period_seconds        = 3
        failure_threshold     = 10
      }

      liveness_probe {
        http_get {
          path = "/health"
        }
        period_seconds = 30
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.service_can_read,
    google_secret_manager_secret_iam_member.request_state_read,
    google_secret_manager_secret_iam_member.oauth_jwt_signing_key_read,
    google_secret_manager_secret_iam_member.oauth_storage_encryption_key_read,
    google_project_iam_member.oauth_firestore_user,
  ]
}

# Platform-layer access is public; identity is enforced by the app's
# OAuth 2.1 layer (see the header comment).
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count = var.deploy_service ? 1 : 0

  name     = google_cloud_run_v2_service.server[0].name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
