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

# Run migrations
php /var/www/bin/console app:db:migrate --no-interaction || true

# Start Garmin bridge in background
echo "Starting Garmin bridge..."
python3 /var/www/garmin-bridge/app.py &
BRIDGE_PID=$!

# Wait for bridge
for i in $(seq 1 30); do
    if curl -sf http://localhost:5000/health > /dev/null 2>&1; then
        echo "Garmin bridge ready"
        break
    fi
    sleep 1
done

# Run a quick import in background if no data exists (first boot)
if [ ! -f /var/www/storage/database/dreeve.db ] || [ $(php -r "echo (new SQLite3('/var/www/storage/database/dreeve.db'))->querySingle('SELECT COUNT(*) FROM activity');" 2>/dev/null || echo 0) -eq 0 ]; then
    echo "First boot — running initial import in background..."
    php /var/www/bin/console app:data:import &
fi

# Start FrankenPHP on Cloud Run's PORT
echo "Starting web server on port ${PORT:-8080}..."
exec frankenphp run --config /etc/frankenphp/Caddyfile
