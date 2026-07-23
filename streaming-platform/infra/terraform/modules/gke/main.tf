# --- Autopilot (regional; per-pod billing) ---
resource "google_container_cluster" "autopilot" {
  count            = var.cluster_mode == "autopilot" ? 1 : 0
  name             = var.name
  location         = var.region
  enable_autopilot = true

  network    = var.network
  subnetwork = var.subnetwork
  ip_allocation_policy {
    cluster_secondary_range_name  = var.pods_range_name
    services_secondary_range_name = var.services_range_name
  }
  release_channel { channel = var.release_channel }
  deletion_protection = false
}

# --- Standard (zonal for free-tier; explicit node pool) ---
resource "google_container_cluster" "standard" {
  count                    = var.cluster_mode == "standard" ? 1 : 0
  name                     = var.name
  location                 = var.zone
  remove_default_node_pool = true
  initial_node_count       = 1

  network    = var.network
  subnetwork = var.subnetwork
  ip_allocation_policy {
    cluster_secondary_range_name  = var.pods_range_name
    services_secondary_range_name = var.services_range_name
  }
  workload_identity_config { workload_pool = "${var.project_id}.svc.id.goog" }
  datapath_provider = var.enable_dataplane_v2 ? "ADVANCED_DATAPATH" : "DATAPATH_PROVIDER_UNSPECIFIED"
  release_channel { channel = var.release_channel }

  dynamic "binary_authorization" {
    for_each = var.enable_binary_authorization ? [1] : []
    content { evaluation_mode = "PROJECT_SINGLETON_POLICY_ENFORCE" }
  }
  deletion_protection = false
}

resource "google_container_node_pool" "standard" {
  count    = var.cluster_mode == "standard" ? 1 : 0
  name     = "${var.name}-np"
  location = var.zone
  cluster  = google_container_cluster.standard[0].name

  autoscaling {
    min_node_count = var.min_nodes
    max_node_count = var.max_nodes
  }
  node_config {
    machine_type = var.machine_type
    spot         = var.use_spot
    disk_size_gb = var.disk_size_gb
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    workload_metadata_config { mode = "GKE_METADATA" }
  }
}
