# ---------- core ----------
variable "project_id" {
  type        = string
  description = "GCP project ID"
  default     = "devops-1-502311"
}
variable "region" {
  type    = string
  default = "asia-south1"
}
variable "zone" {
  type    = string
  default = "asia-south1-a"
}
variable "labels" {
  type    = map(string)
  default = { app = "streaming", env = "dev" }
}

# ---------- network (specify or reuse the cluster network) ----------
variable "create_network" {
  type        = bool
  default     = true
  description = "Create a new VPC/subnet, or reuse an existing one"
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
  type        = bool
  default     = false
  description = "Cloud NAT for private-node egress (costs when on)"
}
# used only when create_network = false:
variable "existing_network" {
  type    = string
  default = ""
}
variable "existing_subnet" {
  type    = string
  default = ""
}
variable "existing_pods_range" {
  type    = string
  default = ""
}
variable "existing_services_range" {
  type    = string
  default = ""
}

# ---------- GKE cluster ----------
variable "cluster_name" {
  type    = string
  default = "streaming"
}
variable "cluster_mode" {
  type        = string
  default     = "autopilot"
  description = "autopilot | standard"
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
# standard node pool (ignored for autopilot):
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

# ---------- registry ----------
variable "registry_name" {
  type    = string
  default = "streaming-images"
}

# ---------- workload identity ----------
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

# ---------- storage ----------
variable "video_bucket_name" {
  type        = string
  default     = ""
  description = "defaults to <project>-video if empty"
}
variable "bucket_force_destroy" {
  type    = bool
  default = true
}

# ---------- optional data services ----------
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
