resource "google_sql_database_instance" "pg" {
  count               = var.enable_cloud_sql ? 1 : 0
  name                = "streaming-pg"
  database_version    = "POSTGRES_15"
  region              = var.region
  deletion_protection = false
  settings {
    tier      = var.db_tier
    disk_size = 10
  }
}

resource "google_redis_instance" "redis" {
  count          = var.enable_memorystore ? 1 : 0
  name           = "streaming-redis"
  memory_size_gb = var.redis_memory_gb
  region         = var.region
  tier           = "BASIC"
}
