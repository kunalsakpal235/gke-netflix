# Phase 5 — storage & data
Video bucket, and (optional) Cloud SQL + Memorystore. In-cluster Postgres/Redis are installed
with Helm instead (see the runbook). Depends on: Phase 0. Do this BEFORE deploying the app.
```bash
terraform init && terraform apply
# managed data (costs money):
terraform apply -var enable_cloud_sql=true -var enable_memorystore=true
```
