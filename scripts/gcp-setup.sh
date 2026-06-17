#!/bin/bash
# Run this on your GCP Compute Engine instance
# curl -sL https://raw.githubusercontent.com/smobaraki/statistics-for-strava/master/scripts/gcp-setup.sh | bash

set -e

echo "=== Installing Docker ==="
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER
newgrp docker <<'DOCKER_SETUP'

echo "=== Cloning project ==="
cd /opt
sudo git clone https://github.com/smobaraki/statistics-for-strava.git
sudo chown -R $USER:$USER statistics-for-strava
cd statistics-for-strava

echo "=== Creating config files ==="

# App configuration (copy the one committed to repo)
# Already at config/app/config.yaml — edit as needed

# Garmin credentials + bridge config
if [ -n "$GARMIN_USER" ] && [ -n "$GARMIN_PASSWORD" ]; then
    cat > garmin-bridge/config/GarminConnectConfig.json << EOF
{"user": "$GARMIN_USER", "password": "$GARMIN_PASSWORD"}
EOF
    echo "Garmin config created from env vars"
else
    echo "WARN: Set GARMIN_USER and GARMIN_PASSWORD env vars before running"
    echo "  export GARMIN_USER=din@epost.no"
    echo "  export GARMIN_PASSWORD=ditt-passord"
    exit 1
fi

# Garmin session token (base64 encoded, avoids MFA)
if [ -n "$GARMIN_SESSION_TOKEN" ]; then
    echo "$GARMIN_SESSION_TOKEN" | base64 -d > garmin-bridge/config/garmin_token.json
    echo "Garmin session token restored"
else
    echo "WARN: No GARMIN_SESSION_TOKEN — MFA will be required on first login"
    echo "  Generate locally: base64 garmin-bridge/config/garmin_token.json"
fi

# Environment file for Docker
cat > .env.local << 'EOF'
GARMIN_BRIDGE_BASE_URI=http://garmin-bridge:5000/
STRAVA_CLIENT_ID=0
STRAVA_CLIENT_SECRET=0
STRAVA_REFRESH_TOKEN=0
EOF

echo "=== Starting services ==="
docker compose up -d

echo ""
echo "=== Done! ==="
echo "App running on http://$(curl -s ifconfig.me):8081"
echo ""
echo "To update: cd /opt/statistics-for-strava && git pull && docker compose up -d --build"
DOCKER_SETUP
