terraform {
  required_version = ">= 1.5"

  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

provider "docker" {}

# ── Network ───────────────────────────────────────────────────────────────────

resource "docker_network" "homelab_net" {
  name   = "homelab-net"
  driver = "bridge"
}

# ── Volumes ───────────────────────────────────────────────────────────────────

resource "docker_volume" "prometheus_data" {
  name = "homelab_prometheus_data"
}

resource "docker_volume" "grafana_data" {
  name = "homelab_grafana_data"
}

resource "docker_volume" "alertmanager_data" {
  name = "homelab_alertmanager_data"
}

# ── Images ────────────────────────────────────────────────────────────────────

resource "docker_image" "prometheus" {
  name         = "prom/prometheus:v2.51.2"
  keep_locally = true
}

resource "docker_image" "node_exporter" {
  name         = "prom/node-exporter:v1.8.0"
  keep_locally = true
}

resource "docker_image" "alertmanager" {
  name         = "prom/alertmanager:v0.27.0"
  keep_locally = true
}

resource "docker_image" "grafana" {
  name         = "grafana/grafana:10.4.2"
  keep_locally = true
}

# ── Containers ────────────────────────────────────────────────────────────────

resource "docker_container" "prometheus" {
  name    = "prometheus-tf"
  image   = docker_image.prometheus.image_id
  restart = "unless-stopped"

  command = [
    "--config.file=/etc/prometheus/prometheus.yml",
    "--storage.tsdb.path=/prometheus",
    "--storage.tsdb.retention.time=30d",
    "--web.enable-lifecycle",
  ]

  ports {
    internal = 9090
    external = var.prometheus_port
  }

  volumes {
    host_path      = abspath("${path.module}/../docker/monitoring/prometheus/prometheus.yml")
    container_path = "/etc/prometheus/prometheus.yml"
    read_only      = true
  }

  volumes {
    host_path      = abspath("${path.module}/../docker/monitoring/prometheus/alert_rules.yml")
    container_path = "/etc/prometheus/alert_rules.yml"
    read_only      = true
  }

  volumes {
    volume_name    = docker_volume.prometheus_data.name
    container_path = "/prometheus"
  }

  networks_advanced {
    name = docker_network.homelab_net.name
  }
}

resource "docker_container" "node_exporter" {
  name    = "node-exporter-tf"
  image   = docker_image.node_exporter.image_id
  restart = "unless-stopped"
  pid_mode = "host"

  command = [
    "--path.procfs=/host/proc",
    "--path.sysfs=/host/sys",
    "--path.rootfs=/rootfs",
    "--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)",
  ]

  ports {
    internal = 9100
    external = var.node_exporter_port
  }

  volumes {
    host_path      = "/proc"
    container_path = "/host/proc"
    read_only      = true
  }

  volumes {
    host_path      = "/sys"
    container_path = "/host/sys"
    read_only      = true
  }

  volumes {
    host_path      = "/"
    container_path = "/rootfs"
    read_only      = true
  }

  networks_advanced {
    name = docker_network.homelab_net.name
  }
}

resource "docker_container" "alertmanager" {
  name    = "alertmanager-tf"
  image   = docker_image.alertmanager.image_id
  restart = "unless-stopped"

  command = [
    "--config.file=/etc/alertmanager/alertmanager.yml",
    "--storage.path=/alertmanager",
  ]

  ports {
    internal = 9093
    external = var.alertmanager_port
  }

  volumes {
    host_path      = abspath("${path.module}/../docker/monitoring/alertmanager/alertmanager.yml")
    container_path = "/etc/alertmanager/alertmanager.yml"
    read_only      = true
  }

  volumes {
    volume_name    = docker_volume.alertmanager_data.name
    container_path = "/alertmanager"
  }

  networks_advanced {
    name = docker_network.homelab_net.name
  }
}

resource "docker_container" "grafana" {
  name    = "grafana-tf"
  image   = docker_image.grafana.image_id
  restart = "unless-stopped"

  env = [
    "GF_SECURITY_ADMIN_USER=${var.grafana_admin_user}",
    "GF_SECURITY_ADMIN_PASSWORD=${var.grafana_admin_password}",
    "GF_USERS_ALLOW_SIGN_UP=false",
  ]

  ports {
    internal = 3000
    external = var.grafana_port
  }

  volumes {
    volume_name    = docker_volume.grafana_data.name
    container_path = "/var/lib/grafana"
  }

  volumes {
    host_path      = abspath("${path.module}/../docker/monitoring/grafana/provisioning/datasources")
    container_path = "/etc/grafana/provisioning/datasources"
    read_only      = true
  }

  volumes {
    host_path      = abspath("${path.module}/../docker/monitoring/grafana/provisioning/dashboards")
    container_path = "/etc/grafana/provisioning/dashboards"
    read_only      = true
  }

  volumes {
    host_path      = abspath("${path.module}/../docker/monitoring/grafana/dashboards")
    container_path = "/var/lib/grafana/dashboards"
    read_only      = true
  }

  networks_advanced {
    name = docker_network.homelab_net.name
  }

  depends_on = [docker_container.prometheus]
}
