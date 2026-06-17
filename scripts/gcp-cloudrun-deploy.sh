#!/bin/bash
# Deploy to Cloud Run — bygg lokalt, push, deploy med persistent storage
set -e

PROJECT_ID=$(gcloud config get-value project)
REGION="europe-north1"
SERVICE_NAME="statistics-for-strava"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/sfs/app:latest"
BUCKET="${PROJECT_ID}-sfs-storage"

echo "=== 1. Create GCS bucket for persistent data ==="
gcloud storage buckets create gs://${BUCKET} \
    --location=${REGION} \
    --uniform-bucket-level-access 2>/dev/null || echo "(bucket exists)"

echo ""
echo "=== 2. Build Docker image locally ==="
docker build --platform linux/amd64 -f Dockerfile.cloudrun -t ${IMAGE} .

echo ""
echo "=== 3. Push to Artifact Registry ==="
gcloud artifacts repositories create sfs \
    --repository-format=docker \
    --location=${REGION} 2>/dev/null || true

gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet
docker push ${IMAGE}

echo ""
echo "=== 4. Deploy to Cloud Run ==="
gcloud run deploy ${SERVICE_NAME} \
    --image=${IMAGE} \
    --region=${REGION} \
    --platform=managed \
    --allow-unauthenticated \
    --memory=1Gi \
    --cpu=1 \
    --timeout=600 \
    --add-volume=name=storage,type=cloud-storage,bucket=${BUCKET} \
    --add-volume-mount=volume=storage,mount-path=/var/www/storage \
    --set-env-vars="GARMIN_BRIDGE_BASE_URI=http://localhost:5000/" \
    --set-env-vars="STRAVA_CLIENT_ID=0" \
    --set-env-vars="STRAVA_CLIENT_SECRET=0" \
    --set-env-vars="STRAVA_REFRESH_TOKEN=0" \
    --set-env-vars="APP_ENV=prod" \
    --set-env-vars="APP_DEBUG=0" \
    --set-env-vars="GARMIN_USER=${GARMIN_USER}" \
    --set-env-vars="GARMIN_PASSWORD=${GARMIN_PASSWORD}" \
    --set-env-vars="GARMIN_SESSION_TOKEN=${GARMIN_SESSION_TOKEN:-}"

SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region=${REGION} --format="value(status.url)")

echo ""
echo "=== 5. Trigger initial import ==="
curl -s "${SERVICE_URL}/api/trigger-import" || echo "(import triggered, may take a minute)"

echo ""
echo "=== Done! ==="
echo "App URL: ${SERVICE_URL}"
echo ""
echo "After import completes (~2 min), refresh the page."
