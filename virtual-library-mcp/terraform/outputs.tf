output "base_url" {
  description = <<-EOT
    The service's deterministic URL. Available even before the service is
    deployed — use it to create the Google OAuth client:
      Authorized redirect URI: <base_url>/auth/callback
  EOT
  value       = local.base_url
}

output "mcp_endpoint" {
  description = "URL MCP clients connect to"
  value       = "${local.base_url}/mcp"
}

output "image" {
  description = "Image reference `just docker-push` builds and pushes"
  value       = local.image
}

output "oauth_secret_name" {
  description = "Secret Manager secret that must hold the OAuth client secret"
  value       = google_secret_manager_secret.oauth_client_secret.secret_id
}

output "service_account" {
  description = "Service account the Cloud Run service runs as"
  value       = google_service_account.run_service.email
}
