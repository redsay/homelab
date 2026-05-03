"""
simulate_logs.py

Generates realistic simulated log files for a manufacturing environment:
  - internal_logs.json  : MES API logs
  - vendor_logs.json    : CNC controller (vendor equipment) logs

The embedded anomaly: MILL_OP jobs on machine MILL-03 have a 100% failure
rate across 15 events (vendor error code: E_SPINDLE_FAULT).  All other
machine/job-type combinations have a normal ~5% failure rate.
"""

import argparse
import json
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JOB_TYPES = ["MILL_OP", "DRILL_OP", "WELD_OP", "INSPECT_OP", "ASSEMBLE_OP"]

# job_type -> vendor operation_code
OPERATION_CODE_MAP = {
    "MILL_OP":     "OP_MILL",
    "DRILL_OP":    "OP_DRILL",
    "WELD_OP":     "OP_WELD",
    "INSPECT_OP":  "OP_INSP",
    "ASSEMBLE_OP": "OP_ASSY",
}

# Machines keyed by job_type (each type has a small fleet)
MACHINES = {
    "MILL_OP":     ["MILL-01", "MILL-02", "MILL-03", "MILL-04"],
    "DRILL_OP":    ["DRILL-01", "DRILL-02", "DRILL-03"],
    "WELD_OP":     ["WELD-01", "WELD-02"],
    "INSPECT_OP":  ["CMM-01", "CMM-02"],
    "ASSEMBLE_OP": ["ASSY-01", "ASSY-02", "ASSY-03"],
}

OPERATORS = [
    "OP_JENSEN", "OP_KOWALSKI", "OP_NAKAMURA", "OP_RILEY",
    "OP_HASSAN", "OP_FISCHER", "OP_ODUYA",
]

# Duration ranges (ms) per job type – normal operation
DURATION_RANGES = {
    "MILL_OP":     (45_000, 180_000),
    "DRILL_OP":    (8_000,  35_000),
    "WELD_OP":     (60_000, 240_000),
    "INSPECT_OP":  (20_000, 90_000),
    "ASSEMBLE_OP": (90_000, 420_000),
}

# Vendor error codes by job type (used when a job fails)
ERROR_CODES = {
    "MILL_OP":     ["E_SPINDLE_FAULT", "E_TOOL_BREAK", "E_OVERLOAD"],
    "DRILL_OP":    ["E_FEED_RATE_ERR", "E_TOOL_BREAK", "E_COOLANT_LOW"],
    "WELD_OP":     ["E_ARC_FAULT", "E_GAS_PRESSURE", "E_WIRE_FEED"],
    "INSPECT_OP":  ["E_PROBE_ERR", "E_FIXTURE_SLIP"],
    "ASSEMBLE_OP": ["E_TORQUE_LIMIT", "E_PART_MISSING", "E_SENSOR_FAIL"],
}

NORMAL_FAILURE_RATE = 0.05   # 5 % baseline for healthy machines
ANOMALY_MACHINE    = "MILL-03"
ANOMALY_JOB_TYPE   = "MILL_OP"
ANOMALY_ERROR_CODE = "E_SPINDLE_FAULT"
ANOMALY_COUNT      = 15      # forced failure events on MILL-03

TOTAL_TARGET_EVENTS = 200
DAYS_SPAN           = 7

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_timestamp(base: datetime, days: int) -> str:
    offset_seconds = random.randint(0, days * 86_400)
    ts = base + timedelta(seconds=offset_seconds)
    return ts.isoformat(timespec="seconds")


def _batch_id() -> str:
    return f"BATCH-{uuid.uuid4().hex[:8].upper()}"


def _make_internal_record(
    event_num: int,
    timestamp: str,
    batch_id: str,
    job_type: str,
    machine_id: str,
    status: str,
    duration_ms: int,
    parts_count: int,
) -> dict:
    return {
        "event_id":    f"EVT-{event_num:05d}",
        "timestamp":   timestamp,
        "batch_id":    batch_id,
        "job_type":    job_type,
        "machine_id":  machine_id,
        "operator_id": random.choice(OPERATORS),
        "status":      status,
        "duration_ms": duration_ms,
        "parts_count": parts_count,
    }


def _make_vendor_record(
    log_num: int,
    timestamp: str,
    batch_id: str,
    machine_id: str,
    job_type: str,
    result: str,
    error_code: str | None,
    cycle_time_ms: int,
) -> dict:
    return {
        "log_id":         f"VND-{log_num:05d}",
        "timestamp":      timestamp,
        "batch_id":       batch_id,
        "machine_id":     machine_id,
        "operation_code": OPERATION_CODE_MAP[job_type],
        "result":         result,
        "error_code":     error_code,
        "cycle_time_ms":  cycle_time_ms,
    }


# ---------------------------------------------------------------------------
# Generation logic
# ---------------------------------------------------------------------------

def generate_logs(total_events: int = TOTAL_TARGET_EVENTS) -> tuple[list, list]:
    """
    Return (internal_records, vendor_records).

    Strategy
    --------
    1. Generate ANOMALY_COUNT forced-failure events for MILL-03 / MILL_OP.
    2. Fill the remaining slots with random normal events (~5 % failure rate).
    3. Both log sources share batch_id + machine_id so they can be correlated.
    """
    random.seed(42)

    base_time = datetime(2025, 4, 1, 6, 0, 0, tzinfo=timezone.utc)

    internal_records: list[dict] = []
    vendor_records:   list[dict] = []

    event_counter = 1
    log_counter   = 1

    # ------------------------------------------------------------------ #
    # Step 1 – Anomalous events (MILL-03 / MILL_OP, always fail)
    # ------------------------------------------------------------------ #
    for _ in range(ANOMALY_COUNT):
        ts         = _random_timestamp(base_time, DAYS_SPAN)
        batch_id   = _batch_id()
        duration   = random.randint(*DURATION_RANGES["MILL_OP"])
        parts      = random.randint(1, 4)

        # Internal MES shows "failure"
        internal_records.append(
            _make_internal_record(
                event_num    = event_counter,
                timestamp    = ts,
                batch_id     = batch_id,
                job_type     = ANOMALY_JOB_TYPE,
                machine_id   = ANOMALY_MACHINE,
                status       = "failure",
                duration_ms  = duration,
                parts_count  = parts,
            )
        )

        # Vendor controller silently records E_SPINDLE_FAULT with result ERROR
        vendor_records.append(
            _make_vendor_record(
                log_num       = log_counter,
                timestamp     = ts,
                batch_id      = batch_id,
                machine_id    = ANOMALY_MACHINE,
                job_type      = ANOMALY_JOB_TYPE,
                result        = "ERROR",
                error_code    = ANOMALY_ERROR_CODE,
                cycle_time_ms = duration + random.randint(-500, 500),
            )
        )

        event_counter += 1
        log_counter   += 1

    # ------------------------------------------------------------------ #
    # Step 2 – Normal events
    # ------------------------------------------------------------------ #
    normal_count = total_events - ANOMALY_COUNT

    for _ in range(normal_count):
        job_type   = random.choice(JOB_TYPES)
        # Exclude MILL-03 from the normal pool (its events are forced above)
        machine_pool = [m for m in MACHINES[job_type] if m != ANOMALY_MACHINE]
        if not machine_pool:
            machine_pool = MACHINES[job_type]
        machine_id = random.choice(machine_pool)

        ts         = _random_timestamp(base_time, DAYS_SPAN)
        batch_id   = _batch_id()
        duration   = random.randint(*DURATION_RANGES[job_type])
        parts      = random.randint(1, 20)

        # Determine outcome
        roll = random.random()
        if roll < NORMAL_FAILURE_RATE * 0.4:
            # timeout: internal=timeout, vendor=TIMEOUT, no error code
            int_status  = "timeout"
            vnd_result  = "TIMEOUT"
            error_code  = None
        elif roll < NORMAL_FAILURE_RATE:
            # failure: internal=failure, vendor=ERROR, random error code
            int_status  = "failure"
            vnd_result  = "ERROR"
            error_code  = random.choice(ERROR_CODES[job_type])
        else:
            int_status  = "success"
            vnd_result  = "OK"
            error_code  = None

        internal_records.append(
            _make_internal_record(
                event_num    = event_counter,
                timestamp    = ts,
                batch_id     = batch_id,
                job_type     = job_type,
                machine_id   = machine_id,
                status       = int_status,
                duration_ms  = duration,
                parts_count  = parts,
            )
        )

        vendor_records.append(
            _make_vendor_record(
                log_num       = log_counter,
                timestamp     = ts,
                batch_id      = batch_id,
                machine_id    = machine_id,
                job_type      = job_type,
                result        = vnd_result,
                error_code    = error_code,
                cycle_time_ms = duration + random.randint(-1000, 1000),
            )
        )

        event_counter += 1
        log_counter   += 1

    # Sort both lists chronologically
    internal_records.sort(key=lambda r: r["timestamp"])
    vendor_records.sort(key=lambda r: r["timestamp"])

    return internal_records, vendor_records


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate simulated MES + CNC controller log files."
    )
    parser.add_argument(
        "--output-dir",
        default="sample_data",
        help="Directory to write JSON log files (default: sample_data/)",
    )
    parser.add_argument(
        "--total-events",
        type=int,
        default=TOTAL_TARGET_EVENTS,
        help=f"Total number of events to generate (default: {TOTAL_TARGET_EVENTS})",
    )
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    internal_records, vendor_records = generate_logs(args.total_events)

    internal_path = os.path.join(args.output_dir, "internal_logs.json")
    vendor_path   = os.path.join(args.output_dir, "vendor_logs.json")

    with open(internal_path, "w") as f:
        json.dump(internal_records, f, indent=2)

    with open(vendor_path, "w") as f:
        json.dump(vendor_records, f, indent=2)

    # Summary
    total_internal = len(internal_records)
    total_vendor   = len(vendor_records)
    int_failures   = sum(1 for r in internal_records if r["status"] in ("failure", "timeout"))
    mill03_events  = [r for r in internal_records if r["machine_id"] == ANOMALY_MACHINE]
    mill03_fails   = sum(1 for r in mill03_events if r["status"] in ("failure", "timeout"))

    print("=" * 58)
    print("  Log simulation complete")
    print("=" * 58)
    print(f"  Output directory   : {os.path.abspath(args.output_dir)}")
    print(f"  internal_logs.json : {total_internal} records")
    print(f"  vendor_logs.json   : {total_vendor} records")
    print(f"  Overall failure rate (internal): "
          f"{int_failures}/{total_internal} = "
          f"{int_failures/total_internal:.1%}")
    print(f"  MILL-03 events     : {len(mill03_events)}")
    print(f"  MILL-03 failures   : {mill03_fails} "
          f"({mill03_fails/len(mill03_events):.0%} — anomaly seeded)")
    print("=" * 58)


if __name__ == "__main__":
    main()
