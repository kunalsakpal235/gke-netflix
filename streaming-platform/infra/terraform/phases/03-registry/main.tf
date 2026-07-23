terraform {
  required_version = ">= 1.5"
  required_providers { google = { source = "hashicorp/google", version = "~> 6.0" } }
}
provider "google" {
  project = var.project_id
  region  = var.region
}

module "registry" {
  source     = "../../modules/artifact-registry"
  project_id = var.project_id
  name       = var.registry_name
  location   = var.region
}
