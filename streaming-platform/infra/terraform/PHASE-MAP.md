# Phase → Terraform map

| Phase / task | Terraform? | Where |
|---|---|---|
| 0 — enable APIs | yes | `phases/00-project` (module: none, uses google_project_service) |
| 1 — network (VPC/subnet/firewall/NAT) | yes | `phases/01-network` → `modules/network` |
| 2 — GKE cluster (+ network attach) | yes | `phases/02-cluster` → `modules/gke` |
| 3 — Artifact Registry | yes | `phases/03-registry` → `modules/artifact-registry` |
| 4 — security & identity (GSA, roles, WI) | yes | `phases/04-security` → `modules/workload-identity` |
| 5 — storage & data (bucket, Cloud SQL, Redis) | yes | `phases/05-data` → `modules/storage`, `modules/data` |
| 4 — K8s RBAC, network policies, Pod Security | kubectl | runbook Security section (optional: kubernetes provider) |
| 5 — in-cluster Postgres/Redis | Helm | runbook Phase 5 |
| 6 — build images | no | docker / kaniko |
| 7 — deploy app | no | Helm / ArgoCD |
| 8 — Jenkins, 9 — ArgoCD, 10 — monitoring | no | Helm |
| 11 — HA drills, 12 — load test | no | kubectl / k6 |
| 13 — teardown | Terraform or script | `terraform destroy` per phase, or `scripts/teardown.sh` |
