locals {
  video_bucket = var.video_bucket_name != "" ? var.video_bucket_name : "${var.project_id}-video"
}

module "network" {
  count               = var.create_network ? 1 : 0
  source              = "./modules/network"
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

locals {
  network        = var.create_network ? module.network[0].network_name : var.existing_network
  subnetwork     = var.create_network ? module.network[0].subnet_name : var.existing_subnet
  pods_range     = var.create_network ? module.network[0].pods_range_name : var.existing_pods_range
  services_range = var.create_network ? module.network[0].services_range_name : var.existing_services_range
}

module "gke" {
  source                      = "./modules/gke"
  project_id                  = var.project_id
  name                        = var.cluster_name
  region                      = var.region
  zone                        = var.zone
  cluster_mode                = var.cluster_mode
  network                     = local.network
  subnetwork                  = local.subnetwork
  pods_range_name             = local.pods_range
  services_range_name         = local.services_range
  release_channel             = var.release_channel
  enable_dataplane_v2         = var.enable_dataplane_v2
  enable_binary_authorization = var.enable_binary_authorization
  machine_type                = var.machine_type
  min_nodes                   = var.min_nodes
  max_nodes                   = var.max_nodes
  use_spot                    = var.use_spot
  disk_size_gb                = var.disk_size_gb
}

module "registry" {
  source     = "./modules/artifact-registry"
  project_id = var.project_id
  name       = var.registry_name
  location   = var.region
}

module "workload_identity" {
  source     = "./modules/workload-identity"
  project_id = var.project_id
  gsa_name   = var.gsa_name
  roles      = var.gsa_roles
  namespace  = var.k8s_namespace
  ksa        = var.k8s_ksa
}

module "storage" {
  source        = "./modules/storage"
  name          = local.video_bucket
  location      = var.region
  force_destroy = var.bucket_force_destroy
}

module "data" {
  source             = "./modules/data"
  region             = var.region
  enable_cloud_sql   = var.enable_cloud_sql
  db_tier            = var.db_tier
  enable_memorystore = var.enable_memorystore
  redis_memory_gb    = var.redis_memory_gb
}
