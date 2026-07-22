#!/usr/bin/env bash
set -euo pipefail
REGION="${REGION:-asia-south1}"
# Cost control: delete the LB/ingress and the cluster between sessions.
kubectl delete ingress --all -A --ignore-not-found
gcloud container clusters delete streaming-auto --region="$REGION" --quiet
echo "Torn down. Cloud Storage + Artifact Registry are kept (cheap)."
