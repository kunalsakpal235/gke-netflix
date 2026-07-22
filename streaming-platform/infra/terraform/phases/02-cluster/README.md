# Phase 2 — GKE cluster
Creates the cluster, attaching it to the network from Phase 1 (read via remote_state).
Depends on: Phase 1. After apply: `gcloud container clusters get-credentials streaming --region asia-south1`.
```bash
terraform init && terraform apply
```
