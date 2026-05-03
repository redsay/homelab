#!/usr/bin/env python3
"""
service_health_check.py — HTTP health check for a list of service endpoints.

Usage:
    python3 service_health_check.py --config urls.yaml
    python3 service_health_check.py --urls http://localhost:3000 http://localhost:9090
    python3 service_health_check.py --urls http://localhost:3000 --timeout 10 --output results.json

Parameters:
    --config   Path to a YAML file containing a list of {name, url} entries
    --urls     One or more URLs to check (uses URL as name)
    --timeout  Request timeout in seconds (default: 5)
    --output   Optional path to write JSON results

Example output:
    [OK]   Grafana          http://localhost:3000        200  12ms
    [OK]   Prometheus       http://localhost:9090        200   8ms
    [DOWN] Alertmanager     http://localhost:9093        ---  ---  Connection refused
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml


def check_url(name: str, url: str, timeout: int) -> dict:
    start = time.monotonic()
    try:
        resp = requests.get(url, timeout=timeout)
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return {
            "name": name,
            "url": url,
            "up": resp.status_code < 400,
            "status_code": resp.status_code,
            "latency_ms": latency_ms,
            "error": None,
        }
    except requests.ConnectionError as e:
        return {"name": name, "url": url, "up": False, "status_code": None, "latency_ms": None, "error": "Connection refused"}
    except requests.Timeout:
        return {"name": name, "url": url, "up": False, "status_code": None, "latency_ms": None, "error": f"Timeout after {timeout}s"}
    except requests.RequestException as e:
        return {"name": name, "url": url, "up": False, "status_code": None, "latency_ms": None, "error": str(e)}


def load_targets(config_path: str | None, urls: list[str]) -> list[dict]:
    if config_path:
        with open(config_path) as f:
            data = yaml.safe_load(f)
        return data.get("services", data) if isinstance(data, dict) else data
    return [{"name": url, "url": url} for url in urls]


def main():
    parser = argparse.ArgumentParser(description="Check HTTP service health endpoints")
    parser.add_argument("--config", help="YAML config file with service list")
    parser.add_argument("--urls", nargs="+", help="URLs to check")
    parser.add_argument("--timeout", type=int, default=5, help="Request timeout in seconds")
    parser.add_argument("--output", help="Write JSON results to this file")
    args = parser.parse_args()

    if not args.config and not args.urls:
        parser.error("Provide --config or --urls")

    targets = load_targets(args.config, args.urls or [])
    results = []
    all_up = True

    for target in targets:
        result = check_url(target["name"], target["url"], args.timeout)
        results.append(result)

        status = "[OK]  " if result["up"] else "[DOWN]"
        latency = f"{result['latency_ms']}ms" if result["latency_ms"] is not None else "---"
        code = str(result["status_code"]) if result["status_code"] is not None else "---"
        error = f"  {result['error']}" if result["error"] else ""
        print(f"  {status}  {target['name']:<20} {target['url']:<40} {code:>5}  {latency:>7}{error}")

        if not result["up"]:
            all_up = False

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "up": sum(1 for r in results if r["up"]),
        "down": sum(1 for r in results if not r["up"]),
        "results": results,
    }

    if args.output:
        Path(args.output).write_text(json.dumps(summary, indent=2))
        print(f"\n  Results written to {args.output}")

    print(f"\n  {summary['up']}/{summary['total']} services up")
    sys.exit(0 if all_up else 1)


if __name__ == "__main__":
    main()
