#!/usr/bin/env bash
# Reverse of stop.sh — scale everything back to 1 replica, in dependency order
# (data first, so app pods that depend on it don't just crash-loop while waiting).
# Nothing here is a "setup" step — every object already exists; this only restores
# replica counts. ArgoCD's credentials and rootpath/basehref/insecure config were never
# touched by stop.sh, so login and routing both work immediately once pods are Ready.
set -uo pipefail
REGION="${REGION:-asia-south1}"

echo "=== Confirming cluster context ==="
gcloud container clusters get-credentials streaming-auto --region="$REGION"

echo "=== 1/4 Scaling up data first (namespace: streaming) ==="
kubectl scale statefulset postgres-postgresql redis-master -n streaming --replicas=1 2>/dev/null || true
kubectl -n streaming rollout status statefulset postgres-postgresql --timeout=180s 2>/dev/null || true
kubectl -n streaming rollout status statefulset redis-master --timeout=180s 2>/dev/null || true

echo "=== 2/4 Scaling up CI/CD tools (namespace: cicd) ==="
kubectl scale statefulset jenkins sonarqube-sonarqube -n cicd --replicas=1 2>/dev/null || true

echo "=== 3/4 Scaling up ArgoCD (namespace: argocd) ==="
kubectl scale deployment argocd-redis argocd-repo-server -n argocd --replicas=1 2>/dev/null || true
kubectl scale statefulset argocd-application-controller -n argocd --replicas=1 2>/dev/null || true
kubectl scale deployment argocd-dex-server argocd-server argocd-applicationset-controller \
  argocd-notifications-controller -n argocd --replicas=1 2>/dev/null || true

echo "=== 4/4 Scaling up the app tier (namespace: streaming) — ArgoCD self-heal may beat you to this ==="
kubectl scale deployment api-gateway frontend catalog-service user-service playback-service \
  -n streaming --replicas=1 2>/dev/null || true

echo "=== Scaling up monitoring (namespace: monitoring), if installed ==="
kubectl scale statefulset -n monitoring -l app.kubernetes.io/name=prometheus --replicas=1 2>/dev/null || true
kubectl scale deployment -n monitoring -l app.kubernetes.io/name=grafana --replicas=1 2>/dev/null || true

echo
echo "=== Watching pods come up — Ctrl+C once everything shows Running/Ready ==="
kubectl get pods -A -w
