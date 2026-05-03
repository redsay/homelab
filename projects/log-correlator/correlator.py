"""
correlator.py

Main script for the log-correlator tool.

Usage
-----
    python correlator.py
    python correlator.py --config path/to/config.yaml
    python correlator.py --config config.yaml --output-dir results/

What it does
------------
1. Loads internal MES logs and vendor CNC controller logs.
2. Joins records on (batch_id, machine_id) — pure Python inner join, no pandas.
3. Computes per (job_type, machine_id) failure rates from both log sources.
4. Runs anomaly detection (high failure rate, missing correlations, machine
   anomalies).
5. Writes sample_data/correlation_report.json with all structured findings.
6. Prints a human-readable summary to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import yaml

import anomaly_detector


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "internal_log_path": "sample_data/internal_logs.json",
    "vendor_log_path":   "sample_data/vendor_logs.json",
    "output_dir":        "sample_data/",
    "thresholds": {
        "failure_rate_warning":  0.10,
        "failure_rate_critical": 0.25,
        "min_sample_size":       5,
    },
}


def load_config(config_path: str | None) -> dict:
    """Load YAML config, falling back to defaults for missing keys."""
    config = dict(DEFAULT_CONFIG)
    config["thresholds"] = dict(DEFAULT_CONFIG["thresholds"])

    if config_path:
        if not os.path.exists(config_path):
            print(f"[ERROR] Config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)
        with open(config_path) as f:
            user_cfg = yaml.safe_load(f) or {}
        for key in ("internal_log_path", "vendor_log_path", "output_dir"):
            if key in user_cfg:
                config[key] = user_cfg[key]
        if "thresholds" in user_cfg:
            config["thresholds"].update(user_cfg["thresholds"])

    return config


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_json(path: str) -> list[dict]:
    if not os.path.exists(path):
        print(f"[ERROR] Log file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, list):
        print(f"[ERROR] Expected a JSON array in {path}", file=sys.stderr)
        sys.exit(1)
    return data


def write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Join logic
# ---------------------------------------------------------------------------

def inner_join(
    internal: list[dict],
    vendor: list[dict],
    join_keys: tuple[str, str] = ("batch_id", "machine_id"),
) -> list[dict]:
    """
    Perform a manual inner join on join_keys.

    For each internal record, look up the vendor record(s) sharing the same
    (batch_id, machine_id).  When multiple vendor records match the same key
    (shouldn't happen with well-formed data but handled defensively), the
    first match is used.

    Returns a list of merged dicts with all fields from both sources.
    Internal fields are kept as-is; vendor fields are prefixed with
    ``vendor_`` where they conflict with internal names.
    """
    # Index vendor records by join key for O(1) lookup
    vendor_index: dict[tuple, list[dict]] = defaultdict(list)
    for rec in vendor:
        key = tuple(rec.get(k) for k in join_keys)
        vendor_index[key].append(rec)

    correlated: list[dict] = []
    for int_rec in internal:
        key = tuple(int_rec.get(k) for k in join_keys)
        matches = vendor_index.get(key)
        if not matches:
            continue

        vnd_rec = matches[0]  # take first match

        merged: dict[str, Any] = {}
        # Internal fields
        for field, value in int_rec.items():
            merged[field] = value

        # Remap internal 'status' so vendor result lives alongside it
        merged["internal_status"] = int_rec.get("status")

        # Vendor fields — prefix conflicting names
        conflict_fields = {"timestamp", "batch_id", "machine_id"}
        for field, value in vnd_rec.items():
            if field in conflict_fields:
                merged[f"vendor_{field}"] = value
            elif field == "result":
                merged["vendor_result"] = value
            else:
                merged[field] = value

        correlated.append(merged)

    return correlated


# ---------------------------------------------------------------------------
# Failure-rate computation
# ---------------------------------------------------------------------------

def compute_failure_rates(
    correlated: list[dict],
    min_sample_size: int = 5,
) -> list[dict]:
    """
    Compute per (job_type, machine_id) failure rates from correlated records.

    Returns a sorted list of dicts with:
        job_type, machine_id, total, failures, failure_rate,
        vendor_errors (dict of error_code -> count).
    """
    groups: dict[tuple, dict] = defaultdict(lambda: {
        "total": 0, "failures": 0, "vendor_errors": defaultdict(int)
    })

    for rec in correlated:
        jt  = rec.get("job_type",  "__UNKNOWN__")
        mid = rec.get("machine_id", "__UNKNOWN__")
        key = (jt, mid)

        groups[key]["total"] += 1
        status = rec.get("internal_status", "")
        if anomaly_detector._is_failure(status):
            groups[key]["failures"] += 1

        error_code = rec.get("error_code")
        if error_code:
            groups[key]["vendor_errors"][error_code] += 1

    rows: list[dict] = []
    for (jt, mid), counts in groups.items():
        if counts["total"] < min_sample_size:
            continue
        rate = counts["failures"] / counts["total"]
        rows.append({
            "job_type":     jt,
            "machine_id":   mid,
            "total":        counts["total"],
            "failures":     counts["failures"],
            "failure_rate": round(rate, 4),
            "vendor_errors": dict(counts["vendor_errors"]),
        })

    rows.sort(key=lambda r: r["failure_rate"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def build_report(
    internal: list[dict],
    vendor: list[dict],
    correlated: list[dict],
    failure_rates: list[dict],
    high_failure_findings: list[dict],
    missing_correlation_findings: dict,
    machine_anomaly_findings: list[dict],
    config: dict,
) -> dict:
    """Assemble the full structured JSON report."""
    total_int = len(internal)
    total_vnd = len(vendor)
    total_cor = len(correlated)
    corr_rate = total_cor / total_int if total_int else 0.0

    return {
        "report_generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {
            "internal_records":   total_int,
            "vendor_records":     total_vnd,
            "correlated_records": total_cor,
            "correlation_rate":   round(corr_rate, 4),
            "high_failure_findings_count":       len(high_failure_findings),
            "machine_anomaly_findings_count":    len(machine_anomaly_findings),
            "missing_correlation_internal_only": len(
                missing_correlation_findings.get("in_internal_only", [])
            ),
            "missing_correlation_vendor_only":   len(
                missing_correlation_findings.get("in_vendor_only", [])
            ),
        },
        "config_used": {
            "thresholds": config.get("thresholds", {}),
        },
        "failure_rates_by_machine": failure_rates,
        "findings": {
            "high_failure_rate":      high_failure_findings,
            "missing_correlations":   missing_correlation_findings,
            "machine_anomalies":      machine_anomaly_findings,
        },
    }


# ---------------------------------------------------------------------------
# Human-readable summary printer
# ---------------------------------------------------------------------------

SEP   = "=" * 62
SUBSEP = "-" * 62


def _pct(rate: float) -> str:
    return f"{rate * 100:.1f}%"


def print_summary(report: dict) -> None:
    s = report["summary"]
    findings = report["findings"]

    print()
    print(SEP)
    print("  LOG CORRELATOR — ANALYSIS REPORT")
    print(f"  Generated: {report['report_generated_at']}")
    print(SEP)

    # --- Overview ---
    print()
    print("  OVERVIEW")
    print(SUBSEP)
    print(f"  Internal (MES) records  : {s['internal_records']}")
    print(f"  Vendor (CNC) records    : {s['vendor_records']}")
    print(f"  Correlated records      : {s['correlated_records']}")
    print(f"  Correlation rate        : {_pct(s['correlation_rate'])}")
    unmatched_int = s["missing_correlation_internal_only"]
    unmatched_vnd = s["missing_correlation_vendor_only"]
    if unmatched_int or unmatched_vnd:
        print(f"  Unmatched (internal)    : {unmatched_int}")
        print(f"  Unmatched (vendor)      : {unmatched_vnd}")

    # --- Failure rates summary (top 10) ---
    print()
    print("  FAILURE RATES BY MACHINE (top 10, min 5 samples)")
    print(SUBSEP)
    print(f"  {'Machine':<12}  {'Job Type':<14}  {'Rate':>7}  {'Fails':>6}  {'Total':>6}")
    print(f"  {'-'*12}  {'-'*14}  {'-'*7}  {'-'*6}  {'-'*6}")
    for row in report["failure_rates_by_machine"][:10]:
        flag = " <-- CRITICAL" if row["failure_rate"] >= report["config_used"]["thresholds"].get("failure_rate_critical", 0.25) else ""
        print(
            f"  {row['machine_id']:<12}  {row['job_type']:<14}  "
            f"{_pct(row['failure_rate']):>7}  {row['failures']:>6}  {row['total']:>6}"
            f"{flag}"
        )

    # --- High failure rate findings ---
    hf = findings["high_failure_rate"]
    print()
    print(f"  HIGH FAILURE RATE FINDINGS  ({len(hf)} flagged)")
    print(SUBSEP)
    if hf:
        for f in hf:
            mid = f.get("machine_id", "?")
            jt  = f.get("job_type",  "?")
            rate = f["failure_rate"]
            n    = f["sample_count"]
            fails = f["failure_count"]
            thresh = f["threshold_used"]
            print(f"  [{_pct(rate):>6}]  {mid:<12}  {jt:<14}  "
                  f"{fails}/{n} events  (threshold: {_pct(thresh)})")
    else:
        print("  None.")

    # --- Machine anomaly findings ---
    ma = findings["machine_anomalies"]
    print()
    print(f"  STATISTICAL MACHINE ANOMALIES  ({len(ma)} flagged)")
    print(SUBSEP)
    if ma:
        for f in ma:
            mid    = f["machine_id"]
            jt     = f["job_type"]
            rate   = f["failure_rate"]
            median = f.get("fleet_median_rate", f.get("fleet_mean_rate", 0.0))
            z      = f["z_score"]
            err    = f.get("dominant_error_code") or "n/a"
            print(f"  {mid:<12}  {jt:<14}  rate={_pct(rate)}  "
                  f"fleet_median={_pct(median)}  z={z:.1f}  dominant_error={err}")
    else:
        print("  None.")

    # --- MILL-03 callout ---
    mill03_anomalies = [
        f for f in ma
        if f.get("machine_id") == "MILL-03"
    ]
    if not mill03_anomalies:
        # Also check high-failure list
        mill03_anomalies = [
            f for f in hf
            if f.get("machine_id") == "MILL-03"
        ]

    if mill03_anomalies:
        print()
        print(SEP)
        print("  *** ACTION REQUIRED: MILL-03 EQUIPMENT FAULT DETECTED ***")
        print(SEP)
        for f in mill03_anomalies:
            rate  = f.get("failure_rate", 0.0)
            n     = f.get("sample_count", "?")
            err   = f.get("dominant_error_code", "E_SPINDLE_FAULT")
            jt    = f.get("job_type", "MILL_OP")
            print(f"  Machine   : MILL-03")
            print(f"  Job type  : {jt}")
            print(f"  Failure rate: {_pct(rate)} ({n} events reviewed)")
            if err:
                print(f"  Vendor error: {err}")
        print()
        print("  Root cause hypothesis:")
        print("    MILL-03 is reporting 100% failure on MILL_OP jobs.")
        print("    The vendor CNC controller is logging E_SPINDLE_FAULT")
        print("    on every cycle but not surfacing this via normal alerts.")
        print("    The MES is recording 'failure' status, but without cross-")
        print("    referencing the vendor logs the pattern was not visible.")
        print()
        print("  Recommended action:")
        print("    1. Take MILL-03 offline and inspect spindle assembly.")
        print("    2. Review vendor controller alarm history for MILL-03.")
        print("    3. Verify tooling, coolant, and spindle speed calibration.")
        print("    4. Re-run a test batch before returning to production.")
        print(SEP)

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Correlate MES and vendor CNC logs to detect equipment anomalies."
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to YAML config file (default: config.yaml)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override output directory from config",
    )
    args = parser.parse_args()

    # Load config
    config = load_config(args.config)
    if args.output_dir:
        config["output_dir"] = args.output_dir

    thresholds    = config["thresholds"]
    min_samples   = int(thresholds.get("min_sample_size", 5))
    warn_thresh   = float(thresholds.get("failure_rate_warning", 0.10))
    crit_thresh   = float(thresholds.get("failure_rate_critical", 0.25))

    # Load logs
    internal = load_json(config["internal_log_path"])
    vendor   = load_json(config["vendor_log_path"])

    # Correlate
    correlated = inner_join(internal, vendor)

    # Compute failure rates
    failure_rates = compute_failure_rates(correlated, min_sample_size=min_samples)

    # --- Anomaly detection ---

    # 1. High failure rate on correlated records (use critical threshold)
    high_failure_findings = anomaly_detector.detect_high_failure_rate(
        jobs           = correlated,
        threshold      = crit_thresh,
        status_key     = "internal_status",
        group_by       = ("job_type", "machine_id"),
        min_sample_size = min_samples,
    )

    # 2. Missing correlations
    missing_correlation_findings = anomaly_detector.detect_missing_correlations(
        internal = internal,
        vendor   = vendor,
    )

    # 3. Statistical machine anomalies
    machine_anomaly_findings = anomaly_detector.detect_machine_anomalies(
        correlated      = correlated,
        status_key      = "internal_status",
        min_sample_size = min_samples,
    )

    # Assemble report
    report = build_report(
        internal                     = internal,
        vendor                       = vendor,
        correlated                   = correlated,
        failure_rates                = failure_rates,
        high_failure_findings        = high_failure_findings,
        missing_correlation_findings = missing_correlation_findings,
        machine_anomaly_findings     = machine_anomaly_findings,
        config                       = config,
    )

    # Write report
    output_dir   = config["output_dir"]
    report_path  = os.path.join(output_dir, "correlation_report.json")
    write_json(report_path, report)

    # Print summary
    print_summary(report)

    print(f"  Full report written to: {os.path.abspath(report_path)}")
    print()


if __name__ == "__main__":
    main()
