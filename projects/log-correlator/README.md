# log-correlator

A Python tool that ingests logs from two manufacturing systems, correlates events across them by batch ID and machine ID, and surfaces anomalies — including patterns that would be invisible when looking at either log source alone.

## The Problem It Solves

In manufacturing environments, multiple systems log the same physical events independently: the internal MES records job outcomes, and the vendor equipment controller logs its own results. When something goes wrong, the failure often shows up in both logs but in different formats, making it hard to see the full picture.

This tool joins the two log streams and computes per-machine, per-job-type failure rates across both sources. Anomalies — like a single machine failing 100% of the time while the rest of the fleet is fine — become immediately visible in the correlation report.

## What it detects

- **High failure rate** — job types or machines where failure rate exceeds a configurable threshold
- **Missing correlations** — batch IDs present in one log source but absent in the other (data loss, connectivity gaps)
- **Machine anomalies** — machine+job-type combinations with failure rates significantly above the fleet average

## Architecture

```
sample_data/internal_logs.json  ─┐
                                  ├──▶ correlator.py ──▶ correlation_report.json
sample_data/vendor_logs.json    ─┘                  └──▶ stdout text summary
```

## Prerequisites

- Python 3.10+ with pip (no Docker required for standalone use)

## Run standalone

```bash
cd projects/log-correlator/
pip install pyyaml
python3 correlator.py
```

## Run with Docker

```bash
docker compose up
```

## Generate fresh test data

```bash
python3 simulate_logs.py --output-dir sample_data/
```

## Configuration

`config.yaml`:

```yaml
internal_log_path: "sample_data/internal_logs.json"
vendor_log_path: "sample_data/vendor_logs.json"
output_dir: "sample_data/"

thresholds:
  failure_rate_warning: 0.15
  failure_rate_critical: 0.50
  min_sample_size: 3
```

## Example Output

```
Log Correlation Report
════════════════���═════════════════════════════
Total events processed:   201
  Internal log entries:   103
  Vendor log entries:      98
  Matched pairs:           94  (90.4% correlation rate)

ANOMALIES DETECTED
──────────────────
  [CRITICAL] Machine MILL-03 | Job MILL_OP
    Failure rate: 100.0% (15/15 events)
    Fleet average for MILL_OP: 6.3%
    Vendor error code: E_SPINDLE_FAULT (consistent)
    → Likely cause: mechanical fault on MILL-03 spindle

  [WARNING] Missing vendor records for 4 batch IDs
    Batches: B-0042, B-0071, B-0088, B-0094
    → Check vendor controller connectivity during those windows

No anomalies in remaining 5 machine/job combinations.
```
