# Phase 0 — enable APIs
Enables the Google APIs the rest of the build needs.
```bash
export TF_VAR_project_id=devops-1-502311
terraform init && terraform apply
```
Depends on: nothing (project must already exist and billing be linked).
