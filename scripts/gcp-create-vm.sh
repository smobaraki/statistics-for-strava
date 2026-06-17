#!/bin/bash
# Deploy Statistics for Strava to GCP Compute Engine
# Prerequisites: gcloud CLI installed and authenticated

set -e

PROJECT_ID=$(gcloud config get-value project)
INSTANCE_NAME="statistics-for-strava"
ZONE="europe-north1-a"  # Skandinavia — endre etter behov
MACHINE_TYPE="e2-small" # 2 GB RAM, ~$12/mnd. e2-micro er gratis-tier

echo "=== Creating Compute Engine instance ==="
gcloud compute instances create $INSTANCE_NAME \
    --project=$PROJECT_ID \
    --zone=$ZONE \
    --machine-type=$MACHINE_TYPE \
    --boot-disk-size=20GB \
    --boot-disk-type=pd-standard \
    --image-family=ubuntu-2404-lts-amd64 \
    --image-project=ubuntu-os-cloud \
    --tags=http-server,https-server

echo "=== Opening firewall for HTTP/HTTPS ==="
gcloud compute firewall-rules create allow-http-8081 \
    --project=$PROJECT_ID \
    --allow tcp:8081 \
    --target-tags=http-server \
    --description="Allow HTTP on port 8081" 2>/dev/null || true

echo ""
echo "Instance created. Now SSH in and run the setup script:"
echo ""
echo "  gcloud compute ssh $INSTANCE_NAME --zone=$ZONE"
echo ""
echo "Then on the VM, run:"
echo ""
echo "  curl -sL https://raw.githubusercontent.com/smobaraki/statistics-for-strava/master/scripts/gcp-setup.sh | bash"
