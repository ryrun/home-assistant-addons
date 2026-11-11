FROM python:3.13.18-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONTZPATH=""
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt \
    && groupadd --gid 10002 eink \
    && useradd --uid 10002 --gid 10002 --no-create-home --shell /usr/sbin/nologin eink
COPY media.py storage.py playback.py network.py profiles.py scheduling.py battery.py diagnostics.py correction.py mqtt_bridge.py server.py startup.py ./
COPY web/ ./web/
EXPOSE 8098 8099
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8098/health', timeout=3)" || exit 1
CMD ["python", "/app/startup.py"]
