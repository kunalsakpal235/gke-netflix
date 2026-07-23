terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
  # For team use, store state in GCS instead of locally:
  # backend "gcs" { bucket = "YOUR_TF_STATE_BUCKET" prefix = "streaming" }
}
