FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY garmin-bridge/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY garmin-bridge/ .

ENV GARMIN_CONFIG_DIR=/config
ENV GARMIN_CACHE_TTL=600

VOLUME ["/config"]

HEALTHCHECK --interval=60s --timeout=10s CMD curl -f http://localhost:5000/health || exit 1

EXPOSE 5000
CMD ["python", "app.py"]
