# Per-phase Terraform

One small stack per Terraform-able phase, each reusing the shared modules in `../modules/`.
They chain via `terraform_remote_state` (local state), so **apply in order**:

```bash
export TF_VAR_project_id=devops-1-502311
for d in 00-project 01-network 02-cluster 03-registry 04-security 05-data; do
  (cd "$d" && terraform init -input=false && terraform apply -auto-approve)
done
```

Tear down in reverse:
```bash
for d in 05-data 04-security 03-registry 02-cluster 01-network 00-project; do
  (cd "$d" && terraform destroy -auto-approve)
done
```

Phases 6+ (build, deploy, Jenkins, ArgoCD, monitoring) are not Terraform — they use
docker/kaniko, Helm, and kubectl. See `PHASE-MAP.md`.

The single composed root in `../` (one `terraform apply`) remains available if you prefer
to provision everything at once.
