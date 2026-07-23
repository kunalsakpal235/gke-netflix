#!/usr/bin/env bash
set -euo pipefail
# Fill these in:
export PROJECT_ID="${PROJECT_ID:-devops-1-502311}"
export REGION="${REGION:-asia-south1}"
export ZONE="${ZONE:-asia-south1-a}"

gcloud config set project "$PROJECT_ID"
gcloud services enable container.googleapis.com artifactregistry.googleapis.com \
  compute.googleapis.com secretmanager.googleapis.com iamcredentials.googleapis.com \
  storage.googleapis.com pubsub.googleapis.com

# Network
gcloud compute networks create streaming-vpc --subnet-mode=custom || true
gcloud compute networks subnets create gke-subnet --network=streaming-vpc --region="$REGION" \
  --range=10.10.0.0/20 --secondary-range=pods=10.20.0.0/16,services=10.30.0.0/20 \
  --enable-private-ip-google-access || true
gcloud compute firewall-rules create allow-health-checks --network=streaming-vpc \
  --direction=INGRESS --action=ALLOW --rules=tcp --source-ranges=35.191.0.0/16,130.211.0.0/22 || true

# Cluster (Autopilot)
gcloud container clusters create-auto streaming-auto --region="$REGION" \
  --network=streaming-vpc --subnetwork=gke-subnet \
  --cluster-secondary-range-name=pods --services-secondary-range-name=services \
  --release-channel=regular
gcloud container clusters get-credentials streaming-auto --region="$REGION"

# Registry + namespace
gcloud artifacts repositories create streaming-images --repository-format=docker --location="$REGION" || true
kubectl apply -f k8s/namespace.yaml
echo "Done. Next: build/push a service and deploy (see runbook)."
