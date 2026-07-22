# Phase 1 — network
VPC + subnet (with pod/service secondary ranges) + firewall (+ optional Cloud NAT).
Depends on: Phase 0. Consumed by: Phase 2 (via terraform_remote_state).
```bash
terraform init && terraform apply
```
