# Cloud Run Dockerfile — stateless, enkel container
# Bruker PORT env var (satt av Cloud Run), ingen daemon
FROM dunglas/frankenphp:1-php8.5-alpine

WORKDIR /var/www

ENV APP_ENV=prod
ENV APP_DEBUG=0
ENV FRANKENPHP_CONFIG="worker /var/www/public/index.php"

# System deps + Python for Garmin bridge
RUN apk add --no-cache bash curl file flock tzdata geos python3 py3-pip

RUN set -eux; \
    install-php-extensions \
        bcmath ctype curl dom fileinfo gd intl mbstring opcache \
        pdo pdo_sqlite phar session simplexml tokenizer xml \
        xmlreader xmlwriter pcntl zstd

RUN pip3 install --no-cache-dir --break-system-packages flask garminconnect gpxpy

COPY docker/app/config/php.ini ${PHP_INI_DIR}/php.ini

# Custom Caddy config — listens on $PORT
COPY docker/cloudrun/Caddyfile /etc/frankenphp/Caddyfile

RUN curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer
ENV COMPOSER_ALLOW_SUPERUSER=1

COPY . /var/www/
RUN touch /var/www/.env
RUN mkdir -p /var/www/var/cache/prod /var/www/var/log /var/www/storage/database /var/www/build /var/www/watch
RUN composer install --no-dev --no-interaction --optimize-autoloader --no-scripts
RUN php /var/www/bin/console cache:clear --env=prod --no-interaction || true

# Startup: run bridge in background, then FrankenPHP on $PORT
COPY docker/cloudrun/start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh

ENV PORT=8080
EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/start.sh"]
