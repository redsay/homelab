# backup-auditor

A Python tool that audits backup job logs, flags failures and anomalies, and generates a daily HTML report. Built for environments where backup jobs run on a schedule and you need a quick daily view of what passed, what warned, and what failed.

## What it does

- Parses backup job logs from a configurable directory (`.log` files in Veeam-style format)
- Aggregates per-job statistics: run count, success/failure/warning rates, average size, last run time
- **Flags** jobs that:
  - Failed on their last run
  - Haven't run in more than N days
  - Produced unusually small backups compared to their history
  - Have a failure rate above warning or critical thresholds
- Generates a **styled HTML report** saved to the reports directory
- Writes a **structured JSON summary** to the log directory
- Optionally POSTs a plain-text summary to a Slack/Teams webhook

## Architecture

```
sample_logs/*.log ──▶ auditor.py ──▶ HTML report (reports/)
                              └──▶ JSON summary (logs/)
                              └──▶ webhook (optional)
```

## Prerequisites

- Docker and Docker Compose, **or**
- Python 3.10+ with pip

## Run with Docker

```bash
cd projects/backup-auditor/
docker compose up
```

The report will be saved to `./reports/backup-report-<date>.html`.

## Run without Docker

```bash
cd projects/backup-auditor/
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 auditor.py
```

## Configuration

All settings in `config.yaml`:

```yaml
backup_jobs:
  log_directory: "/app/sample_logs"
  log_pattern: "*.log"

thresholds:
  max_days_since_last_run: 1
  min_backup_size_gb: 0.001
  warning_failure_rate_percent: 10
  critical_failure_rate_percent: 25

notifications:
  webhook_url: ""
  webhook_enabled: false
```

## Sample Data

`sample_logs/` contains three days of realistic manufacturing environment backup logs covering:
- Production database (MES)
- Quality system database
- ERP database
- PLC configuration backups
- VM images
- File server

The sample data includes deliberate failures and warnings so the tool produces a non-trivial report out of the box.

## Example Output

```
Backup Audit Report — 2024-05-03
──────────────────────────────────────────
Jobs audited:   6
  Passed:       4
  Warning:      1
  Failed:       1

FLAGGED:
  [CRITICAL] VMware-ManufacturingHosts-Images — Last run FAILED (target unreachable)
  [WARNING]  PLCConfigs-Incremental — Backup size 0.00012 GB is unusually small
```
