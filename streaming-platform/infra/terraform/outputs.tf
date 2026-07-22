output "cluster_name" { value = module.gke.name }
output "cluster_location" { value = module.gke.location }
output "registry_url" { value = module.registry.repository_url }
output "workload_sa" { value = module.workload_identity.email }
output "video_bucket" { value = module.storage.bucket_name }
