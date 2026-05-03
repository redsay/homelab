variable "prometheus_port" {
  description = "Host port for Prometheus"
  type        = number
  default     = 9090
}

variable "node_exporter_port" {
  description = "Host port for Node Exporter"
  type        = number
  default     = 9100
}

variable "alertmanager_port" {
  description = "Host port for Alertmanager"
  type        = number
  default     = 9093
}

variable "grafana_port" {
  description = "Host port for Grafana"
  type        = number
  default     = 3000
}

variable "grafana_admin_user" {
  description = "Grafana admin username"
  type        = string
  default     = "admin"
}

variable "grafana_admin_password" {
  description = "Grafana admin password"
  type        = string
  default     = "admin"
  sensitive   = true
}
