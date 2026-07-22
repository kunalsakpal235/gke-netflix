variable "project_id" {
  type    = string
  default = "devops-1-502311"
}
variable "region" {
  type    = string
  default = "asia-south1"
}
variable "apis" {
  type = list(string)
  default = ["container.googleapis.com", "artifactregistry.googleapis.com", "compute.googleapis.com",
    "secretmanager.googleapis.com", "iamcredentials.googleapis.com", "storage.googleapis.com",
  "pubsub.googleapis.com"]
}
