#!/usr/bin/env python3
"""
System health monitor service.
Polls CPU, RAM, disk, HTTP endpoints, and required processes.
Exposes /metrics (Prometheus format) and /status (JSON) on a configurable port.
"""

import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import psutil
import requests
import yaml
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    generate_latest,
    start_http_server,
)

# ── Prometheus metrics ──────────────────────────────────────────────────────

cpu_usage = Gauge("system_cpu_usage_percent", "Current CPU usage percentage")
ram_usage = Gauge("system_ram_usage_percent", "Current RAM usage percentage")
ram_available_bytes = Gauge("system_ram_available_bytes", "Available RAM in bytes")
disk_usage = Gauge("system_disk_usage_percent", "Disk usage percentage", ["mountpoint"])
disk_free_bytes = Gauge("system_disk_free_bytes", "Free disk space in bytes", ["mountpoint"])
endpoint_up = Gauge("endpoint_up", "HTTP endpoint reachability (1=up, 0=down)", ["name", "url"])
endpoint_latency = Gauge("endpoint_latency_seconds", "HTTP endpoint response latency", ["name", "url"])
process_running = Gauge("process_running", "Whether a required process is running (1=yes, 0=no)", ["name"])
poll_errors = Counter("monitor_poll_errors_total", "Total number of polling errors")
polls_total = Counter("monitor_polls_total", "Total number of completed polls")

# ── Shared state ─────────────────────────────────────────────────────────────

_status: dict = {}
_status_lock = threading.Lock()


# ── Logging ──────────────────────────────────────────────────────────────────

def setup_logging(log_dir: str) -> logging.Logger:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_dir) / f"system-monitor-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"

    logger = logging.getLogger("system-monitor")
    logger.setLevel(logging.INFO)

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            return json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "service": "system-monitor",
                "message": record.getMessage(),
            })

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(JsonFormatter())

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


# ── Polling logic ────────────────────────────────────────────────────────────

def check_cpu() -> dict:
    percent = psutil.cpu_percent(interval=1)
    cpu_usage.set(percent)
    return {"percent": percent, "count": psutil.cpu_count()}


def check_ram() -> dict:
    mem = psutil.virtual_memory()
    ram_usage.set(mem.percent)
    ram_available_bytes.set(mem.available)
    return {
        "percent": mem.percent,
        "total_gb": round(mem.total / (1024 ** 3), 2),
        "available_gb": round(mem.available / (1024 ** 3), 2),
        "used_gb": round(mem.used / (1024 ** 3), 2),
    }


def check_disk() -> list[dict]:
    results = []
    for partition in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disk_usage.labels(mountpoint=partition.mountpoint).set(usage.percent)
            disk_free_bytes.labels(mountpoint=partition.mountpoint).set(usage.free)
            results.append({
                "mountpoint": partition.mountpoint,
                "device": partition.device,
                "percent": usage.percent,
                "total_gb": round(usage.total / (1024 ** 3), 2),
                "free_gb": round(usage.free / (1024 ** 3), 2),
            })
        except PermissionError:
            pass
    return results


def check_endpoint(name: str, url: str, timeout: int) -> dict:
    start = time.monotonic()
    try:
        resp = requests.get(url, timeout=timeout)
        latency = time.monotonic() - start
        up = resp.status_code < 400
        endpoint_up.labels(name=name, url=url).set(1 if up else 0)
        endpoint_latency.labels(name=name, url=url).set(latency)
        return {"name": name, "url": url, "up": up, "status_code": resp.status_code, "latency_ms": round(latency * 1000, 1)}
    except requests.RequestException as exc:
        latency = time.monotonic() - start
        endpoint_up.labels(name=name, url=url).set(0)
        endpoint_latency.labels(name=name, url=url).set(latency)
        return {"name": name, "url": url, "up": False, "error": str(exc), "latency_ms": round(latency * 1000, 1)}


def check_processes(names: list[str]) -> list[dict]:
    running = {p.name().lower() for p in psutil.process_iter(["name"])}
    results = []
    for name in names:
        is_running = name.lower() in running
        process_running.labels(name=name).set(1 if is_running else 0)
        results.append({"name": name, "running": is_running})
    return results


def run_poll(config: dict, logger: logging.Logger) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    thresholds = config.get("thresholds", {})

    cpu = check_cpu()
    ram = check_ram()
    disks = check_disk()

    endpoints = [
        check_endpoint(ep["name"], ep["url"], ep.get("timeout_seconds", 5))
        for ep in config.get("health_checks", {}).get("urls", [])
    ]

    processes = check_processes(config.get("required_processes", []))

    # Determine overall health
    alerts = []
    if cpu["percent"] >= thresholds.get("cpu_critical_percent", 90):
        alerts.append(f"CRITICAL: CPU at {cpu['percent']}%")
    elif cpu["percent"] >= thresholds.get("cpu_warning_percent", 75):
        alerts.append(f"WARNING: CPU at {cpu['percent']}%")

    if ram["percent"] >= thresholds.get("ram_critical_percent", 95):
        alerts.append(f"CRITICAL: RAM at {ram['percent']}%")
    elif ram["percent"] >= thresholds.get("ram_warning_percent", 80):
        alerts.append(f"WARNING: RAM at {ram['percent']}%")

    for disk in disks:
        if disk["percent"] >= thresholds.get("disk_critical_percent", 90):
            alerts.append(f"CRITICAL: Disk {disk['mountpoint']} at {disk['percent']}%")
        elif disk["percent"] >= thresholds.get("disk_warning_percent", 80):
            alerts.append(f"WARNING: Disk {disk['mountpoint']} at {disk['percent']}%")

    for ep in endpoints:
        if not ep["up"]:
            alerts.append(f"DOWN: {ep['name']} at {ep['url']}")

    for proc in processes:
        if not proc["running"]:
            alerts.append(f"MISSING: process {proc['name']} not found")

    overall = "healthy"
    if any(a.startswith("CRITICAL") or a.startswith("DOWN") or a.startswith("MISSING") for a in alerts):
        overall = "critical"
    elif any(a.startswith("WARNING") for a in alerts):
        overall = "warning"

    status = {
        "timestamp": now,
        "overall": overall,
        "alerts": alerts,
        "cpu": cpu,
        "ram": ram,
        "disks": disks,
        "endpoints": endpoints,
        "processes": processes,
    }

    polls_total.inc()
    if alerts:
        logger.info(f"Poll complete: {overall} — {len(alerts)} alert(s): {alerts}")
    else:
        logger.info(f"Poll complete: {overall}")

    return status


# ── HTTP server ───────────────────────────────────────────────────────────────

class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress default HTTP logs; structured logs handle this

    def do_GET(self):
        if self.path == "/status":
            with _status_lock:
                body = json.dumps(_status, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/metrics":
            body = generate_latest()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

        else:
            self.send_response(404)
            self.end_headers()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    config_path = os.environ.get("CONFIG_PATH", "/app/config.yaml")
    with open(config_path) as f:
        config = yaml.safe_load(f)

    service_cfg = config.get("service", {})
    log_dir = service_cfg.get("log_dir", "/app/logs")
    host = service_cfg.get("host", "0.0.0.0")
    port = service_cfg.get("port", 8000)
    interval = service_cfg.get("poll_interval_seconds", 30)

    logger = setup_logging(log_dir)
    logger.info(f"Starting system-monitor on {host}:{port}, poll interval {interval}s")

    # Initial poll before serving
    with _status_lock:
        global _status
        _status = run_poll(config, logger)

    # Background polling thread
    def poll_loop():
        while True:
            time.sleep(interval)
            try:
                result = run_poll(config, logger)
                with _status_lock:
                    global _status
                    _status = result
            except Exception as exc:
                poll_errors.inc()
                logger.error(f"Poll error: {exc}")

    thread = threading.Thread(target=poll_loop, daemon=True)
    thread.start()

    server = HTTPServer((host, port), RequestHandler)

    def shutdown(sig, frame):
        logger.info("Shutting down")
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    logger.info(f"Serving on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
