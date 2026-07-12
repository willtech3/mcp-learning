# One-time bootstrap for CI-driven deployment.
#
# This is the ONLY Terraform a human runs locally. It creates the three
# things GitHub Actions cannot create for itself:
#
#   1. A GCS bucket for Terraform remote state — CI runners are ephemeral,
#      so state must live somewhere durable and shared.
#   2. A Workload Identity Federation pool + OIDC provider trusted for
#      exactly one GitHub repository/branch. This is the keyless
#      alternative to exporting a service-account JSON key into GitHub
#      secrets: GitHub mints a short-lived OIDC token per workflow run and
#      GCP exchanges it for GCP credentials. Nothing long-lived exists to
#      leak.
#   3. A deployer service account the workflow impersonates, with the
#      roles the main Terraform configuration needs.
#
# State for THIS module is local (terraform.tfstate in this directory,
# gitignored). That is deliberate: the bootstrap creates the remote-state
# bucket, so it cannot store its own state there on first apply, and these
# few resources change ~never. Keep the local state file; you only need it
# again to change or destroy the bootstrap resources.
#
# Usage (once, from a workstation authenticated via `gcloud auth login`
# and `gcloud auth application-default login`):
#
#   cd virtual-library-mcp/terraform/bootstrap
#   terraform init
#   terraform apply -var project_id=<your-project>
#
# Then copy the outputs into GitHub repo variables (see docs/DEPLOYMENT.md).

terraform {
  required_version = ">= 1.7"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.30, < 8"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  description = "GCP project that hosts the service"
  type        = string
}

variable "region" {
  description = "Region for the state bucket (should match the Cloud Run region)"
  type        = string
  default     = "us-central1"
}

variable "github_repository" {
  description = "GitHub repository (owner/name) allowed to deploy"
  type        = string
  default     = "willtech3/mcp-learning"
}

variable "deploy_ref" {
  description = "Git ref deploys are restricted to (WIF attribute condition)"
  type        = string
  default     = "refs/heads/main"
}

data "google_project" "current" {
  project_id = var.project_id
}

# APIs the bootstrap resources themselves depend on. The main configuration
# enables the runtime APIs (run, artifactregistry, secretmanager) on its own.
resource "google_project_service" "apis" {
  for_each = toset([
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "storage.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
  ])

  service            = each.key
  disable_on_destroy = false
}

# --- 1. Remote state -------------------------------------------------------

resource "google_storage_bucket" "tfstate" {
  name     = "${var.project_id}-tfstate"
  location = var.region

  # State snapshots let you recover from a corrupted or mistaken apply.
  versioning {
    enabled = true
  }

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  depends_on = [google_project_service.apis]
}

# --- 2. Workload Identity Federation for GitHub Actions --------------------

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions"
  description               = "Identity pool for keyless GitHub Actions deploys"

  depends_on = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"

  # Map GitHub's OIDC token claims onto GCP attributes. `repository` and
  # `ref` are what the condition below pins; `subject` is required.
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # THE trust boundary: only workflow runs from this repo on this ref can
  # exchange tokens. A fork or another branch gets nothing.
  attribute_condition = "assertion.repository == \"${var.github_repository}\" && assertion.ref == \"${var.deploy_ref}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# --- 3. Deployer service account -------------------------------------------

resource "google_service_account" "deployer" {
  account_id   = "github-deployer"
  display_name = "GitHub Actions deployer"
  description  = "Impersonated by GitHub Actions via Workload Identity Federation"
}

# Let workflow runs from the trusted repo impersonate the deployer.
resource "google_service_account_iam_member" "wif_binding" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

# Roles the main Terraform configuration needs. Broad-ish by necessity —
# it creates service accounts, grants them project roles, enables APIs,
# and manages Cloud Run / Artifact Registry / Secret Manager. Acceptable
# on a personal project; on a shared project you would scope these with
# IAM conditions or a dedicated deploy project.
resource "google_project_iam_member" "deployer_roles" {
  for_each = toset([
    "roles/run.admin",                       # Cloud Run service + invoker IAM
    "roles/artifactregistry.admin",          # image repo + docker push
    "roles/secretmanager.admin",             # secret containers + versions + IAM
    "roles/iam.serviceAccountAdmin",         # creates the runtime SA
    "roles/iam.serviceAccountUser",          # actAs the runtime SA on deploy
    "roles/serviceusage.serviceUsageAdmin",  # enables runtime APIs
    "roles/resourcemanager.projectIamAdmin", # grants the runtime SA log/metric roles
  ])

  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# State bucket access for terraform init/plan/apply in CI.
resource "google_storage_bucket_iam_member" "deployer_state" {
  bucket = google_storage_bucket.tfstate.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.deployer.email}"
}

# --- Outputs: copy these into GitHub repo variables -------------------------

output "workload_identity_provider" {
  description = "GitHub variable GCP_WIF_PROVIDER"
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deployer_service_account" {
  description = "GitHub variable GCP_DEPLOYER_SA"
  value       = google_service_account.deployer.email
}

output "state_bucket" {
  description = "Terraform remote state bucket (derived as <project>-tfstate in CI)"
  value       = google_storage_bucket.tfstate.name
}

output "base_url" {
  description = <<-EOT
    The Cloud Run service's deterministic URL — knowable before anything is
    deployed. Use it to create the Google OAuth client:
      Authorized redirect URI: <base_url>/auth/callback
  EOT
  value       = "https://virtual-library-mcp-${data.google_project.current.number}.${var.region}.run.app"
}
