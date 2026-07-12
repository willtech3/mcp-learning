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
  # Personal email addresses; sensitive keeps them out of CI plan output.
  sensitive = true
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

variable "modern_auth_enabled" {
  description = <<-EOT
    Require OAuth 2.1 bearer tokens on the MODERN (2026-07-28) protocol
    path. The server refuses to start over HTTP unless BOTH eras are
    authenticated (or insecure mode is explicitly opted into), so leave
    this true for any deployment.
  EOT
  type        = bool
  default     = true
}

variable "demo_as_enabled" {
  description = <<-EOT
    Mount the EDUCATIONAL built-in authorization server under /auth. The
    modern era's bearer validation only accepts tokens from this AS, so it
    must be on whenever modern_auth_enabled is. Caveat, documented in
    DEPLOYMENT.md: the demo AS has no user identity — anyone completing
    the PKCE flow gets a token for the modern era. Acceptable for a demo
    catalog; never for real data.
  EOT
  type        = bool
  default     = true
}

variable "demo_as_auto_approve" {
  description = <<-EOT
    Demo AS skips its consent page and immediately redirects with a code.
    Convenient for headless local demos; on a public deployment keep the
    consent step (false) so token issuance at least requires a human click.
  EOT
  type        = bool
  default     = false
}
