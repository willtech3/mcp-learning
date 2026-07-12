# Terraform and provider requirements.
#
# State is local by default — fine for a single-owner demo. For anything
# shared, create a GCS bucket and uncomment the backend block.

terraform {
  required_version = ">= 1.7"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.30, < 8"
    }
  }

  # backend "gcs" {
  #   bucket = "your-tf-state-bucket"
  #   prefix = "virtual-library-mcp"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
