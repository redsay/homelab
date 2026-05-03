#!/usr/bin/env python3
"""
log_parser.py — Parse structured JSON log files and output summary statistics.

Usage:
    python3 log_parser.py --path /app/logs/
    python3 log_parser.py --path /app/logs/app.jsonl --field level --output summary.json
    python3 log_parser.py --path /var/log/ --pattern "*.jsonl" --since 24h

Parameters:
    --path      File or directory to parse
    --pattern   Glob pattern when --path is a directory (default: *.jsonl)
    --field     Field to group by for breakdown (default: level)
    --since     Only include logs from the last N hours/days (e.g. 24h, 7d)
    --output    Optional JSON output file
    --errors    Show only error-level entries

Example output:
    Log Summary — /app/logs/
    ─────────────────────────────────
    Total entries:    1,482
    Time range:       2024-05-01 00:00 → 2024-05-03 23:59
    Breakdown by level:
      INFO      1,201   (81.0%)
      WARNING     204   (13.8%)
      ERROR        77    (5.2%)
    Top services:
      system-monitor    891
      backup-auditor    591
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def parse_since(since_str: str) -> datetime | None:
    if not since_str:
        return None
    m = re.match(r"^(\d+)([hd])$", since_str.lower())
    if not m:
        raise ValueError(f"Cannot parse --since value: {since_str} (use e.g. 24h or 7d)")
    value = int(m.group(1))
    delta = timedelta(hours=value) if m.group(2) == "h" else timedelta(days=value)
    return datetime.now(timezone.utc) - delta


def parse_timestamp(ts: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(ts, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def collect_files(path: Path, pattern: str) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob(pattern))


def parse_logs(files: list[Path], group_field: str, since: datetime | None, errors_only: bool) -> dict:
    entries = []
    parse_errors = 0

    for fpath in files:
        try:
            for line in fpath.read_text(errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    entries.append(record)
                except json.JSONDecodeError:
                    parse_errors += 1
        except (PermissionError, OSError):
            pass

    # Filter by time
    if since:
        filtered = []
        for e in entries:
            ts_raw = e.get("timestamp") or e.get("time") or e.get("ts")
            if ts_raw:
                ts = parse_timestamp(str(ts_raw))
                if ts and ts >= since:
                    filtered.append(e)
            else:
                filtered.append(e)
        entries = filtered

    # Filter by error level
    if errors_only:
        entries = [e for e in entries if str(e.get("level", "")).upper() in ("ERROR", "CRITICAL", "FATAL")]

    # Group by requested field
    breakdown: Counter = Counter()
    service_counts: Counter = Counter()
    timestamps = []

    for e in entries:
        val = e.get(group_field, "unknown")
        breakdown[str(val)] += 1

        svc = e.get("service") or e.get("logger") or e.get("app")
        if svc:
            service_counts[str(svc)] += 1

        ts_raw = e.get("timestamp") or e.get("time") or e.get("ts")
        if ts_raw:
            ts = parse_timestamp(str(ts_raw))
            if ts:
                timestamps.append(ts)

    total = len(entries)
    time_range = None
    if timestamps:
        time_range = {
            "earliest": min(timestamps).strftime("%Y-%m-%d %H:%M UTC"),
            "latest": max(timestamps).strftime("%Y-%m-%d %H:%M UTC"),
        }

    return {
        "total_entries": total,
        "parse_errors": parse_errors,
        "files_scanned": len(files),
        "time_range": time_range,
        "breakdown": dict(breakdown.most_common()),
        "top_services": dict(service_counts.most_common(10)),
    }


def main():
    parser = argparse.ArgumentParser(description="Parse and summarize structured JSON logs")
    parser.add_argument("--path", required=True, help="File or directory to parse")
    parser.add_argument("--pattern", default="*.jsonl", help="Glob pattern for directory scan")
    parser.add_argument("--field", default="level", help="Field to group by")
    parser.add_argument("--since", help="Only include logs from last N hours/days (e.g. 24h, 7d)")
    parser.add_argument("--output", help="Write JSON summary to this file")
    parser.add_argument("--errors", action="store_true", help="Show only error-level entries")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"  ERROR: Path not found: {path}", file=sys.stderr)
        sys.exit(1)

    since = parse_since(args.since) if args.since else None
    files = collect_files(path, args.pattern)
    if not files:
        print(f"  No files found matching {args.pattern} in {path}")
        sys.exit(0)

    summary = parse_logs(files, args.field, since, args.errors)

    total = summary["total_entries"]
    print(f"\n  Log Summary — {path}")
    print("  " + "─" * 50)
    print(f"  Files scanned:   {summary['files_scanned']}")
    print(f"  Total entries:   {total:,}")
    if summary["parse_errors"]:
        print(f"  Parse errors:    {summary['parse_errors']:,}")
    if summary["time_range"]:
        print(f"  Time range:      {summary['time_range']['earliest']} → {summary['time_range']['latest']}")

    print(f"\n  Breakdown by {args.field}:")
    for val, count in summary["breakdown"].items():
        pct = (count / total * 100) if total else 0
        print(f"    {val:<20} {count:>6,}   ({pct:.1f}%)")

    if summary["top_services"]:
        print(f"\n  Top services:")
        for svc, count in summary["top_services"].items():
            print(f"    {svc:<30} {count:>6,}")

    print()

    if args.output:
        Path(args.output).write_text(json.dumps(summary, indent=2))
        print(f"  Summary written to {args.output}")


if __name__ == "__main__":
    main()
