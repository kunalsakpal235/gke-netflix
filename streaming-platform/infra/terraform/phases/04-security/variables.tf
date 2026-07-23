variable "project_id" {
  type    = string
  default = "devops-1-502311"
}
variable "region" {
  type    = string
  default = "asia-south1"
}
variable "gsa_name" {
  type    = string
  default = "streaming-workloads"
}
variable "k8s_namespace" {
  type    = string
  default = "streaming"
}
variable "k8s_ksa" {
  type    = string
  default = "streaming-workloads"
}
variable "gsa_roles" {
  type    = list(string)
  default = ["roles/storage.objectViewer", "roles/secretmanager.secretAccessor", "roles/iam.serviceAccountTokenCreator"]
}
