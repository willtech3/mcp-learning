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
    Maximum Cloud Run instances. This must remain 1 while the service uses
    per-instance SQLite: session affinity is only best-effort and cannot make
    mutations consistent across replicas. Move catalog state to a shared
    database before raising this limit.
  EOT
  type        = number
  default     = 1

  validation {
    condition     = var.max_instances == 1
    error_message = "max_instances must remain 1 while the deployment uses per-instance SQLite."
  }
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
    Mount the EDUCATIONAL built-in authorization server under /auth. It has
    no user identity and is intentionally restricted by application startup
    validation to loopback development. Cloud Run must keep this false: the
    modern era shares the Google-backed OAuth proxy and email allowlist.
  EOT
  type        = bool
  default     = false
}

variable "demo_as_auto_approve" {
  description = <<-EOT
    Demo AS skips its consent page and immediately redirects with a code.
    Convenient for headless local demos. The demo AS cannot be enabled on a
    public deployment, irrespective of this setting.
  EOT
  type        = bool
  default     = false
}

variable "discovery_era" {
  description = <<-EOT
    Which protocol era's OAuth discovery documents own the shared
    well-known paths. "legacy" is right for a deployment that interactive
    chat clients (Claude, ChatGPT) connect to — they speak the legacy era
    and walk PRM -> AS metadata -> PKCE from those paths. The modern
    (2026-07-28) resource server follows the same discovery chain and
    validates tokens through the same Google-backed OAuth proxy.
  EOT
  type        = string
  default     = "legacy"

  validation {
    condition     = contains(["modern", "legacy"], var.discovery_era)
    error_message = "discovery_era must be \"modern\" or \"legacy\"."
  }
}

variable "http_stateless" {
  description = <<-EOT
    Run the legacy (FastMCP) protocol path without Mcp-Session-Id sessions.
    Strongly recommended on Cloud Run: scale-to-zero recycles instances,
    and hosted chat clients are known to cache a stale session id across
    restarts and then wedge. Costs the session-stream features (sampling,
    elicitation, subscriptions) remotely — chat clients don't use them.
  EOT
  type        = bool
  default     = true
}
