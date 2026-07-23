terraform {
  required_version = ">= 1.5"
  required_providers { google = { source = "hashicorp/google", version = "~> 6.0" } }
}
provider "google" {
  project = var.project_id
  region  = var.region
}

module "workload_identity" {
  source     = "../../modules/workload-identity"
  project_id = var.project_id
  gsa_name   = var.gsa_name
  roles      = var.gsa_roles
  namespace  = var.k8s_namespace
  ksa        = var.k8s_ksa
}
