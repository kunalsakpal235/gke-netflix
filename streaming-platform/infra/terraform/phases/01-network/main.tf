terraform {
  required_version = ">= 1.5"
  required_providers { google = { source = "hashicorp/google", version = "~> 6.0" } }
}
provider "google" {
  project = var.project_id
  region  = var.region
}

module "network" {
  source              = "../../modules/network"
  network_name        = var.network_name
  subnet_name         = var.subnet_name
  region              = var.region
  subnet_cidr         = var.subnet_cidr
  pods_range_name     = var.pods_range_name
  pods_cidr           = var.pods_cidr
  services_range_name = var.services_range_name
  services_cidr       = var.services_cidr
  enable_nat          = var.enable_nat
}
