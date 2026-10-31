FROM python:3.13.18-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY streaming.py cache.py auth.py errors.py server.py trakt_client.py setup_flow.py http_utils.py personal_cache.py security.py metrics.py dashboard.py run.sh ./
RUN groupadd --gid 10001 trakt && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin trakt && chmod 755 /app/run.sh
COPY web/ ./web/
EXPOSE 8765 8099
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=3)" || exit 1
CMD ["/app/run.sh"]
