# Phase 4 — security & identity
Creates the GCP service account, its IAM roles, and the Workload Identity binding to the
Kubernetes SA (namespace/ksa). Depends on: Phase 0.
After apply, annotate the K8s SA once:
```bash
kubectl annotate sa streaming-workloads -n streaming \
  iam.gke.io/gcp-service-account=$(terraform output -raw workload_sa)
```
K8s RBAC and network policies are applied with kubectl (see the runbook's Security section).
