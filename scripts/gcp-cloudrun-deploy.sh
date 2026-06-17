#!/bin/bash
# Deploy to Cloud Run — enkel versjon med --source
set -e

PROJECT_ID=$(gcloud config get-value project)
REGION="europe-north1"
SERVICE_NAME="statistics-for-strava"

echo "=== Deploying to Cloud Run ==="
echo "Project: $PROJECT_ID"
echo "Region:  $REGION"
echo ""

gcloud run deploy ${SERVICE_NAME} \
    --source=. \
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
    --set-env-vars="APP_ENV=prod" \
    --set-env-vars="APP_DEBUG=0" \
    --set-env-vars="GARMIN_USER=${GARMIN_USER}" \
    --set-env-vars="GARMIN_PASSWORD=${GARMIN_PASSWORD}" \
    --set-env-vars="GARMIN_SESSION_TOKEN=${GARMIN_SESSION_TOKEN:-}"

SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region=${REGION} --format="value(status.url)")
echo ""
echo "=== Done! ==="
echo "App URL: ${SERVICE_URL}"
