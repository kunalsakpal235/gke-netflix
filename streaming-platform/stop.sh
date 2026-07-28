#!/usr/bin/env bash
# Two distinct levels, deliberately kept separate:
#
# DEFAULT (no flag): scale every Deployment/StatefulSet to 0 replicas, namespace by
# namespace, in dependency-safe order. This is NOT a teardown — every PVC/Secret/ConfigMap
# stays exactly as it is. ArgoCD's admin password (a Secret) and its rootpath/basehref/
# insecure config (a ConfigMap) both survive completely untouched. Fully reversible in
# minutes via start.sh. This covers all CPU/memory cost.
#
# --full flag: ADDITIONALLY deletes the Gateway, HTTPRoutes, GCPBackendPolicy,
# HealthCheckPolicy, and Cloud Armor policy — the pieces that have no replica count to
# scale and keep costing (~₹100/day) regardless of whether any pod is running. This is
# real, deliberate teardown: recreating this layer next time means redoing the 15-20+
# minute Gateway propagation wait and the Cloud Armor allowlist rules from scratch.
# Only run this if you're stepping away long enough that the saved cost is worth that
# rework — not for routine day-to-day pauses.
#
# For a FULL cluster teardown (cluster itself deleted), see teardown.sh instead —
# a deliberately more destructive action than either level here.
set -uo pipefail

FULL=false
[ "${1:-}" = "--full" ] && FULL=true

echo "=== 1/4 Scaling down ArgoCD (namespace: argocd) — first, so self-heal doesn't fight step 2 ==="
kubectl scale deployment argocd-server argocd-repo-server argocd-redis \
  argocd-dex-server argocd-applicationset-controller argocd-notifications-controller \
  -n argocd --replicas=0 2>/dev/null || true
kubectl scale statefulset argocd-application-controller -n argocd --replicas=0 2>/dev/null || true

echo "=== 2/4 Scaling down the app tier + data (namespace: streaming) ==="
kubectl scale deployment api-gateway frontend catalog-service user-service playback-service \
  -n streaming --replicas=0 2>/dev/null || true
kubectl scale statefulset postgres-postgresql redis-master -n streaming --replicas=0 2>/dev/null || true

echo "=== 3/4 Scaling down CI/CD tools (namespace: cicd) ==="
kubectl scale statefulset jenkins sonarqube-sonarqube sonarqube-db-postgresql -n cicd --replicas=0 2>/dev/null || true

echo "=== 4/4 Scaling down monitoring (namespace: monitoring), if installed ==="
kubectl scale statefulset -n monitoring -l app.kubernetes.io/name=prometheus --replicas=0 2>/dev/null || true
kubectl scale deployment -n monitoring -l app.kubernetes.io/name=grafana --replicas=0 2>/dev/null || true

echo
echo "=== Remaining running pods (expect none from streaming/cicd/argocd/monitoring) ==="
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
  echo "PVCs/Secrets/ConfigMaps are untouched and will show 'no healthy upstream' until you"
  echo "run start.sh — expected, not broken. This still costs ~₹100/day; re-run with --full"
  echo "if you want that gone too and are OK with the rework next time."
fi
