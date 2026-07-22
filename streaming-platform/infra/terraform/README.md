# Terraform IaC for the streaming platform

Modular, one module per segment. Customize everything via variables (see `variables.tf`).

## Usage
```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # edit project_id etc.
terraform init
terraform plan
terraform apply
# ... work ...
terraform destroy      # deletion_protection is off for easy teardown
```

## Modules
- `network` — VPC, subnet + **secondary ranges** (pods/services), firewall (health-checks/internal), optional Cloud NAT.
- `gke` — the cluster; toggle `cluster_mode = autopilot|standard`. The **cluster network is specified explicitly** via `network`, `subnetwork`, and `ip_allocation_policy` (secondary range names).
- `artifact-registry` — Docker repo.
- `workload-identity` — GSA, IAM roles, and the WI binding to your Kubernetes SA.
- `storage` — video bucket (uniform access).
- `data` — optional Cloud SQL + Memorystore (off by default).

## Reuse an existing network
Set `create_network = false` and pass `existing_network`, `existing_subnet`,
`existing_pods_range`, `existing_services_range`.
