#!/usr/bin/env bash
set -euo pipefail
REGION="${REGION:-asia-south1}"
# Recreate/scale the cluster up for a work session.
gcloud container clusters get-credentials streaming-auto --region="$REGION"
kubectl get nodes
