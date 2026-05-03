"""
sim_engine.py — Manufacturing simulation engine.

Simulates a small facility with 5 machines. Each call to tick() advances
the simulation by one step, updating machine states and facility metrics.
get_state() returns a full JSON-serialisable snapshot.
get_prometheus_metrics() returns Prometheus text-format output.
"""

import random
import time
import math
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

STATUS_RUNNING = "running"
STATUS_IDLE = "idle"
STATUS_FAULT = "fault"
STATUS_MAINTENANCE = "maintenance"

# Temperature ranges by machine type (celsius)
TEMP_PROFILES: dict[str, dict[str, float]] = {
    "cnc_mill":       {"base": 45.0, "running_delta": 30.0, "noise": 3.0},
    "cnc_drill":      {"base": 38.0, "running_delta": 22.0, "noise": 2.5},
    "robot_welder":   {"base": 28.0, "running_delta":  8.0, "noise": 2.0},
    "cmm_inspection": {"base": 22.0, "running_delta":  2.0, "noise": 0.5},
}

# Rejection rate by machine type (fraction of produced parts)
REJECT_RATES: dict[str, float] = {
    "cnc_mill":       0.02,
    "cnc_drill":      0.01,
    "robot_welder":   0.03,
    "cmm_inspection": 0.005,
}

# How many consecutive ticks a machine stays faulted before auto-recovering
FAULT_RECOVERY_TICKS = 4

# Cycle-time jitter (±fraction of base_cycle_time_ms)
CYCLE_JITTER = 0.08

# Probability of going to maintenance from idle (very low, keeps things spicy)
MAINTENANCE_RATE = 0.01

# Ticks in maintenance before returning to idle
MAINTENANCE_DURATION_TICKS = 10

# Fake job ID prefixes per machine type
JOB_PREFIXES: dict[str, str] = {
    "cnc_mill":       "JOB-MILL",
    "cnc_drill":      "JOB-DRL",
    "robot_welder":   "JOB-WLD",
    "cmm_inspection": "JOB-INS",
}


# ──────────────────────────────────────────────────────────────────────────────
# MachineState
# ──────────────────────────────────────────────────────────────────────────────

class MachineState:
    """Mutable state container for one machine."""

    def __init__(self, machine_cfg: dict[str, Any]) -> None:
        self.id: str = machine_cfg["id"]
        self.machine_type: str = machine_cfg["type"]
        self.base_cycle_time_ms: int = machine_cfg["base_cycle_time_ms"]
        self.fault_rate: float = machine_cfg["fault_rate"]

        # Dynamic state
        self.status: str = STATUS_RUNNING
        self.current_job: str | None = self._new_job_id()
        self.parts_produced_today: int = random.randint(0, 30)
        self.parts_rejected_today: int = 0
        self.cycle_time_ms: float = float(self.base_cycle_time_ms)
        self.temperature_c: float = self._base_temp()

        # Internal counters
        self._fault_ticks_remaining: int = 0
        self._maintenance_ticks_remaining: int = 0
        self._running_ticks: int = 0
        self._total_ticks: int = 0

        # Seed a plausible initial rejection count
        reject_rate = REJECT_RATES.get(self.machine_type, 0.02)
        self.parts_rejected_today = int(self.parts_produced_today * reject_rate * random.uniform(0.5, 1.5))

    # ── helpers ──────────────────────────────────────────────────────────────

    def _base_temp(self) -> float:
        profile = TEMP_PROFILES.get(self.machine_type, {"base": 25.0, "running_delta": 5.0, "noise": 1.0})
        return profile["base"] + profile["running_delta"] * 0.5

    def _new_job_id(self) -> str:
        prefix = JOB_PREFIXES.get(self.machine_type, "JOB")
        return f"{prefix}-{random.randint(1000, 9999)}"

    def _jittered_cycle_time(self) -> float:
        delta = self.base_cycle_time_ms * CYCLE_JITTER
        return self.base_cycle_time_ms + random.uniform(-delta, delta)

    def _update_temperature(self) -> None:
        profile = TEMP_PROFILES.get(self.machine_type, {"base": 25.0, "running_delta": 5.0, "noise": 1.0})
        target = profile["base"]
        if self.status == STATUS_RUNNING:
            target += profile["running_delta"]
        elif self.status == STATUS_FAULT:
            # Temperature stays elevated when faulted (e.g. overheat fault)
            target += profile["running_delta"] * 0.8
        noise = random.gauss(0, profile["noise"])
        # Smooth towards target
        self.temperature_c += (target - self.temperature_c) * 0.3 + noise

    # ── tick ─────────────────────────────────────────────────────────────────

    def tick(self) -> None:
        """Advance this machine's state by one simulation step."""
        self._total_ticks += 1

        if self.status == STATUS_FAULT:
            self._tick_faulted()
        elif self.status == STATUS_MAINTENANCE:
            self._tick_maintenance()
        elif self.status == STATUS_RUNNING:
            self._tick_running()
        else:  # idle
            self._tick_idle()

        self._update_temperature()

    def _tick_running(self) -> None:
        self._running_ticks += 1
        # Possibly fault
        if random.random() < self.fault_rate:
            logger.info("Machine %s entering FAULT state", self.id)
            self.status = STATUS_FAULT
            self._fault_ticks_remaining = FAULT_RECOVERY_TICKS + random.randint(0, 3)
            self.current_job = None
            return

        # Produce a part
        self.parts_produced_today += 1
        reject_rate = REJECT_RATES.get(self.machine_type, 0.02)
        if random.random() < reject_rate:
            self.parts_rejected_today += 1

        # Update cycle time with jitter
        self.cycle_time_ms = self._jittered_cycle_time()

        # Occasionally finish a job and start a new one
        if random.random() < 0.05:
            self.current_job = self._new_job_id()

        # Occasionally go idle briefly
        if random.random() < 0.03:
            self.status = STATUS_IDLE
            self.current_job = None

    def _tick_faulted(self) -> None:
        self._fault_ticks_remaining -= 1
        if self._fault_ticks_remaining <= 0:
            logger.info("Machine %s recovered from FAULT → IDLE", self.id)
            self.status = STATUS_IDLE
            self._fault_ticks_remaining = 0

    def _tick_maintenance(self) -> None:
        self._maintenance_ticks_remaining -= 1
        if self._maintenance_ticks_remaining <= 0:
            logger.info("Machine %s leaving MAINTENANCE → RUNNING", self.id)
            self.status = STATUS_RUNNING
            self.current_job = self._new_job_id()
            self._maintenance_ticks_remaining = 0

    def _tick_idle(self) -> None:
        # Possibly enter maintenance
        if random.random() < MAINTENANCE_RATE:
            logger.info("Machine %s entering MAINTENANCE", self.id)
            self.status = STATUS_MAINTENANCE
            self._maintenance_ticks_remaining = MAINTENANCE_DURATION_TICKS + random.randint(0, 5)
            self.current_job = None
            return
        # Mostly return to running
        if random.random() < 0.6:
            self.status = STATUS_RUNNING
            self.current_job = self._new_job_id()
            self.cycle_time_ms = self._jittered_cycle_time()

    # ── derived metrics ───────────────────────────────────────────────────────

    @property
    def uptime_percent_today(self) -> float:
        if self._total_ticks == 0:
            return 100.0
        return round(100.0 * self._running_ticks / self._total_ticks, 2)

    @property
    def oee_percent(self) -> float:
        """
        Simplified OEE = Availability × Performance × Quality.
        Availability  = uptime_percent_today / 100
        Performance   = base_cycle / actual_cycle  (capped at 1.0)
        Quality       = good_parts / total_parts   (or 1.0 if no parts)
        """
        availability = self.uptime_percent_today / 100.0
        if self.cycle_time_ms > 0:
            performance = min(1.0, self.base_cycle_time_ms / self.cycle_time_ms)
        else:
            performance = 1.0
        total = self.parts_produced_today
        if total > 0:
            quality = (total - self.parts_rejected_today) / total
        else:
            quality = 1.0
        return round(availability * performance * quality * 100.0, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "machine_type": self.machine_type,
            "status": self.status,
            "current_job": self.current_job,
            "parts_produced_today": self.parts_produced_today,
            "parts_rejected_today": self.parts_rejected_today,
            "cycle_time_ms": round(self.cycle_time_ms, 1),
            "temperature_c": round(self.temperature_c, 2),
            "uptime_percent_today": self.uptime_percent_today,
            "oee_percent": self.oee_percent,
        }


# ──────────────────────────────────────────────────────────────────────────────
# ManufacturingSimulator
# ──────────────────────────────────────────────────────────────────────────────

class ManufacturingSimulator:
    """Top-level simulation object."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.facility_name: str = config.get("facility", {}).get("name", "Manufacturing Sim")
        self.shift_hours: int = config.get("facility", {}).get("shift_hours", 8)
        self.machines: list[MachineState] = [
            MachineState(m) for m in config.get("machines", [])
        ]
        self._tick_count: int = 0
        self._sim_start: float = time.time()
        logger.info(
            "Simulator initialised: %s — %d machines",
            self.facility_name,
            len(self.machines),
        )

    # ── simulation loop ───────────────────────────────────────────────────────

    def tick(self) -> None:
        """Advance simulation one step."""
        self._tick_count += 1
        for machine in self.machines:
            machine.tick()
        logger.debug("Tick %d complete", self._tick_count)

    # ── state snapshot ────────────────────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        machine_states = [m.to_dict() for m in self.machines]
        active_alerts = [
            {"machine_id": m.id, "reason": "fault"}
            for m in self.machines
            if m.status == STATUS_FAULT
        ]
        shift_output = sum(
            m.parts_produced_today - m.parts_rejected_today
            for m in self.machines
        )
        return {
            "facility": {
                "name": self.facility_name,
                "shift_hours": self.shift_hours,
                "shift_output": shift_output,
                "active_alerts": active_alerts,
                "active_faults": len(active_alerts),
                "tick_count": self._tick_count,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            },
            "machines": {m["id"]: m for m in machine_states},
        }

    # ── Prometheus metrics ────────────────────────────────────────────────────

    def get_prometheus_metrics(self) -> str:
        """Return Prometheus text-format metrics string."""
        lines: list[str] = []
        state = self.get_state()

        # ── machine-level metrics ─────────────────────────────────────────────

        # machine_status
        lines.append("# HELP machine_status 1 if machine is running, 0 otherwise")
        lines.append("# TYPE machine_status gauge")
        for m in self.machines:
            val = 1 if m.status == STATUS_RUNNING else 0
            lines.append(
                f'machine_status{{machine_id="{m.id}",machine_type="{m.machine_type}"}} {val}'
            )

        # machine_parts_produced_today
        lines.append("# HELP machine_parts_produced_today Parts produced today (good + rejected)")
        lines.append("# TYPE machine_parts_produced_today gauge")
        for m in self.machines:
            lines.append(
                f'machine_parts_produced_today{{machine_id="{m.id}"}} {m.parts_produced_today}'
            )

        # machine_parts_rejected_today
        lines.append("# HELP machine_parts_rejected_today Rejected parts today")
        lines.append("# TYPE machine_parts_rejected_today gauge")
        for m in self.machines:
            lines.append(
                f'machine_parts_rejected_today{{machine_id="{m.id}"}} {m.parts_rejected_today}'
            )

        # machine_cycle_time_ms
        lines.append("# HELP machine_cycle_time_ms Current cycle time in milliseconds")
        lines.append("# TYPE machine_cycle_time_ms gauge")
        for m in self.machines:
            lines.append(
                f'machine_cycle_time_ms{{machine_id="{m.id}"}} {round(m.cycle_time_ms, 1)}'
            )

        # machine_temperature_c
        lines.append("# HELP machine_temperature_c Spindle/tool temperature in Celsius")
        lines.append("# TYPE machine_temperature_c gauge")
        for m in self.machines:
            lines.append(
                f'machine_temperature_c{{machine_id="{m.id}"}} {round(m.temperature_c, 2)}'
            )

        # machine_oee_percent
        lines.append("# HELP machine_oee_percent Overall Equipment Effectiveness (0-100)")
        lines.append("# TYPE machine_oee_percent gauge")
        for m in self.machines:
            lines.append(
                f'machine_oee_percent{{machine_id="{m.id}"}} {m.oee_percent}'
            )

        # machine_uptime_percent_today
        lines.append("# HELP machine_uptime_percent_today Uptime percentage today (0-100)")
        lines.append("# TYPE machine_uptime_percent_today gauge")
        for m in self.machines:
            lines.append(
                f'machine_uptime_percent_today{{machine_id="{m.id}"}} {m.uptime_percent_today}'
            )

        # ── facility-level metrics ────────────────────────────────────────────

        facility = state["facility"]

        lines.append("# HELP facility_shift_output_total Good parts produced this shift (all machines)")
        lines.append("# TYPE facility_shift_output_total gauge")
        lines.append(f'facility_shift_output_total {facility["shift_output"]}')

        lines.append("# HELP facility_active_faults Number of machines currently in fault state")
        lines.append("# TYPE facility_active_faults gauge")
        lines.append(f'facility_active_faults {facility["active_faults"]}')

        lines.append("")  # trailing newline required by Prometheus
        return "\n".join(lines)
