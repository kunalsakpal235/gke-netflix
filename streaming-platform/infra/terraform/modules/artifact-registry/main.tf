resource "google_artifact_registry_repository" "repo" {
  repository_id = var.name
  location      = var.location
  format        = "DOCKER"
}
