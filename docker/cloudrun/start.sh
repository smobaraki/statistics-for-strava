#!/bin/sh
set -e

echo "Starting Statistics for Strava (Cloud Run)..."
echo "Port: ${PORT:-8080}"

# Timezone
echo "date.timezone=\"${TZ:-UTC}\"" > "${PHP_INI_DIR}/conf.d/timezone.ini"

# APP_SECRET
if [ -z "$APP_SECRET" ]; then
    export APP_SECRET="$(php -r 'echo bin2hex(random_bytes(16));')"
fi

# Ensure directories exist
mkdir -p /var/www/storage/database /var/www/storage/files /var/www/build /var/www/watch

echo "Running migrations..."
php /var/www/bin/console app:db:migrate --no-interaction 2>&1 || echo "Migration warning (may be OK)"

# Write .env.local from env vars
cat > /var/www/.env.local << ENVEOF
GARMIN_BRIDGE_BASE_URI=http://localhost:5000/
STRAVA_CLIENT_ID=0
STRAVA_CLIENT_SECRET=0
STRAVA_REFRESH_TOKEN=0
ENVEOF

# Start Garmin bridge in background
echo "Starting Garmin bridge..."
python3 /var/www/garmin-bridge/app.py 2>&1 &
BRIDGE_PID=$!

# Wait for bridge health
for i in $(seq 1 30); do
    if curl -sf http://localhost:5000/health > /dev/null 2>&1; then
        echo "Garmin bridge ready"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "WARNING: Garmin bridge not ready after 30s, continuing anyway"
    fi
    sleep 1
done

echo "Starting web server on port ${PORT:-8080}..."
exec frankenphp run --config /etc/frankenphp/Caddyfile
