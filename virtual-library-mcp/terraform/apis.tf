# GCP APIs the deployment depends on.

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "firestore.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
  ])

  service            = each.key
  disable_on_destroy = false
}
