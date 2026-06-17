#!/bin/bash
# Deploy to Cloud Run with persistent SQLite via Cloud Storage
set -e

PROJECT_ID=$(gcloud config get-value project)
REGION="europe-north1"       # Finland — lav latency til Skandinavia
SERVICE_NAME="statistics-for-strava"
BUCKET_NAME="${PROJECT_ID}-sfs-data"
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/sfs/app"

echo "=== 1. Create Cloud Storage bucket for persistent data ==="
gcloud storage buckets create gs://${BUCKET_NAME} \
    --location=${REGION} \
    --uniform-bucket-level-access 2>/dev/null || echo "Bucket already exists"

echo ""
echo "=== 2. Build and push Docker image ==="
gcloud artifacts repositories create sfs \
    --repository-format=docker \
    --location=${REGION} 2>/dev/null || echo "Repo already exists"

gcloud builds submit \
    --region=${REGION} \
    --tag ${IMAGE_NAME}:latest \
    --dockerfile=Dockerfile.cloudrun \
    .

echo ""
echo "=== 3. Deploy to Cloud Run ==="
gcloud run deploy ${SERVICE_NAME} \
    --image=${IMAGE_NAME}:latest \
    --region=${REGION} \
    --platform=managed \
    --allow-unauthenticated \
    --memory=1Gi \
    --cpu=1 \
    --timeout=600 \
    --set-env-vars="GARMIN_BRIDGE_BASE_URI=http://localhost:5000/" \
    --set-env-vars="STRAVA_CLIENT_ID=0" \
    --set-env-vars="STRAVA_CLIENT_SECRET=0" \
    --set-env-vars="STRAVA_REFRESH_TOKEN=0" \
    --set-env-vars="GARMIN_USER=${GARMIN_USER}" \
    --set-env-vars="GARMIN_PASSWORD=${GARMIN_PASSWORD}" \
    --set-env-vars="GARMIN_SESSION_TOKEN=${GARMIN_SESSION_TOKEN:-}" \
    --add-volume=name=data,type=cloud-storage,bucket=${BUCKET_NAME} \
    --add-volume-mount=volume=data,mount-path=/var/www/storage

echo ""
echo "=== 4. Schedule periodic imports ==="
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region=${REGION} --format="value(status.url)")

gcloud scheduler jobs create http sfs-import-trigger \
    --location=${REGION} \
    --schedule="0 */4 * * *" \
    --uri="${SERVICE_URL}/" \
    --http-method=GET \
    --time-zone="Europe/Oslo" 2>/dev/null || echo "Scheduler job already exists"

echo ""
echo "=== Done! ==="
echo "App URL: ${SERVICE_URL}"
echo ""
echo "For custom domain, run:"
echo "  gcloud run domain-mappings create --service=${SERVICE_NAME} --domain=stats.dittdomene.no --region=${REGION}"
