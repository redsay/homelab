# Dean Sayre — Home Lab & Portfolio

A fully functional home lab environment demonstrating manufacturing systems engineering skills: infrastructure as code, containerized monitoring, automation scripting, and log analysis. Everything here is built to production standards and ready to run.

```
┌────────────��────────────────────────────────────────────────────┐
│                        homelab-net (Docker)                     │
│                                                                 │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐   │
│  │  Prometheus  │   │   Grafana    │   │  Alertmanager    │   │
│  │  :9090       │──▶│  :3000       │   │  :9093           │   │
│  └──────┬───────┘   └──────────────┘   └──────────────────┘   │
│         │                  ▲                                    │
│  ┌──────▼───────┐   ┌──────┴───────┐   ┌──────────────────┐   │
│  │ Node Exporter│   │     Loki     │   │ manufacturing-   │   │
│  │  :9100       │   │  :3100       │   │ data-sim :9200   │   │
│  └──────────────┘   └──────┬───────┘   └──────────────────┘   │
│                      ┌─────▼──────┐    ┌──────────────────┐   │
│                      │  Promtail  │    │ system-monitor   │   │
│                      └────────────┘    │  :8000           │   │
│                                        └──────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

**Prerequisites:** Docker, Docker Compose, Python 3.10+

```bash
# Clone the repo
git clone <your-github-url> homelab && cd homelab

# Start the monitoring stack
cd docker/monitoring && docker compose up -d

# Start the log pipeline
cd ../log-pipeline && docker compose up -d

# Open Grafana
# http://localhost:3000  (admin / admin)
```

## Projects

| Project | Description |
|---------|-------------|
| [system-monitor](projects/system-monitor/) | Python service that monitors host health and HTTP endpoints; exposes Prometheus metrics |
| [backup-auditor](projects/backup-auditor/) | Audits backup job logs, flags failures and anomalies, generates HTML reports |
| [log-correlator](projects/log-correlator/) | Correlates logs from two manufacturing systems to surface anomalies across sources |
| [manufacturing-data-sim](projects/manufacturing-data-sim/) | Simulates a live manufacturing floor with 5 machines; Prometheus metrics + Grafana dashboard |

## Stacks

| Stack | Path | Services |
|-------|------|---------|
| Monitoring | `docker/monitoring/` | Prometheus, Grafana, Node Exporter, Alertmanager |
| Log Pipeline | `docker/log-pipeline/` | Loki, Promtail, Grafana |

## Infrastructure as Code

- **Terraform** (`terraform/`) — manages the monitoring stack containers using the Docker provider. No cloud account needed.
- **Ansible** (`ansible/`) — provisions a fresh Ubuntu 22.04 machine to a fully running homelab with one command.

```bash
# Provision with Ansible
ansible-playbook ansible/provision_local.yml -K

# Manage with Terraform
cd terraform && terraform init && terraform apply
```

## Scripts

Standalone utility scripts in `scripts/`:

| Script | Language | What it does |
|--------|----------|-------------|
| `service_health_check.py` | Python | Pings service URLs, reports status and latency |
| `disk_usage_report.py` | Python | Scans directories, reports top consumers, exports CSV |
| `log_parser.py` | Python | Parses JSON logs, outputs summary statistics |
| `backup_verify.sh` | Bash | Checks backup files exist and aren't older than N days |
| `docker_health.sh` | Bash | Checks container health, restarts unhealthy ones |
| `ServiceMonitor.ps1` | PowerShell | Checks Windows services are running, logs results |
| `AssetInventory.ps1` | PowerShell | Scans machine, exports software/hardware/services to CSV |

## Tech Stack

![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white)
![Terraform](https://img.shields.io/badge/Terraform-7B42BC?style=flat&logo=terraform&logoColor=white)
![Ansible](https://img.shields.io/badge/Ansible-EE0000?style=flat&logo=ansible&logoColor=white)
![Prometheus](https://img.shields.io/badge/Prometheus-E6522C?style=flat&logo=prometheus&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-F46800?style=flat&logo=grafana&logoColor=white)
![PowerShell](https://img.shields.io/badge/PowerShell-5391FE?style=flat&logo=powershell&logoColor=white)
![Bash](https://img.shields.io/badge/Bash-4EAA25?style=flat&logo=gnu-bash&logoColor=white)

## Port Reference

| Service | Port |
|---------|------|
| Grafana | 3000 |
| Prometheus | 9090 |
| Alertmanager | 9093 |
| Node Exporter | 9100 |
| Loki | 3100 |
| System Monitor | 8000 |
| Mfg Data Sim | 9200 |
