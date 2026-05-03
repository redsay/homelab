# system-monitor

A Python service that continuously monitors system health and service endpoints, exposing metrics in Prometheus format. Designed to run as a lightweight sidecar or standalone container in a homelab or small production environment.

## What it does

- Polls **CPU**, **RAM**, and **disk** usage against configurable warning/critical thresholds
- Performs **HTTP health checks** on a list of configured service URLs
- Checks that **required processes** are running
- Exposes a `/metrics` endpoint in Prometheus format (scraped by Prometheus every 15s)
- Exposes a `/status` endpoint returning a full JSON health summary
- Writes **structured JSON logs** for ingestion by Loki/Promtail

## Architecture

```
config.yaml ──▶ monitor.py ──▶ /metrics  (Prometheus scrapes this)
                          └──▶ /status   (JSON health summary)
                          └──▶ /health   (liveness check)
                          └──▶ logs/*.jsonl  (Promtail picks these up)
```

## Prerequisites

- Docker and Docker Compose, **or**
- Python 3.10+ with pip

## Run with Docker

```bash
cd projects/system-monitor/
docker compose up -d
```

- Metrics: `http://localhost:8000/metrics`
- Status:  `http://localhost:8000/status`

## Run without Docker

```bash
cd projects/system-monitor/
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 monitor.py
```

## Configuration

All settings are in `config.yaml`:

```yaml
service:
  port: 8000
  poll_interval_seconds: 30
  log_dir: "/app/logs"

thresholds:
  cpu_warning_percent: 75
  cpu_critical_percent: 90
  ram_warning_percent: 80
  ram_critical_percent: 95

health_checks:
  urls:
    - name: "Grafana"
      url: "http://grafana:3000/api/health"
      timeout_seconds: 5

required_processes:
  - "prometheus"
```

## Example Output

`GET /status`:
```json
{
  "timestamp": "2024-05-03T06:12:44Z",
  "overall": "warning",
  "alerts": ["WARNING: CPU at 81.2%"],
  "cpu": { "percent": 81.2, "count": 8 },
  "ram": { "percent": 62.4, "total_gb": 16.0, "available_gb": 6.0 },
  "disks": [{ "mountpoint": "/", "percent": 44.1, "free_gb": 112.3 }],
  "endpoints": [{ "name": "Grafana", "up": true, "status_code": 200, "latency_ms": 11.2 }],
  "processes": [{ "name": "prometheus", "running": true }]
}
```
