resource "google_storage_bucket" "video" {
  name                        = var.name
  location                    = var.location
  uniform_bucket_level_access = true
  force_destroy               = var.force_destroy
}
