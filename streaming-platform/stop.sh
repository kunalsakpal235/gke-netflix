#!/usr/bin/env bash
# Rewritten to account for everything added since the last version:
#   - streaming-staging and streaming-production namespaces now exist, each running the
#     full 5-service app tier (multi-service Helm chart), not just the original "streaming"
#   - every service in all three namespaces now has an HPA (minReplicas: 1)
#   - all three ArgoCD Applications (streaming-dev/staging/production) have selfHeal: true
#
# Those last two points matter a lot: a plain "kubectl scale deployment --replicas=0" on
# any of these namespaces would very likely get silently reverted within seconds - either
# by the HPA enforcing its minReplicas floor, or by ArgoCD's self-heal treating the scale-
# down as drift from what Git declares. So app-tier namespaces are handled differently
# here than the rest: ArgoCD's automated sync is disabled FIRST (same technique used
# during tonight's api-gateway incident), which stops both fights before any scaling
# happens.
#
# Two distinct levels, deliberately kept separate:
#
# DEFAULT (no flag): scale every Deployment/StatefulSet to 0 replicas, namespace by
# namespace, in dependency-safe order. This is NOT a teardown - every PVC/Secret/ConfigMap
# stays exactly as it is. ArgoCD's admin password (a Secret) and its rootpath/basehref/
# insecure config (a ConfigMap) both survive completely untouched. Fully reversible via
# start.sh. This covers all CPU/memory cost.
#
# --full flag: ADDITIONALLY deletes the Gateway, HTTPRoutes, GCPBackendPolicy,
# HealthCheckPolicy, and Cloud Armor policy - the pieces that have no replica count to
# scale and keep costing (~₹100/day) regardless of whether any pod is running. Real,
# deliberate teardown: recreating this layer next time means redoing the 15-20+ minute
# Gateway propagation wait and the Cloud Armor allowlist rules from scratch. Only run this
# if you're stepping away long enough that the saved cost is worth that rework.
#
# For a FULL cluster teardown (cluster itself deleted), see teardown.sh instead.
set -uo pipefail

FULL=false
[ "${1:-}" = "--full" ] && FULL=true

APP_NAMESPACES=(streaming streaming-staging streaming-production)
ARGO_APPS=(streaming-dev streaming-staging streaming-production)

echo "=== 1/5 Disabling ArgoCD automated sync on all 3 Applications ==="
echo "    (prevents self-heal AND the HPAs' minReplicas floor from fighting the next steps)"
for app in "${ARGO_APPS[@]}"; do
  kubectl patch application "$app" -n argocd --type merge -p '{"spec":{"syncPolicy":null}}' 2>/dev/null || true
done

echo "=== 2/5 Scaling down ArgoCD itself (namespace: argocd) ==="
kubectl scale deployment argocd-server argocd-repo-server argocd-redis \
  argocd-dex-server argocd-applicationset-controller argocd-notifications-controller \
  -n argocd --replicas=0 2>/dev/null || true
kubectl scale statefulset argocd-application-controller -n argocd --replicas=0 2>/dev/null || true

echo "=== 3/5 Scaling down the app tier in all 3 namespaces (dev/staging/production) ==="
for ns in "${APP_NAMESPACES[@]}"; do
  echo "  -- $ns --"
  kubectl scale deployment frontend api-gateway catalog-service user-service playback-service \
    -n "$ns" --replicas=0 2>/dev/null || true
done
echo "=== Scaling down data (namespace: streaming) — dev's shared Postgres/Redis ==="
kubectl scale statefulset postgres-postgresql redis-master -n streaming --replicas=0 2>/dev/null || true

echo "=== 4/5 Scaling down CI/CD tools (namespace: cicd) ==="
kubectl scale statefulset jenkins sonarqube-sonarqube sonarqube-db-postgresql -n cicd --replicas=0 2>/dev/null || true

echo "=== 5/5 Scaling down monitoring (namespace: monitoring), if installed ==="
kubectl scale statefulset -n monitoring -l app.kubernetes.io/name=prometheus --replicas=0 2>/dev/null || true
kubectl scale deployment -n monitoring -l app.kubernetes.io/name=grafana --replicas=0 2>/dev/null || true

echo
echo "=== Remaining running pods (expect none from streaming*/cicd/argocd/monitoring) ==="
kubectl get pods -A | grep -v "Completed\|kube-system\|gke-gmp-system\|NAMESPACE" || echo "(none — fully scaled down)"

if [ "$FULL" = true ]; then
  echo
  echo "=== --full: also tearing down the Gateway/Cloud Armor layer (real rework next time) ==="
  kubectl delete -f k8s/healthcheckpolicy-api-gateway.yaml -f k8s/healthcheckpolicy-jenkins.yaml \
    -f k8s/healthcheckpolicy-sonarqube.yaml -f k8s/healthcheckpolicy-argocd.yaml --ignore-not-found
  kubectl delete -f k8s/httproute-cicd.yaml -f k8s/httproute-argocd.yaml --ignore-not-found
  kubectl delete -f k8s/httproute.yaml --ignore-not-found
  kubectl delete -f k8s/gcpbackendpolicy-admin-tools.yaml --ignore-not-found
  kubectl delete -f k8s/gateway.yaml --ignore-not-found
  gcloud compute security-policies delete admin-tools-allowlist --quiet 2>/dev/null || true
  echo "Gateway/Cloud Armor layer deleted. Re-provisioning next time will take real time —"
  echo "expect the same 15-20+ minute propagation wait as when this was first built."
else
  echo
  echo "Scaled down (replicas only). The Gateway, HTTPRoutes, Cloud Armor policy, and all"
  echo "PVCs/Secrets/ConfigMaps are untouched. ArgoCD's automated sync is intentionally OFF"
  echo "right now for all 3 apps — start.sh restores it, which is what brings everything"
  echo "back up. This still costs ~₹100/day; re-run with --full if you want that gone too."
fi
