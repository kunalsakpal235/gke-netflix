#!/usr/bin/env bash
# Rewritten alongside stop.sh for the same reason: streaming-staging and
# streaming-production now exist, every service has an HPA, and all 3 ArgoCD
# Applications have selfHeal on. Given that, the cleanest way to bring the app tier back
# up isn't to manually kubectl-scale 5 deployments across 3 namespaces (15 commands to
# maintain and keep in sync with the chart) - it's to simply restore each Application's
# automated syncPolicy and let ArgoCD reconcile everything to what Git already declares
# (replicaCount: 1) on its own. This also automatically fixes any HPA minReplicas drift,
# since the HPA is a Git-declared resource under the same Application, not something
# needing separate handling.
#
# Nothing here is a "setup" step - every object already exists; this only restores
# state. ArgoCD's credentials and rootpath/basehref/insecure config were never touched
# by stop.sh, so login and routing both work immediately once pods are Ready.
#
# Safe to run from a fresh terminal/session - explicitly sets project/region context
# rather than assuming gcloud's ambient config is already correct.
#
# --full flag: use this ONLY if you ran `stop.sh --full` last time (which deleted the
# Gateway/HTTPRoute/policy layer). Re-applies those manifests from the repo. It does NOT
# recreate the Cloud Armor policy or its specific allowed-IP rules - those are personal
# and aren't safely re-creatable from a generic file. You'll need to redo that part
# yourself; see "Exposing admin tools" in the runbook for the exact commands.
set -uo pipefail

FULL=false
[ "${1:-}" = "--full" ] && FULL=true

PROJECT_ID="${PROJECT_ID:-devops-1-502311}"
REGION="${REGION:-asia-south1}"
CLUSTER_NAME="${CLUSTER_NAME:-streaming-auto}"
# Only needed as a fallback if billing somehow isn't linked (see step 1) - leave unset
# if you don't know it; the script only uses it in that one edge case.
BILLING_ACCOUNT_ID="${BILLING_ACCOUNT_ID:-}"

ARGO_APPS=(streaming-dev streaming-staging streaming-production)

echo "=== 0/6 Setting project context ==="
gcloud config set project "$PROJECT_ID"

echo "=== 1/6 Confirming billing is linked (won't touch it if already fine) ==="
BILLING_ENABLED=$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)' 2>/dev/null || echo "false")
if [ "$BILLING_ENABLED" != "True" ]; then
  echo "  Billing not enabled on $PROJECT_ID."
  if [ -n "$BILLING_ACCOUNT_ID" ]; then
    echo "  Attempting to link billing account $BILLING_ACCOUNT_ID..."
    gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT_ID"
  else
    echo "  Set BILLING_ACCOUNT_ID and re-run to link it, e.g.:"
    echo "  BILLING_ACCOUNT_ID=XXXXXX-XXXXXX-XXXXXX ./start.sh"
    exit 1
  fi
else
  echo "  Billing already linked — nothing to do."
fi

echo "=== 2/6 Authenticating to the GKE cluster ==="
gcloud container clusters get-credentials "$CLUSTER_NAME" --region="$REGION" --project="$PROJECT_ID"
kubectl get nodes

echo "=== 3/6 Scaling up data first (namespace: streaming) — dev's shared Postgres/Redis ==="
kubectl scale statefulset postgres-postgresql redis-master -n streaming --replicas=1 2>/dev/null || true
kubectl -n streaming rollout status statefulset postgres-postgresql --timeout=180s 2>/dev/null || true
kubectl -n streaming rollout status statefulset redis-master --timeout=180s 2>/dev/null || true

echo "=== 4/6 Scaling up CI/CD tools (namespace: cicd) and ArgoCD itself (namespace: argocd) ==="
kubectl scale statefulset sonarqube-db-postgresql jenkins sonarqube-sonarqube -n cicd --replicas=1 2>/dev/null || true
kubectl scale deployment argocd-redis argocd-repo-server -n argocd --replicas=1 2>/dev/null || true
kubectl scale statefulset argocd-application-controller -n argocd --replicas=1 2>/dev/null || true
kubectl scale deployment argocd-dex-server argocd-server argocd-applicationset-controller \
  argocd-notifications-controller -n argocd --replicas=1 2>/dev/null || true

echo "=== 5/6 Restoring ArgoCD's automated sync — this brings the whole app tier back ==="
echo "    (all 3 apps, all 5 services each, correct HPA settings — all reconciled by ArgoCD"
echo "    itself from what Git already declares, not manually re-typed here)"
for app in "${ARGO_APPS[@]}"; do
  kubectl patch application "$app" -n argocd --type merge \
    -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}' 2>/dev/null || true
done
echo "    NOTE: ArgoCD's own background reconciliation loop picks this up within its normal"
echo "    interval (usually well under a few minutes) — this isn't instant, that's expected."

echo "=== 6/6 Scaling up monitoring (namespace: monitoring), if installed ==="
kubectl scale statefulset -n monitoring -l app.kubernetes.io/name=prometheus --replicas=1 2>/dev/null || true
kubectl scale deployment -n monitoring -l app.kubernetes.io/name=grafana --replicas=1 2>/dev/null || true

if [ "$FULL" = true ]; then
  echo
  echo "=== --full: re-applying the Gateway/Cloud Armor layer manifests ==="
  kubectl label namespace streaming cicd argocd gateway-access=streaming-gw --overwrite
  kubectl apply -f k8s/gateway.yaml
  kubectl apply -f k8s/httproute-cicd.yaml -f k8s/httproute-argocd.yaml
  echo "  NOTE: the Cloud Armor policy itself was NOT recreated — its allowed IPs are"
  echo "  personal and can't be safely guessed. Recreate it and re-add your IPs manually:"
  echo "  gcloud compute security-policies create admin-tools-allowlist ..."
  echo "  (see 'Exposing admin tools' in the runbook for the exact commands)"
  echo "  Then re-apply the GCPBackendPolicy + HealthCheckPolicy files once that policy exists:"
  echo "  kubectl apply -f k8s/gcpbackendpolicy-admin-tools.yaml"
  echo "  kubectl apply -f k8s/healthcheckpolicy-api-gateway.yaml -f k8s/healthcheckpolicy-jenkins.yaml \\"
  echo "    -f k8s/healthcheckpolicy-sonarqube.yaml -f k8s/healthcheckpolicy-argocd.yaml"
fi

echo
echo "=== Watching pods come up across all namespaces — Ctrl+C once everything shows Running/Ready ==="

echo"=== scaling down streaming-staging and streaming-production resources to 0"
bash /opt/gke-netflix/streaming-platform/scripts/streaming-staging-prod-scale-down.sh

kubectl get pods -A -w
