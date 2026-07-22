variable "project_id" {
  type    = string
  default = "devops-1-502311"
}
variable "region" {
  type    = string
  default = "asia-south1"
}
variable "video_bucket_name" {
  type    = string
  default = ""
}
variable "bucket_force_destroy" {
  type    = bool
  default = true
}
variable "enable_cloud_sql" {
  type    = bool
  default = false
}
variable "db_tier" {
  type    = string
  default = "db-f1-micro"
}
variable "enable_memorystore" {
  type    = bool
  default = false
}
variable "redis_memory_gb" {
  type    = number
  default = 1
}
