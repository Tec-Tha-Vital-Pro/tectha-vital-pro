# Tec Tha Vital - production image.
#   docker build -t tectha-care .
#   docker compose up -d            (see docker-compose.yml and docs/DEPLOY.md)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Kolkata \
    TT_DB_PATH=/data/tectha.db \
    TT_BACKUP_DIR=/data/backups

WORKDIR /app

# Dependencies first so code changes do not re-download them.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY deploy ./deploy

# Run as an unprivileged user; the database lives on the /data volume. /app/data points there too,
# so the app's own fallback session secret (data/.session_secret) survives rebuilds.
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin tectha \
 && mkdir -p /data/backups \
 && ln -s /data /app/data \
 && chown -R tectha:tectha /data \
 && chmod 700 /data
USER tectha
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" || exit 1

# Exactly ONE worker: the automation scheduler runs inside the server process, so more workers
# would send every reminder more than once. --proxy-headers lets the app see HTTPS from Caddy
# (needed for secure login cookies). Only Caddy should reach port 8000 (see docker-compose.yml).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
