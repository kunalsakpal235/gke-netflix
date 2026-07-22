output "email" { value = google_service_account.gsa.email }
# Remember to annotate the K8s SA:
# kubectl annotate sa <ksa> -n <ns> iam.gke.io/gcp-service-account=<email>
