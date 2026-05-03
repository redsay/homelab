FROM python:3.12-slim

LABEL maintainer="homelab"
LABEL description="Manufacturing Data Simulator — fake PLC/MES Prometheus exporter"

# Create non-root user for security
RUN groupadd -r simuser && useradd -r -g simuser simuser

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY config.yaml .
COPY sim_engine.py .
COPY server.py .

# Create log directory and set ownership
RUN mkdir -p /app/logs && chown -R simuser:simuser /app

USER simuser

EXPOSE 9200

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:9200/health')" \
    || exit 1

CMD ["python3", "server.py"]
