output "sql_instance" {
  value = var.enable_cloud_sql ? google_sql_database_instance.pg[0].name : null
}
output "redis_host" {
  value = var.enable_memorystore ? google_redis_instance.redis[0].host : null
}
