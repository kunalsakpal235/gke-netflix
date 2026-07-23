terraform {
  required_version = ">= 1.5"
  required_providers { google = { source = "hashicorp/google", version = "~> 6.0" } }
}
provider "google" {
  project = var.project_id
  region  = var.region
}

data "terraform_remote_state" "network" {
  backend = "local"
  config  = { path = "../01-network/terraform.tfstate" }
}

module "gke" {
  source                      = "../../modules/gke"
  project_id                  = var.project_id
  name                        = var.cluster_name
  region                      = var.region
  zone                        = var.zone
  cluster_mode                = var.cluster_mode
  network                     = data.terraform_remote_state.network.outputs.network_name
  subnetwork                  = data.terraform_remote_state.network.outputs.subnet_name
  pods_range_name             = data.terraform_remote_state.network.outputs.pods_range_name
  services_range_name         = data.terraform_remote_state.network.outputs.services_range_name
  release_channel             = var.release_channel
  enable_dataplane_v2         = var.enable_dataplane_v2
  enable_binary_authorization = var.enable_binary_authorization
  machine_type                = var.machine_type
  min_nodes                   = var.min_nodes
  max_nodes                   = var.max_nodes
  use_spot                    = var.use_spot
  disk_size_gb                = var.disk_size_gb
}
