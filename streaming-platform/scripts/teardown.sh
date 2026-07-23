#!/usr/bin/env bash
# Full teardown of the streaming-platform infra, in reverse dependency order.
# Usage:  PROJECT_ID=devops-1-502311 REGION=asia-south1 ZONE=asia-south1-a ./scripts/teardown.sh
# Safe to re-run; every step ignores "not found".
set -uo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-asia-south1}"
ZONE="${ZONE:-asia-south1-a}"
CLUSTER="${CLUSTER:-streaming}"

echo "This DELETES the streaming-platform infra in project: $PROJECT_ID"
read -rp "Type the project id to confirm: " c
[ "$c" = "$PROJECT_ID" ] || { echo "aborted"; exit 1; }
gcloud config set project "$PROJECT_ID" >/dev/null

echo "==> cluster creds (ignore errors if already gone)"
gcloud container clusters get-credentials "$CLUSTER" --region "$REGION" 2>/dev/null \
  || gcloud container clusters get-credentials "$CLUSTER" --zone "$ZONE" 2>/dev/null || true

echo "==> Phase 10: observability"
helm uninstall monitoring loki -n monitoring 2>/dev/null || true
kubectl get crd 2>/dev/null | awk '/monitoring.coreos.com/{print $1}' | xargs -r kubectl delete crd 2>/dev/null || true
kubectl delete namespace monitoring --ignore-not-found 2>/dev/null || true

echo "==> Phase 9: ArgoCD"
kubectl delete application streaming-dev -n argocd --ignore-not-found 2>/dev/null || true
kubectl delete namespace argocd --ignore-not-found 2>/dev/null || true

echo "==> Phase 8: Jenkins / SonarQube"
helm uninstall jenkins sonarqube -n cicd 2>/dev/null || true
kubectl delete namespace cicd --ignore-not-found 2>/dev/null || true

echo "==> Phase 7: app workloads + Ingress (release the LB FIRST)"
kubectl delete ingress --all -n streaming --ignore-not-found 2>/dev/null || true
helm uninstall api-gateway frontend user-service catalog-service playback -n streaming 2>/dev/null || true
gcloud compute addresses delete streaming-ip --global --quiet 2>/dev/null || true

echo "==> Phase 5: data"
gcloud storage rm -r "gs://${PROJECT_ID}-video" 2>/dev/null || true
gcloud pubsub subscriptions delete transcode-sub --quiet 2>/dev/null || true
gcloud pubsub topics delete new-video --quiet 2>/dev/null || true
helm uninstall postgres redis -n streaming 2>/dev/null || true
gcloud sql instances delete streaming-pg --quiet 2>/dev/null || true
gcloud redis instances delete streaming-redis --region "$REGION" --quiet 2>/dev/null || true

echo "==> Phase 3: Artifact Registry"
gcloud artifacts repositories delete streaming-images --location "$REGION" --quiet 2>/dev/null || true

echo "==> Phase 2: the cluster (delete any leftover ingress first)"
kubectl delete ingress --all -A --ignore-not-found 2>/dev/null || true
gcloud container clusters delete "$CLUSTER" --region "$REGION" --quiet 2>/dev/null \
  || gcloud container clusters delete "$CLUSTER" --zone "$ZONE" --quiet 2>/dev/null || true

echo "==> Phase 4: IAM / service accounts"
for SA in streaming-workloads ci-builder; do
  gcloud iam service-accounts delete "${SA}@${PROJECT_ID}.iam.gserviceaccount.com" --quiet 2>/dev/null || true
done

echo "==> Phase 1: network (reverse order: NAT -> router -> firewall -> subnet -> VPC)"
gcloud compute routers nats delete streaming-vpc-nat --router streaming-vpc-router --region "$REGION" --quiet 2>/dev/null || true
gcloud compute routers delete streaming-vpc-router --region "$REGION" --quiet 2>/dev/null || true
gcloud compute firewall-rules delete streaming-vpc-allow-health-checks streaming-vpc-allow-internal --quiet 2>/dev/null || true
gcloud compute networks subnets delete gke-subnet --region "$REGION" --quiet 2>/dev/null || true
gcloud compute networks delete streaming-vpc --quiet 2>/dev/null || true

echo "==> VERIFY (all of these should be empty):"
gcloud compute forwarding-rules list 2>/dev/null || true
gcloud compute addresses list 2>/dev/null || true
gcloud compute disks list 2>/dev/null || true
gcloud container clusters list 2>/dev/null || true

echo
echo "Done. To remove EVERYTHING at once instead of the above, run:"
echo "  gcloud projects delete $PROJECT_ID"
echo "Or, if you built with Terraform:  (cd infra/terraform && terraform destroy)"
