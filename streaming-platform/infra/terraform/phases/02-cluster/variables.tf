variable "project_id" {
  type    = string
  default = "devops-1-502311"
}
variable "region" {
  type    = string
  default = "asia-south1"
}
variable "zone" {
  type    = string
  default = "asia-south1-a"
}
variable "cluster_name" {
  type    = string
  default = "streaming"
}
variable "cluster_mode" {
  type    = string
  default = "autopilot"
}
variable "release_channel" {
  type    = string
  default = "REGULAR"
}
variable "enable_dataplane_v2" {
  type    = bool
  default = true
}
variable "enable_binary_authorization" {
  type    = bool
  default = false
}
variable "machine_type" {
  type    = string
  default = "e2-medium"
}
variable "min_nodes" {
  type    = number
  default = 0
}
variable "max_nodes" {
  type    = number
  default = 3
}
variable "use_spot" {
  type    = bool
  default = true
}
variable "disk_size_gb" {
  type    = number
  default = 40
}
