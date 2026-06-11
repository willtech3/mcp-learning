# Secret Manager: the Google OAuth client secret.
#
# Terraform creates the secret CONTAINER only — the value is added
# out-of-band (`just secret-set`) so it never touches Terraform state.
# State files are not a safe place for credentials.

resource "google_secret_manager_secret" "oauth_client_secret" {
  secret_id = "${var.service_name}-google-oauth-client-secret"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

# Only the service's dedicated service account may read it.
resource "google_secret_manager_secret_iam_member" "service_can_read" {
  secret_id = google_secret_manager_secret.oauth_client_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.run_service.email}"
}
