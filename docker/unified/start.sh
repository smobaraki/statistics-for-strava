#!/bin/sh
set -e

echo "Starting Statistics for Strava (unified container)..."

# Set timezone
echo "date.timezone=\"${TZ:-UTC}\"" > "${PHP_INI_DIR}/conf.d/timezone.ini"

# Generate APP_SECRET if not set
if [ -z "$APP_SECRET" ]; then
    export APP_SECRET="$(php -r 'echo bin2hex(random_bytes(16));')"
fi

# Run database migrations
flock /var/www/storage/database/migrate.lock \
    php /var/www/bin/console app:db:migrate --no-interaction || true

# Create required directories
mkdir -p /var/www/storage/database /var/www/storage/files /var/www/build /var/www/watch

# Start Garmin bridge in background
echo "Starting Garmin bridge..."
python3 /var/www/garmin-bridge/app.py &
BRIDGE_PID=$!

# Wait for bridge to be ready
for i in $(seq 1 30); do
    if curl -sf http://localhost:5000/health > /dev/null 2>&1; then
        echo "Garmin bridge is ready"
        break
    fi
    sleep 1
done

# Start import daemon in background
echo "Starting import daemon..."
php /var/www/bin/console app:daemon:run &

# Start FrankenPHP web server (foreground - keeps container alive)
echo "Starting web server on port 8080..."
exec frankenphp run --config /etc/frankenphp/Caddyfile
