# Durable FastMCP OAuth proxy storage.
#
# ChatGPT dynamically registers before opening the user's browser. Cloud Run
# may scale to zero between those requests or route them to different
# instances, so FastMCP's Linux in-memory default cannot be used in production.
# The application encrypts every value before it reaches this database.

resource "google_firestore_database" "oauth" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  # Removing this resource must not silently erase registered OAuth clients
  # or upstream refresh tokens.
  deletion_policy = "ABANDON"

  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "oauth_firestore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.run_service.email}"

  depends_on = [google_firestore_database.oauth]
}
