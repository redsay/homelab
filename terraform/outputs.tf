output "grafana_url" {
  description = "Grafana dashboard URL"
  value       = "http://localhost:${var.grafana_port}"
}

output "prometheus_url" {
  description = "Prometheus UI URL"
  value       = "http://localhost:${var.prometheus_port}"
}

output "alertmanager_url" {
  description = "Alertmanager UI URL"
  value       = "http://localhost:${var.alertmanager_port}"
}

output "node_exporter_url" {
  description = "Node Exporter metrics URL"
  value       = "http://localhost:${var.node_exporter_port}/metrics"
}

output "network_name" {
  description = "Shared Docker network name"
  value       = docker_network.homelab_net.name
}
