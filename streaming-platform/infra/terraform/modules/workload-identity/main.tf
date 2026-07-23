resource "google_service_account" "gsa" {
  account_id   = var.gsa_name
  display_name = "Streaming workloads SA"
}

resource "google_project_iam_member" "roles" {
  for_each = toset(var.roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.gsa.email}"
}

# Bind the Kubernetes SA (namespace/ksa) to this GSA for keyless auth.
resource "google_service_account_iam_member" "wi" {
  service_account_id = google_service_account.gsa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.namespace}/${var.ksa}]"
}
