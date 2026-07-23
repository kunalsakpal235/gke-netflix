terraform {
  required_version = ">= 1.5"
  required_providers { google = { source = "hashicorp/google", version = "~> 6.0" } }
}
provider "google" {
  project = var.project_id
  region  = var.region
}

module "storage" {
  source        = "../../modules/storage"
  name          = var.video_bucket_name != "" ? var.video_bucket_name : "${var.project_id}-video"
  location      = var.region
  force_destroy = var.bucket_force_destroy
}

module "data" {
  source             = "../../modules/data"
  region             = var.region
  enable_cloud_sql   = var.enable_cloud_sql
  db_tier            = var.db_tier
  enable_memorystore = var.enable_memorystore
  redis_memory_gb    = var.redis_memory_gb
}
