#!/bin/sh
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

# Write .env.local
cat > /var/www/.env.local << ENVEOF
GARMIN_BRIDGE_BASE_URI=http://localhost:5000/
STRAVA_CLIENT_ID=0
STRAVA_CLIENT_SECRET=0
STRAVA_REFRESH_TOKEN=0
ENVEOF

# Run migrations (non-blocking — may fail on first boot, that's ok)
php /var/www/bin/console app:db:migrate --no-interaction 2>/dev/null || true

# Start Garmin bridge in background (don't wait for it)
python3 /var/www/garmin-bridge/app.py > /dev/null 2>&1 &

# Start FrankenPHP immediately
exec frankenphp run --config /etc/frankenphp/Caddyfile
