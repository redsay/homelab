#!/usr/bin/env python3
"""
disk_usage_report.py — Scan directories and report top disk consumers.

Usage:
    python3 disk_usage_report.py --path /home --top 20
    python3 disk_usage_report.py --path /var/log --top 10 --output report.csv --min-size 1MB
    python3 disk_usage_report.py --path /data --depth 3

Parameters:
    --path      Root path to scan (default: current directory)
    --top       Number of largest items to report (default: 15)
    --depth     Max directory depth to scan (default: 3)
    --output    Optional CSV output file path
    --min-size  Minimum size to include (e.g. 1MB, 500KB, 1GB)

Example output:
    Disk Usage Report — /var/log
    ─────────────────────────────────────────────────────────
      Rank  Size       Path
         1  2.4 GB     /var/log/syslog
         2  847 MB     /var/log/journal
    ...
    Total scanned: 4.1 GB across 342 files
"""

import argparse
import csv
import os
import re
from datetime import datetime, timezone
from pathlib import Path


def parse_size(size_str: str) -> int:
    """Parse human-readable size string to bytes."""
    units = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    m = re.match(r"^([\d.]+)\s*([KMGT]B)?$", size_str.upper().strip())
    if not m:
        raise ValueError(f"Cannot parse size: {size_str}")
    value = float(m.group(1))
    unit = m.group(2) or "B"
    return int(value * units.get(unit, 1))


def format_size(bytes_: int) -> str:
    for unit, threshold in [("TB", 1024**4), ("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)]:
        if bytes_ >= threshold:
            return f"{bytes_ / threshold:.1f} {unit}"
    return f"{bytes_} B"


def scan_directory(root: Path, max_depth: int, min_bytes: int) -> list[dict]:
    entries = []
    root_depth = len(root.parts)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        depth = len(current.parts) - root_depth

        if depth >= max_depth:
            dirnames.clear()
            continue

        dir_size = 0
        file_count = 0
        for fname in filenames:
            fpath = current / fname
            try:
                size = fpath.stat().st_size
                dir_size += size
                file_count += 1
                if size >= min_bytes:
                    entries.append({
                        "path": str(fpath),
                        "size_bytes": size,
                        "type": "file",
                        "depth": depth + 1,
                    })
            except (PermissionError, FileNotFoundError):
                pass

        if depth > 0 and dir_size >= min_bytes:
            entries.append({
                "path": str(current),
                "size_bytes": dir_size,
                "type": "directory",
                "depth": depth,
            })

    return sorted(entries, key=lambda x: x["size_bytes"], reverse=True)


def main():
    parser = argparse.ArgumentParser(description="Scan directories and report disk usage")
    parser.add_argument("--path", default=".", help="Root path to scan")
    parser.add_argument("--top", type=int, default=15, help="Number of largest items to show")
    parser.add_argument("--depth", type=int, default=3, help="Max directory depth")
    parser.add_argument("--output", help="CSV output file")
    parser.add_argument("--min-size", default="0", help="Minimum size to include (e.g. 1MB)")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    min_bytes = parse_size(args.min_size)

    print(f"\n  Disk Usage Report — {root}")
    print(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("  " + "─" * 70)

    entries = scan_directory(root, args.depth, min_bytes)
    top = entries[:args.top]
    total_bytes = sum(e["size_bytes"] for e in entries if e["type"] == "file")
    total_files = sum(1 for e in entries if e["type"] == "file")

    print(f"  {'Rank':>5}  {'Size':>10}  {'Type':<10}  Path")
    for i, entry in enumerate(top, 1):
        print(f"  {i:>5}  {format_size(entry['size_bytes']):>10}  {entry['type']:<10}  {entry['path']}")

    print("  " + "─" * 70)
    print(f"  Total scanned: {format_size(total_bytes)} across {total_files} files\n")

    if args.output:
        with open(args.output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["rank", "path", "type", "size_bytes", "size_human"])
            writer.writeheader()
            for i, entry in enumerate(entries, 1):
                writer.writerow({
                    "rank": i,
                    "path": entry["path"],
                    "type": entry["type"],
                    "size_bytes": entry["size_bytes"],
                    "size_human": format_size(entry["size_bytes"]),
                })
        print(f"  CSV written to {args.output}")


if __name__ == "__main__":
    main()
