"""
server.py — HTTP server for the manufacturing data simulator.

Endpoints:
  GET /metrics          — Prometheus text format
  GET /status           — Full facility JSON state
  GET /status/<machine> — Single machine JSON
  GET /health           — Plain text "ok"

The simulation engine runs on a background thread, ticking every
`tick_interval_seconds` as defined in config.yaml.
"""

import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import yaml

from sim_engine import ManufacturingSimulator

# ──────────────────────────────────────────────────────────────────────────────
# Logging setup
# ──────────────────────────────────────────────────────────────────────────────

def configure_logging(log_dir: str) -> None:
    """Configure root logger to write to stdout and to a rotating file."""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    try:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(os.path.join(log_dir, "manufacturing-sim.log"))
        handlers.append(fh)
    except OSError as exc:
        # Non-fatal — if we can't create the log directory just use stdout
        print(f"WARNING: Could not create log directory {log_dir!r}: {exc}", flush=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        handlers=handlers,
    )

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Config loader
# ──────────────────────────────────────────────────────────────────────────────

def load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path) as fh:
        cfg = yaml.safe_load(fh)
    logger.info("Loaded config from %s", path)
    return cfg


# ──────────────────────────────────────────────────────────────────────────────
# Simulation background thread
# ──────────────────────────────────────────────────────────────────────────────

class SimulatorThread(threading.Thread):
    """Calls simulator.tick() every `interval` seconds in the background."""

    def __init__(self, simulator: ManufacturingSimulator, interval: float) -> None:
        super().__init__(daemon=True, name="sim-engine")
        self.simulator = simulator
        self.interval = interval
        self._stop_event = threading.Event()

    def run(self) -> None:
        logger.info("Simulation thread started — tick interval %.1fs", self.interval)
        while not self._stop_event.is_set():
            try:
                self.simulator.tick()
            except Exception:
                logger.exception("Unhandled error in simulation tick")
            self._stop_event.wait(timeout=self.interval)

    def stop(self) -> None:
        self._stop_event.set()


# ──────────────────────────────────────────────────────────────────────────────
# HTTP request handler
# ──────────────────────────────────────────────────────────────────────────────

# Module-level reference injected before the server starts
_simulator: ManufacturingSimulator | None = None


class ManufacturingHandler(BaseHTTPRequestHandler):
    """HTTP handler for all simulator endpoints."""

    # Suppress default "127.0.0.1 - - [date] ..." access log spam; use our own.
    def log_message(self, fmt: str, *args: Any) -> None:  # type: ignore[override]
        logger.debug("HTTP %s %s %s", self.command, self.path, args[-1] if args else "")

    def do_GET(self) -> None:  # noqa: N802
        # Strip query string for routing
        path = self.path.split("?")[0].rstrip("/")

        if path == "/health":
            self._respond_text(200, "ok\n")

        elif path == "/metrics":
            assert _simulator is not None
            body = _simulator.get_prometheus_metrics()
            self._respond(200, "text/plain; version=0.0.4; charset=utf-8", body.encode())

        elif path == "/status":
            assert _simulator is not None
            state = _simulator.get_state()
            self._respond_json(200, state)

        elif path.startswith("/status/"):
            machine_id = path[len("/status/"):]
            assert _simulator is not None
            state = _simulator.get_state()
            machine_data = state["machines"].get(machine_id.upper())
            if machine_data is None:
                self._respond_json(
                    404,
                    {"error": f"Machine '{machine_id}' not found",
                     "available": list(state["machines"].keys())},
                )
            else:
                self._respond_json(200, machine_data)

        else:
            self._respond_json(
                404,
                {"error": "Not found",
                 "endpoints": ["/health", "/metrics", "/status", "/status/<machine_id>"]},
            )

    # ── response helpers ──────────────────────────────────────────────────────

    def _respond(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _respond_text(self, code: int, text: str) -> None:
        self._respond(code, "text/plain; charset=utf-8", text.encode())

    def _respond_json(self, code: int, data: Any) -> None:
        body = json.dumps(data, indent=2).encode()
        self._respond(code, "application/json", body)


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    global _simulator

    # Allow overriding config path via env var for container flexibility
    config_path = os.environ.get("CONFIG_PATH", "config.yaml")
    config = load_config(config_path)

    svc = config.get("service", {})
    host = svc.get("host", "0.0.0.0")
    port = int(svc.get("port", 9200))
    tick_interval = float(svc.get("tick_interval_seconds", 5))
    log_dir = svc.get("log_dir", "/app/logs")

    configure_logging(log_dir)

    logger.info("Starting Manufacturing Data Simulator")

    _simulator = ManufacturingSimulator(config)

    sim_thread = SimulatorThread(_simulator, tick_interval)
    sim_thread.start()

    server = HTTPServer((host, port), ManufacturingHandler)
    logger.info("HTTP server listening on %s:%d", host, port)
    logger.info("Endpoints: /health  /metrics  /status  /status/<machine_id>")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        sim_thread.stop()
        server.server_close()
        logger.info("Server stopped")


if __name__ == "__main__":
    main()
