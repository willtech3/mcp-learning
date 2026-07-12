# Terraform and provider requirements.
#
# State lives in GCS because deploys run from ephemeral GitHub Actions
# runners — local state would vanish with each runner. The bucket is
# created once by terraform/bootstrap; the backend block is PARTIAL
# (no bucket name) and completed at init time:
#
#   terraform init \
#     -backend-config="bucket=<project-id>-tfstate" \
#     -backend-config="prefix=virtual-library-mcp"
#
# (`just tf-init` does this for you; CI does it in the deploy workflow.)

terraform {
  required_version = ">= 1.7"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.30, < 8"
    }
  }

  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}
