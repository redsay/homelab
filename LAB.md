# Homelab Mini Lab

Hands-on exercises to learn each tool in this repo. No Docker needed — everything here runs with plain Python.

**Setup (one time)**
```bash
cd ~/homelab
pip3 install psutil prometheus-client pyyaml python-dateutil jinja2 requests --break-system-packages
```

---

## Exercise 1 — Log Correlator

**What it does:** Joins internal MES logs with vendor CNC controller logs to find failures that only appear when you cross-reference both sources.

```bash
cd ~/homelab/projects/log-correlator
python3 correlator.py
```

**What to look at:**
- The output names a specific machine with a 100% failure rate
- Open `sample_data/correlation_report.json` — it's the full structured finding
- Open `sample_data/internal_logs.json` and `vendor_logs.json` — these are the raw inputs

**Dig deeper:**
```bash
# See what the log simulator generates
python3 simulate_logs.py --help

# Re-generate fresh sample data, then re-run the correlator
python3 simulate_logs.py
python3 correlator.py
```

**Understand the code:**
- `correlator.py` — loads both log files, joins on `(batch_id, machine_id)`, computes failure rates
- `anomaly_detector.py` — takes the joined data and decides what's anomalous
- `config.yaml` — tune thresholds (e.g. `failure_rate_threshold`)

---

## Exercise 2 — Backup Auditor

**What it does:** Reads backup job logs, flags failures and anomalies, and generates an HTML report you can open in a browser.

```bash
cd ~/homelab/projects/backup-auditor

# Run against the 3 sample log files
CONFIG_PATH=$(pwd)/config.yaml python3 auditor.py --config config.yaml
```

That will fail on the Docker path. Use this workaround for local runs:
```bash
python3 - <<'EOF'
import sys, os
os.chdir('/home/dsayre/homelab/projects/backup-auditor')
# patch config paths before importing
import yaml
cfg = yaml.safe_load(open('config.yaml'))
cfg['backup_jobs']['log_directory'] = 'sample_logs'
cfg['service']['report_dir'] = 'reports'
import tempfile, json
tmp = tempfile.NamedTemporaryFile('w', suffix='.yaml', delete=False)
yaml.dump(cfg, tmp); tmp.flush()
sys.argv = ['auditor.py', '--config', tmp.name]
exec(open('auditor.py').read())
EOF
```

Or the simpler approach — just edit `config.yaml` to use local paths:
```bash
sed -i 's|/app/sample_logs|sample_logs|; s|/app/reports|reports|' config.yaml
mkdir -p reports
python3 auditor.py --config config.yaml
```

**What to look at:**
- Terminal output lists each flag with severity (WARNING / CRITICAL)
- Open `reports/backup-report-YYYY-MM-DD.html` in a browser — it's a formatted HTML report

**Dig deeper:**
```bash
# Add a new log file with a fake job
cp sample_logs/manufacturing-backup-2024-05-01.log sample_logs/manufacturing-backup-2024-05-04.log
# Edit the new file — change a job status to "Failed"
# Re-run and see the new flag appear
python3 auditor.py --config config.yaml
```

**Understand the code:**
- `auditor.py` — scans log files, aggregates per job, flags against thresholds, renders HTML
- `report_template.html` — Jinja2 template for the report
- `config.yaml` — tune `thresholds.critical_failure_rate_percent`, `max_days_since_last_run`, etc.

> **Restore Docker paths when done:**
> ```bash
> sed -i 's|sample_logs|/app/sample_logs|; s|^  report_dir: reports|  report_dir: /app/reports|' config.yaml
> ```

---

## Exercise 3 — Manufacturing Data Simulator

**What it does:** Simulates 5 machines on a live factory floor, generating realistic metrics (OEE, throughput, faults). Exposes a `/metrics` endpoint in Prometheus format and a `/status` JSON endpoint.

```bash
cd ~/homelab/projects/manufacturing-data-sim

# Start the simulator (runs until you Ctrl+C)
CONFIG_PATH=$(pwd)/config.yaml python3 server.py
```

Once it's running, open a second terminal and query it:

```bash
# Human-readable factory status
curl http://localhost:9200/status | python3 -m json.tool

# Status for one machine
curl http://localhost:9200/status/MILL-01 | python3 -m json.tool

# Raw Prometheus metrics
curl http://localhost:9200/metrics

# Health check
curl http://localhost:9200/health
```

**What to look at:**
- Each machine has: `state` (RUNNING/IDLE/FAULT), `oee`, `throughput_per_hour`, `fault_code`
- The `/metrics` output uses the Prometheus exposition format — these are what Grafana would scrape
- Watch `/status` over a few refreshes — machines change state on their own

**Dig deeper:**
```bash
# Filter just the OEE metrics from the Prometheus output
curl -s http://localhost:9200/metrics | grep oee

# Watch live — updates every 2 seconds
watch -n2 "curl -s http://localhost:9200/status | python3 -m json.tool | grep -E 'machine_id|state|oee|throughput'"
```

**Understand the code:**
- `sim_engine.py` — the machine state machine: IDLE → RUNNING → FAULT → IDLE cycles
- `server.py` — the HTTP server; converts sim state to Prometheus text format
- `config.yaml` — tune machine names, fault probabilities, OEE targets

---

## Exercise 4 — System Monitor

**What it does:** Collects host CPU/RAM/disk metrics via `psutil`, checks HTTP endpoints, and exposes everything as JSON at `/status` and Prometheus metrics at `/metrics`.

The config points at Docker hostnames (`prometheus`, `grafana`) that don't exist locally — make a local config first:

```bash
cd ~/homelab/projects/system-monitor

cat > config.local.yaml <<'EOF'
service:
  host: "0.0.0.0"
  port: 8000
  poll_interval_seconds: 10
  log_dir: "/tmp/system-monitor-logs"

thresholds:
  cpu_warning_percent: 75
  cpu_critical_percent: 90
  ram_warning_percent: 80
  ram_critical_percent: 95
  disk_warning_percent: 80
  disk_critical_percent: 90

health_checks:
  urls:
    - name: "Google"
      url: "https://www.google.com"
      timeout_seconds: 5

required_processes:
  - "python3"
EOF

CONFIG_PATH=$(pwd)/config.local.yaml python3 monitor.py
```

Query it from a second terminal:
```bash
# Full JSON status
curl http://localhost:8000/status | python3 -m json.tool

# Prometheus metrics
curl http://localhost:8000/metrics

# Health check
curl http://localhost:8000/health
```

**What to look at:**
- `/status` shows real CPU %, RAM %, disk % of your WSL machine right now
- `/metrics` is what Prometheus would scrape
- The `health_checks` section shows HTTP endpoint results

---

## Exercise 5 — Standalone Scripts

These run with no setup:

```bash
cd ~/homelab

# Disk usage report — prints a table of filesystem usage
python3 scripts/python/disk_usage_report.py

# Service health check — pings a list of URLs, reports up/down
python3 scripts/python/service_health_check.py

# Log parser — parses a log file and summarizes errors/warnings
python3 scripts/python/log_parser.py
```

---

## What's Next (needs Docker Desktop enabled)

Once you enable WSL integration in Docker Desktop:

```bash
# Full monitoring stack: Prometheus + Grafana + Node Exporter + Alertmanager
cd ~/homelab/docker/monitoring
docker compose up -d
# Open http://localhost:3000  (admin / admin)

# Log pipeline: Loki + Promtail + Grafana
cd ~/homelab/docker/log-pipeline
docker compose up -d

# Run manufacturing-data-sim as a container with Grafana dashboard
cd ~/homelab/projects/manufacturing-data-sim
docker compose up -d
# Open http://localhost:3000 → Manufacturing Floor dashboard
```
