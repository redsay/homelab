#!/usr/bin/env python3
"""
backup-auditor: Parses Veeam-style backup logs, aggregates job statistics,
flags anomalies, and produces an HTML report + JSON summary.
"""

import argparse
import glob
import json
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml
from dateutil import parser as dateutil_parser
from jinja2 import Environment, FileSystemLoader, select_autoescape

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("backup-auditor")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Matches the completion / failure lines that contain all fields we care about.
# Example:
#   2024-05-01 02:14:55 [INFO] Backup job completed: job_name="ProductionDB-Full"
#     type="Full" schedule="Daily" status="Success" duration_minutes=74
#     size_gb=183.42 files_transferred=1 verify_status="Passed"
LOG_LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
    r"\s+\[(?P<level>\w+)\]"
    r".*?"
    r'job_name="(?P<job_name>[^"]+)"'
    r".*?"
    r'status="(?P<status>Success|Failed|Warning)"'
    r".*?"
    r"duration_minutes=(?P<duration_minutes>\d+)"
    r".*?"
    r"size_gb=(?P<size_gb>[\d.]+)"
    r".*?"
    r"files_transferred=(?P<files_transferred>\d+)"
)

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> dict:
    """Load YAML configuration file and return as dict."""
    config_path = Path(config_path)
    if not config_path.exists():
        log.error("Config file not found: %s", config_path)
        sys.exit(1)
    with config_path.open() as fh:
        config = yaml.safe_load(fh)
    log.info("Loaded configuration from %s", config_path)
    return config


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

def parse_log_file(log_path: Path) -> list[dict]:
    """
    Parse a single backup log file and return a list of job result records.
    Only lines containing a terminal status (Success / Failed / Warning) and
    all required numeric fields are returned.
    """
    records = []
    with log_path.open(errors="replace") as fh:
        for line in fh:
            m = LOG_LINE_RE.search(line)
            if not m:
                continue
            records.append(
                {
                    "job_name": m.group("job_name"),
                    "timestamp": dateutil_parser.parse(m.group("timestamp")),
                    "status": m.group("status"),
                    "duration_minutes": int(m.group("duration_minutes")),
                    "size_gb": float(m.group("size_gb")),
                    "files_transferred": int(m.group("files_transferred")),
                    "source_file": log_path.name,
                }
            )
    return records


def scan_log_directory(log_dir: str, log_pattern: str) -> list[dict]:
    """
    Scan log_dir for files matching log_pattern, parse each one, and
    return a flat list of all job result records sorted by timestamp.
    """
    log_dir_path = Path(log_dir)
    if not log_dir_path.is_dir():
        log.error("Log directory does not exist: %s", log_dir_path)
        sys.exit(1)

    all_records: list[dict] = []
    matched_files = sorted(log_dir_path.glob(log_pattern))
    if not matched_files:
        log.warning("No log files found in %s matching %s", log_dir_path, log_pattern)
        return all_records

    for log_file in matched_files:
        log.info("Parsing %s", log_file.name)
        records = parse_log_file(log_file)
        log.info("  -> %d job result(s) found", len(records))
        all_records.extend(records)

    all_records.sort(key=lambda r: r["timestamp"])
    log.info("Total records parsed: %d across %d file(s)", len(all_records), len(matched_files))
    return all_records


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_jobs(records: list[dict]) -> dict[str, dict]:
    """
    Aggregate raw records per job name.

    Returns a dict keyed by job_name with fields:
        last_run, total_runs, success_count, fail_count, warning_count,
        avg_size_gb, last_status, last_duration_minutes, last_size_gb,
        last_files_transferred, run_history (list of individual records)
    """
    jobs: dict[str, dict] = defaultdict(
        lambda: {
            "last_run": None,
            "total_runs": 0,
            "success_count": 0,
            "fail_count": 0,
            "warning_count": 0,
            "size_sum_gb": 0.0,
            "last_status": None,
            "last_duration_minutes": None,
            "last_size_gb": None,
            "last_files_transferred": None,
            "run_history": [],
        }
    )

    for rec in records:
        name = rec["job_name"]
        j = jobs[name]
        j["total_runs"] += 1
        status = rec["status"]
        if status == "Success":
            j["success_count"] += 1
        elif status == "Failed":
            j["fail_count"] += 1
        elif status == "Warning":
            j["warning_count"] += 1

        j["size_sum_gb"] += rec["size_gb"]

        # Keep last run info (records are sorted by timestamp, so the last
        # processed record for this job is the most recent).
        if j["last_run"] is None or rec["timestamp"] > j["last_run"]:
            j["last_run"] = rec["timestamp"]
            j["last_status"] = status
            j["last_duration_minutes"] = rec["duration_minutes"]
            j["last_size_gb"] = rec["size_gb"]
            j["last_files_transferred"] = rec["files_transferred"]

        j["run_history"].append(rec)

    # Compute derived fields
    for name, j in jobs.items():
        j["job_name"] = name
        n = j["total_runs"]
        j["avg_size_gb"] = round(j["size_sum_gb"] / n, 5) if n > 0 else 0.0
        j["failure_rate_pct"] = round(j["fail_count"] / n * 100, 1) if n > 0 else 0.0
        del j["size_sum_gb"]  # not needed downstream

    return dict(jobs)


# ---------------------------------------------------------------------------
# Flagging
# ---------------------------------------------------------------------------

def flag_jobs(jobs: dict[str, dict], thresholds: dict, now: datetime) -> list[dict]:
    """
    Evaluate each job against configured thresholds and return a list of flag dicts.

    Each flag has: job_name, severity ("warning" | "critical"), reason,
                   last_run, last_status
    """
    flags: list[dict] = []
    max_days = thresholds["max_days_since_last_run"]
    min_size_gb = thresholds["min_backup_size_gb"]
    warn_rate = thresholds["warning_failure_rate_percent"]
    crit_rate = thresholds["critical_failure_rate_percent"]

    # Jobs whose names contain these tokens are expected to be tiny; skip the
    # size check for them so PLCConfigs-Incremental doesn't false-alarm.
    small_job_tokens = thresholds.get("small_job_name_tokens", ["PLCConfigs", "PLC"])

    for name, j in jobs.items():
        last_run: datetime | None = j["last_run"]
        last_status: str = j["last_status"] or "Unknown"

        # ---- 1. Last run was Failed
        if last_status == "Failed":
            flags.append(
                {
                    "job_name": name,
                    "severity": "critical",
                    "reason": f"Last run ended with status=Failed",
                    "last_run": last_run,
                    "last_status": last_status,
                }
            )

        # ---- 2. Job hasn't run recently
        if last_run is not None:
            # Make both tz-naive for comparison
            lr_naive = last_run.replace(tzinfo=None) if last_run.tzinfo else last_run
            now_naive = now.replace(tzinfo=None) if now.tzinfo else now
            days_since = (now_naive - lr_naive).total_seconds() / 86400.0
            if days_since > max_days:
                flags.append(
                    {
                        "job_name": name,
                        "severity": "warning",
                        "reason": (
                            f"Job has not run in {days_since:.1f} day(s) "
                            f"(threshold: {max_days} day(s))"
                        ),
                        "last_run": last_run,
                        "last_status": last_status,
                    }
                )

        # ---- 3. Unusually small backup size (skip known-tiny jobs)
        is_small_job = any(token.lower() in name.lower() for token in small_job_tokens)
        last_size = j["last_size_gb"] or 0.0
        if not is_small_job and last_size > 0 and last_size < min_size_gb:
            flags.append(
                {
                    "job_name": name,
                    "severity": "warning",
                    "reason": (
                        f"Last backup size {last_size:.5f} GB is below "
                        f"minimum threshold {min_size_gb} GB"
                    ),
                    "last_run": last_run,
                    "last_status": last_status,
                }
            )

        # ---- 4. High failure rate
        rate = j["failure_rate_pct"]
        if rate >= crit_rate:
            flags.append(
                {
                    "job_name": name,
                    "severity": "critical",
                    "reason": (
                        f"Failure rate {rate:.1f}% meets or exceeds critical "
                        f"threshold ({crit_rate}%)"
                    ),
                    "last_run": last_run,
                    "last_status": last_status,
                }
            )
        elif rate >= warn_rate:
            flags.append(
                {
                    "job_name": name,
                    "severity": "warning",
                    "reason": (
                        f"Failure rate {rate:.1f}% meets or exceeds warning "
                        f"threshold ({warn_rate}%)"
                    ),
                    "last_run": last_run,
                    "last_status": last_status,
                }
            )

    return flags


# ---------------------------------------------------------------------------
# Overall status
# ---------------------------------------------------------------------------

def overall_status(jobs: dict[str, dict], flags: list[dict]) -> str:
    """Return 'OK', 'Warning', or 'Critical' based on aggregated state."""
    if any(f["severity"] == "critical" for f in flags):
        return "Critical"
    if any(f["severity"] == "warning" for f in flags):
        return "Warning"
    # Also check if any job's last status is Warning even without a flag
    if any(j["last_status"] == "Warning" for j in jobs.values()):
        return "Warning"
    return "OK"


# ---------------------------------------------------------------------------
# HTML report rendering
# ---------------------------------------------------------------------------

def render_html_report(
    jobs: dict[str, dict],
    flags: list[dict],
    report_date: str,
    template_path: Path,
) -> str:
    """Render the Jinja2 HTML template and return the rendered string."""
    template_dir = template_path.parent
    template_file = template_path.name

    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template(template_file)

    total_jobs = len(jobs)
    passed = sum(1 for j in jobs.values() if j["last_status"] == "Success")
    warned = sum(1 for j in jobs.values() if j["last_status"] == "Warning")
    failed = sum(1 for j in jobs.values() if j["last_status"] == "Failed")

    status = overall_status(jobs, flags)

    # Sort jobs: failed first, then warning, then success, alphabetically within each
    status_order = {"Failed": 0, "Warning": 1, "Success": 2}
    sorted_jobs = sorted(
        jobs.values(),
        key=lambda j: (status_order.get(j["last_status"] or "Success", 2), j["job_name"]),
    )

    # Format last_run datetimes for display
    def fmt_dt(dt: datetime | None) -> str:
        if dt is None:
            return "Never"
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    # Attach formatted last_run to each job dict copy for the template
    display_jobs = []
    for j in sorted_jobs:
        dj = dict(j)
        dj["last_run_display"] = fmt_dt(j["last_run"])
        dj["avg_size_gb_display"] = f"{j['avg_size_gb']:.3f}"
        dj["last_size_gb_display"] = f"{j.get('last_size_gb', 0):.3f}"
        display_jobs.append(dj)

    display_flags = []
    for f in flags:
        df = dict(f)
        df["last_run_display"] = fmt_dt(f["last_run"])
        display_flags.append(df)

    return template.render(
        report_date=report_date,
        overall_status=status,
        total_jobs=total_jobs,
        passed=passed,
        warned=warned,
        failed=failed,
        jobs=display_jobs,
        flags=display_flags,
    )


# ---------------------------------------------------------------------------
# JSON summary writer
# ---------------------------------------------------------------------------

def build_json_summary(
    jobs: dict[str, dict],
    flags: list[dict],
    report_date: str,
) -> dict:
    """Build a structured dict for the JSON summary."""

    def serialize_job(j: dict) -> dict:
        return {
            "job_name": j["job_name"],
            "last_run": j["last_run"].isoformat() if j["last_run"] else None,
            "last_status": j["last_status"],
            "last_duration_minutes": j["last_duration_minutes"],
            "last_size_gb": j["last_size_gb"],
            "last_files_transferred": j["last_files_transferred"],
            "total_runs": j["total_runs"],
            "success_count": j["success_count"],
            "fail_count": j["fail_count"],
            "warning_count": j["warning_count"],
            "failure_rate_pct": j["failure_rate_pct"],
            "avg_size_gb": j["avg_size_gb"],
        }

    def serialize_flag(f: dict) -> dict:
        return {
            "job_name": f["job_name"],
            "severity": f["severity"],
            "reason": f["reason"],
            "last_run": f["last_run"].isoformat() if f["last_run"] else None,
            "last_status": f["last_status"],
        }

    return {
        "report_date": report_date,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "overall_status": overall_status(jobs, flags),
        "summary": {
            "total_jobs": len(jobs),
            "passed": sum(1 for j in jobs.values() if j["last_status"] == "Success"),
            "warned": sum(1 for j in jobs.values() if j["last_status"] == "Warning"),
            "failed": sum(1 for j in jobs.values() if j["last_status"] == "Failed"),
            "total_flags": len(flags),
            "critical_flags": sum(1 for f in flags if f["severity"] == "critical"),
            "warning_flags": sum(1 for f in flags if f["severity"] == "warning"),
        },
        "jobs": [serialize_job(j) for j in jobs.values()],
        "flags": [serialize_flag(f) for f in flags],
    }


# ---------------------------------------------------------------------------
# Webhook notification
# ---------------------------------------------------------------------------

def send_webhook(summary: dict, webhook_url: str, timeout_seconds: int = 10) -> None:
    """POST a plain-text summary to the configured webhook URL."""
    status = summary["overall_status"]
    s = summary["summary"]
    flags = summary["flags"]

    lines = [
        f"[Backup Auditor] Report: {summary['report_date']}",
        f"Overall Status : {status}",
        f"Jobs           : {s['total_jobs']} total | "
        f"{s['passed']} passed | {s['warned']} warned | {s['failed']} failed",
        f"Flags          : {s['total_flags']} "
        f"({s['critical_flags']} critical, {s['warning_flags']} warning)",
    ]
    if flags:
        lines.append("")
        lines.append("Flagged Jobs:")
        for f in flags:
            lines.append(f"  [{f['severity'].upper()}] {f['job_name']}: {f['reason']}")

    text = "\n".join(lines)

    try:
        resp = requests.post(
            webhook_url,
            json={"text": text},
            timeout=timeout_seconds,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        log.info("Webhook notification sent successfully (HTTP %d)", resp.status_code)
    except requests.RequestException as exc:
        log.error("Failed to send webhook notification: %s", exc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="backup-auditor",
        description="Audit Veeam-style backup logs and produce HTML/JSON reports.",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("CONFIG_PATH", "/app/config.yaml"),
        metavar="PATH",
        help="Path to config.yaml (default: $CONFIG_PATH or /app/config.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the report to stdout instead of saving files.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)

    # Pull config sections
    job_cfg = config.get("backup_jobs", {})
    log_dir = job_cfg.get("log_directory", "/app/sample_logs")
    log_pattern = job_cfg.get("log_pattern", "*.log")

    service_cfg = config.get("service", {})
    report_dir = service_cfg.get("report_dir", "/app/reports")

    thresholds = config.get("thresholds", {})

    notifications = config.get("notifications", {})
    webhook_enabled = notifications.get("webhook_enabled", False)
    webhook_url = notifications.get("webhook_url", "")

    now = datetime.utcnow()
    report_date = now.strftime("%Y-%m-%d")

    # Locate template relative to this script
    script_dir = Path(__file__).parent
    template_path = script_dir / "report_template.html"
    if not template_path.exists():
        log.error("Report template not found: %s", template_path)
        return 1

    # ---- Parse logs
    records = scan_log_directory(log_dir, log_pattern)
    if not records:
        log.warning("No parseable backup records found. Exiting.")
        return 0

    # ---- Aggregate
    jobs = aggregate_jobs(records)
    log.info("Aggregated %d unique job(s)", len(jobs))

    # ---- Flag
    flags = flag_jobs(jobs, thresholds, now)
    log.info("Generated %d flag(s)", len(flags))
    for f in flags:
        log.warning("FLAG [%s] %s — %s", f["severity"].upper(), f["job_name"], f["reason"])

    # ---- Build outputs
    html_content = render_html_report(jobs, flags, report_date, template_path)
    json_summary = build_json_summary(jobs, flags, report_date)

    if args.dry_run:
        print("=" * 72)
        print("DRY RUN — HTML report (first 80 lines):")
        print("=" * 72)
        for line in html_content.splitlines()[:80]:
            print(line)
        print("...")
        print()
        print("=" * 72)
        print("DRY RUN — JSON summary:")
        print("=" * 72)
        print(json.dumps(json_summary, indent=2, default=str))
        return 0

    # ---- Save HTML report
    report_dir_path = Path(report_dir)
    report_dir_path.mkdir(parents=True, exist_ok=True)
    html_path = report_dir_path / f"backup-report-{report_date}.html"
    html_path.write_text(html_content, encoding="utf-8")
    log.info("HTML report saved: %s", html_path)

    # ---- Save JSON summary (JSONL — one JSON object per line)
    log_dir_path = Path(log_dir)
    jsonl_path = log_dir_path / f"auditor-{report_date}.jsonl"
    with jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(json_summary, default=str) + "\n")
    log.info("JSON summary appended: %s", jsonl_path)

    # ---- Webhook
    if webhook_enabled and webhook_url:
        log.info("Sending webhook notification to %s", webhook_url)
        send_webhook(json_summary, webhook_url)
    elif webhook_enabled and not webhook_url:
        log.warning("webhook_enabled=true but webhook_url is empty; skipping notification")

    status = overall_status(jobs, flags)
    log.info("Audit complete. Overall status: %s", status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
