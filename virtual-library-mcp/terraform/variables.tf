variable "project_id" {
  description = "GCP project that hosts the service"
  type        = string
}

variable "region" {
  description = "Cloud Run region"
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Cloud Run service name (also the deterministic URL's first label)"
  type        = string
  default     = "virtual-library-mcp"
}

variable "image_tag" {
  description = "Tag of the container image to deploy"
  type        = string
  default     = "latest"
}

variable "google_oauth_client_id" {
  description = "Google OAuth client ID for the MCP server (create in Cloud Console)"
  type        = string
  default     = ""
}

variable "auth_allowed_emails" {
  description = "Google accounts authorized to use the server (empty = any Google account)"
  type        = list(string)
  default     = []
}

variable "deploy_service" {
  description = <<-EOT
    Whether to deploy the Cloud Run service itself. Set to false for the
    bootstrap apply (creates APIs, registry, secret, service account) that
    must happen before the image is pushed and the OAuth secret is set.
  EOT
  type        = bool
  default     = true
}

variable "max_instances" {
  description = <<-EOT
    Maximum Cloud Run instances. Keep small: MCP sessions are stateful
    (sampling/elicitation ride a session SSE stream) and the SQLite catalog
    is per-instance, so this deployment relies on session affinity rather
    than wide horizontal scale.
  EOT
  type        = number
  default     = 2
}
