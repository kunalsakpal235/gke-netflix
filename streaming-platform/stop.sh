#!/usr/bin/env bash
# Scale everything to 0 replicas, namespace by namespace, in dependency-safe order.
# This is NOT a teardown — every Deployment/StatefulSet/PVC/Secret/ConfigMap stays exactly
# as it is, just with 0 pods running. Nothing here costs rework: ArgoCD's admin password
# (a Secret) and its rootpath/basehref/insecure config (a ConfigMap) both survive this
# completely untouched, since scaling replicas never creates, deletes, or resets either kind
# of object. Only an actual reinstall (`kubectl apply -f .../install.yaml`) or `kubectl delete`
# would do that — this script does neither.
#
# For a full teardown (cluster + LB deleted, real rework required to rebuild) see teardown.sh
# instead — that is a deliberately different, more destructive action.
set -uo pipefail

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
kubectl scale statefulset jenkins sonarqube-sonarqube -n cicd --replicas=0 2>/dev/null || true

echo "=== 4/4 Scaling down monitoring (namespace: monitoring), if installed ==="
kubectl scale statefulset -n monitoring -l app.kubernetes.io/name=prometheus --replicas=0 2>/dev/null || true
kubectl scale deployment -n monitoring -l app.kubernetes.io/name=grafana --replicas=0 2>/dev/null || true

echo
echo "=== Remaining running pods (expect none from streaming/cicd/argocd/monitoring) ==="
kubectl get pods -A | grep -v "Completed\|kube-system\|gke-gmp-system\|NAMESPACE" || echo "(none — fully scaled down)"
echo
echo "Scaled down. The Gateway, HTTPRoutes, Cloud Armor policy, and all PVCs/Secrets/ConfigMaps"
echo "are untouched and will show 'no healthy upstream' until you run start.sh — expected, not broken."
