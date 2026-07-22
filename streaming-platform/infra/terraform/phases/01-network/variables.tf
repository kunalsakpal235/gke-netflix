variable "project_id" {
  type    = string
  default = "devops-1-502311"
}
variable "region" {
  type    = string
  default = "asia-south1"
}
variable "network_name" {
  type    = string
  default = "streaming-vpc"
}
variable "subnet_name" {
  type    = string
  default = "gke-subnet"
}
variable "subnet_cidr" {
  type    = string
  default = "10.10.0.0/20"
}
variable "pods_range_name" {
  type    = string
  default = "pods"
}
variable "pods_cidr" {
  type    = string
  default = "10.20.0.0/16"
}
variable "services_range_name" {
  type    = string
  default = "services"
}
variable "services_cidr" {
  type    = string
  default = "10.30.0.0/20"
}
variable "enable_nat" {
  type    = bool
  default = false
}
