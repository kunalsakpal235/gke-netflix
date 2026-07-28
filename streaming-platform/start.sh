#!/usr/bin/env bash
# Reverse of stop.sh — scale everything back to 1 replica, in dependency order
# (data first, so app pods that depend on it don't just crash-loop while waiting).
# Nothing here is a "setup" step — every object already exists; this only restores
# replica counts. ArgoCD's credentials and rootpath/basehref/insecure config were never
# touched by stop.sh, so login and routing both work immediately once pods are Ready.
#
# Safe to run from a fresh terminal/session — explicitly sets project/region context
# rather than assuming gcloud's ambient config is already correct.
#
# --full flag: use this ONLY if you ran `stop.sh --full` last time (which deleted the
# Gateway/HTTPRoute/policy layer). Re-applies those manifests from the repo. It does NOT
# recreate the Cloud Armor policy or its specific allowed-IP rules — those are personal
# (your jump server, laptop, anyone else you'd added) and aren't safely re-creatable from
# a generic file. You'll need to redo that part yourself; see "Exposing admin tools" in
# the runbook for the exact commands.
set -uo pipefail

FULL=false
[ "${1:-}" = "--full" ] && FULL=true

PROJECT_ID="${PROJECT_ID:-devops-1-502311}"
REGION="${REGION:-asia-south1}"
CLUSTER_NAME="${CLUSTER_NAME:-streaming-auto}"
# Only needed as a fallback if billing somehow isn't linked (see step 2) — leave unset
# if you don't know it; the script only uses it in that one edge case.
BILLING_ACCOUNT_ID="${BILLING_ACCOUNT_ID:-}"

echo "=== 0/5 Setting project context ==="
gcloud config set project "$PROJECT_ID"

echo "=== 1/5 Confirming billing is linked (won't touch it if already fine) ==="
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

echo "=== 2/5 Authenticating to the GKE cluster ==="
gcloud container clusters get-credentials "$CLUSTER_NAME" --region="$REGION" --project="$PROJECT_ID"
kubectl get nodes

echo "=== 3/5 Scaling up data first (namespace: streaming) ==="
kubectl scale statefulset postgres-postgresql redis-master -n streaming --replicas=1 2>/dev/null || true
kubectl -n streaming rollout status statefulset postgres-postgresql --timeout=180s 2>/dev/null || true
kubectl -n streaming rollout status statefulset redis-master --timeout=180s 2>/dev/null || true

echo "=== 4/5 Scaling up CI/CD tools (namespace: cicd) and ArgoCD (namespace: argocd) ==="
kubectl scale statefulset sonarqube-db-postgresql jenkins sonarqube-sonarqube -n cicd --replicas=1 2>/dev/null || true
kubectl scale deployment argocd-redis argocd-repo-server -n argocd --replicas=1 2>/dev/null || true
kubectl scale statefulset argocd-application-controller -n argocd --replicas=1 2>/dev/null || true
kubectl scale deployment argocd-dex-server argocd-server argocd-applicationset-controller \
  argocd-notifications-controller -n argocd --replicas=1 2>/dev/null || true

echo "=== 5/5 Scaling up the app tier (namespace: streaming) — ArgoCD self-heal may beat you to this ==="
kubectl scale deployment api-gateway frontend catalog-service user-service playback-service \
  -n streaming --replicas=1 2>/dev/null || true

echo "=== Scaling up monitoring (namespace: monitoring), if installed ==="
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
echo "=== Watching pods come up — Ctrl+C once everything shows Running/Ready ==="
kubectl get pods -A -w
