FROM python:3.12-slim

# ---------------------------------------------------------------------------
# System-level setup
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install supercronic (a cron-in-container replacement that plays nicely with
# Docker logs — no dependency on a full init system).
# Pin to a specific release for reproducibility.
ARG SUPERCRONIC_VERSION=0.2.29
ARG SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-linux-amd64
ARG SUPERCRONIC_SHA1=cd48d45c4b10f3f0bfdd3a57d054cd05ac96812b

RUN curl -fsSL "$SUPERCRONIC_URL" -o /usr/local/bin/supercronic \
    && echo "${SUPERCRONIC_SHA1}  /usr/local/bin/supercronic" | sha1sum -c - \
    && chmod +x /usr/local/bin/supercronic

# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------
WORKDIR /app

# Copy and install Python dependencies first (layer cache-friendly)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY auditor.py          /app/auditor.py
COPY report_template.html /app/report_template.html

# ---------------------------------------------------------------------------
# Crontab for supercronic (used when running via supercronic)
# The schedule here is the default; it can be overridden by mounting a
# custom crontab file to /app/crontab.
# ---------------------------------------------------------------------------
RUN echo "0 6 * * * python /app/auditor.py" > /app/crontab

# ---------------------------------------------------------------------------
# Runtime environment
# ---------------------------------------------------------------------------
# CONFIG_PATH can be overridden at runtime (e.g. -e CONFIG_PATH=/my/config.yaml)
ENV CONFIG_PATH=/app/config.yaml

# Create expected directories so the container can run without volume mounts
RUN mkdir -p /app/sample_logs /app/reports

# ---------------------------------------------------------------------------
# Default command
# ---------------------------------------------------------------------------
# Run auditor.py directly so that `docker run` works out-of-the-box for
# testing and one-shot execution.
# To run on a schedule instead, override the CMD:
#   docker run ... supercronic /app/crontab
CMD ["python", "/app/auditor.py"]
