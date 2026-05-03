# Terraform — Homelab Infrastructure as Code

Manages the homelab monitoring stack (Prometheus, Grafana, Node Exporter, Alertmanager) as Terraform resources using the [kreuzwerker/docker](https://registry.terraform.io/providers/kreuzwerker/docker/latest) provider. No cloud account required — everything runs locally via Docker.

## Quick Start

```bash
cd terraform/
terraform init
terraform plan
terraform apply
```

Grafana will be available at `http://localhost:3000` (admin/admin).

## What it manages

| Resource | Type |
|----------|------|
| `homelab-net` | Docker network |
| Prometheus data | Docker volume |
| Grafana data | Docker volume |
| Alertmanager data | Docker volume |
| prometheus-tf | Docker container |
| node-exporter-tf | Docker container |
| alertmanager-tf | Docker container |
| grafana-tf | Docker container |

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `prometheus_port` | 9090 | Host port for Prometheus |
| `grafana_port` | 3000 | Host port for Grafana |
| `alertmanager_port` | 9093 | Host port for Alertmanager |
| `node_exporter_port` | 9100 | Host port for Node Exporter |
| `grafana_admin_password` | admin | Grafana admin password |

Override variables:
```bash
terraform apply -var="grafana_port=3001" -var="grafana_admin_password=mysecret"
```

## State

State is stored locally in `terraform.tfstate`. Both `terraform.tfstate*` and `.terraform/` are gitignored.

## Tear down

```bash
terraform destroy
```
