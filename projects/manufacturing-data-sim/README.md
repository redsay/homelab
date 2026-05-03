# manufacturing-data-sim

A simulated manufacturing data server that acts as a fake PLC/MES, generating realistic real-time metrics for 5 machines on a virtual production floor. Designed to run as a standalone server that other services (Prometheus, Grafana, system-monitor) can scrape.

## What it does

Simulates a small manufacturing facility with 5 machines:

| Machine | Type | Notes |
|---------|------|-------|
| MILL-01 | CNC Mill | Normal operation |
| MILL-02 | CNC Mill | Higher fault rate (15%) — interesting to watch |
| DRILL-01 | CNC Drill | Normal operation |
| WELD-01 | Robot Welder | Normal operation |
| INSPECT-01 | CMM Inspection | Low fault rate |

Each machine tracks: status (running/idle/fault/maintenance), parts produced/rejected today, cycle time, temperature, OEE, and uptime. The simulation runs on a configurable tick interval with realistic variability — machines enter and recover from fault states, temperatures fluctuate, OEE degrades with fault events.

## Architecture

```
sim_engine.py ──▶ server.py ──▶ GET /metrics  (Prometheus format)
                          └──▶ GET /status    (full JSON)
                          └──▶ GET /status/MILL-02  (single machine)
                          └──▶ GET /health
```

## Quick Start

```bash
cd projects/manufacturing-data-sim/
docker compose up -d
```

- Grafana (Manufacturing Floor dashboard): `http://localhost:3000`
- Raw JSON status: `http://localhost:9200/status`
- Prometheus metrics: `http://localhost:9200/metrics`

## Standalone (no Docker)

```bash
pip install pyyaml prometheus-client
python3 server.py
```

## Configuration

`config.yaml` lets you add/remove machines, change fault rates, and adjust tick speed:

```yaml
service:
  port: 9200
  tick_interval_seconds: 5

machines:
  - id: "MILL-01"
    type: "cnc_mill"
    base_cycle_time_ms: 45000
    fault_rate: 0.05   # 5% chance of fault per tick
```

## Example Output

`GET /status/MILL-02`:
```json
{
  "id": "MILL-02",
  "type": "cnc_mill",
  "status": "running",
  "parts_produced_today": 142,
  "parts_rejected_today": 9,
  "cycle_time_ms": 43218,
  "temperature_c": 67.4,
  "oee_percent": 71.2,
  "uptime_percent_today": 84.3
}
```

## Prometheus Metrics

```
machine_status{machine_id="MILL-02",machine_type="cnc_mill"} 1
machine_parts_produced_today{machine_id="MILL-02"} 142
machine_oee_percent{machine_id="MILL-02"} 71.2
facility_shift_output_total 687
facility_active_faults 0
```

## Grafana Dashboard

The included "Manufacturing Floor" dashboard auto-provisions on startup showing:
- Machine status tiles (green=running, red=fault, gray=idle) for all 5 machines
- OEE gauge per machine with industry-standard thresholds (world class = 85%)
- Parts produced over time, shift output total
