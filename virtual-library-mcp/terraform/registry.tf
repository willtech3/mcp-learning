# Artifact Registry repository for the server image.

resource "google_artifact_registry_repository" "images" {
  repository_id = "mcp-servers"
  location      = var.region
  format        = "DOCKER"
  description   = "Container images for MCP servers"

  depends_on = [google_project_service.apis]
}

locals {
  image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}/${var.service_name}:${var.image_tag}"
}
