resource "google_compute_network" "vpc" {
  name                    = var.network_name
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "subnet" {
  name                     = var.subnet_name
  region                   = var.region
  network                  = google_compute_network.vpc.id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true

  secondary_ip_range {
    range_name    = var.pods_range_name
    ip_cidr_range = var.pods_cidr
  }
  secondary_ip_range {
    range_name    = var.services_range_name
    ip_cidr_range = var.services_cidr
  }
}

resource "google_compute_firewall" "health_checks" {
  name          = "${var.network_name}-allow-health-checks"
  network       = google_compute_network.vpc.id
  direction     = "INGRESS"
  source_ranges = ["35.191.0.0/16", "130.211.0.0/22"]
  allow { protocol = "tcp" }
}

resource "google_compute_firewall" "internal" {
  name          = "${var.network_name}-allow-internal"
  network       = google_compute_network.vpc.id
  direction     = "INGRESS"
  source_ranges = [var.subnet_cidr, var.pods_cidr, var.services_cidr]
  allow { protocol = "tcp" }
  allow { protocol = "udp" }
  allow { protocol = "icmp" }
}

resource "google_compute_router" "router" {
  count   = var.enable_nat ? 1 : 0
  name    = "${var.network_name}-router"
  region  = var.region
  network = google_compute_network.vpc.id
}

resource "google_compute_router_nat" "nat" {
  count                              = var.enable_nat ? 1 : 0
  name                               = "${var.network_name}-nat"
  router                             = google_compute_router.router[0].name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}
