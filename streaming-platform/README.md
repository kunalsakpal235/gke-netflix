# streaming-platform (starter repo)

A learning-grade Netflix/Hotstar-style platform on GKE, wired for Jenkins CI + ArgoCD GitOps.
This scaffold pairs with the runbook PDF — each folder maps to a phase.

## Layout
- `services/` — polyglot microservices (Node, Go, Java, Next.js) with `/healthz` + `/readyz`
- `charts/streaming/` — Helm chart (Deployment, Service, HPA, PDB, Ingress)
- `k8s/` — raw manifests (namespace, network policy) to learn before Helm
- `gitops/` — ArgoCD Application + per-env values (GitOps source of truth)
- `jenkins/` — Jenkinsfile + kaniko agent pod
- `infra/` — `setup.sh` (project, network, cluster) 
- `load-tests/` — k6 script
- `scripts/` — `start.sh` / `stop.sh` (cost control)

## Quick start
1. `./infra/setup.sh` — creates project resources, VPC, and a GKE Autopilot cluster.
2. Build + push a service, e.g. api-gateway (Phase 4).
3. `kubectl apply -f k8s/namespace.yaml` then deploy via Helm or the ArgoCD app.
4. Point Jenkins at `jenkins/Jenkinsfile`; point ArgoCD at `gitops/apps/streaming-dev.yaml`.

## Fill in devops-1-502311 / repo URL
Search-replace `devops-1-502311` and `YOUR_GH` before use.

See the runbook for full step-by-step and gap-fillers.
