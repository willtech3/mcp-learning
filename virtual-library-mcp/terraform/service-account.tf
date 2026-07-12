# Dedicated least-privilege service account for the Cloud Run service.
#
# Deliberately NOT the default compute SA (which carries Editor on many
# projects). This account can write logs/metrics and read one secret —
# nothing else.

resource "google_service_account" "run_service" {
  account_id   = "${var.service_name}-sa"
  display_name = "Virtual Library MCP Cloud Run service"
}

resource "google_project_iam_member" "log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.run_service.email}"
}

resource "google_project_iam_member" "metric_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.run_service.email}"
}
