output "video_bucket" { value = module.storage.bucket_name }
output "sql_instance" { value = module.data.sql_instance }
output "redis_host" { value = module.data.redis_host }
