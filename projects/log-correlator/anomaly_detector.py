"""
anomaly_detector.py

Pure-logic module (not a script) for detecting anomalies in manufacturing
log data.  All functions operate on plain Python dicts / lists and have no
I/O side-effects.

Public API
----------
detect_high_failure_rate(jobs, threshold)       -> list[dict]
detect_missing_correlations(internal, vendor)   -> dict
detect_machine_anomalies(correlated)            -> list[dict]
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_failure(status: str) -> bool:
    """Return True for any status that counts as a non-success outcome."""
    return status.lower() in {"failure", "error", "timeout"}


def _failure_rate(records: list[dict], status_key: str) -> float:
    """Compute fraction of records where status_key is a failure."""
    if not records:
        return 0.0
    failed = sum(1 for r in records if _is_failure(r.get(status_key, "")))
    return failed / len(records)


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def detect_high_failure_rate(
    jobs: list[dict],
    threshold: float,
    status_key: str = "status",
    group_by: tuple[str, ...] = ("job_type", "machine_id"),
    min_sample_size: int = 5,
) -> list[dict]:
    """
    Group *jobs* by the fields in *group_by* and return a list of findings
    for every group whose failure rate exceeds *threshold*.

    Parameters
    ----------
    jobs : list[dict]
        Log records (internal MES format or pre-normalised dicts).
    threshold : float
        Failure rate above which a group is flagged (e.g. 0.10 for 10 %).
    status_key : str
        The field name that holds the outcome string.
    group_by : tuple[str, ...]
        Fields to group on before computing failure rates.
    min_sample_size : int
        Groups with fewer records than this are skipped.

    Returns
    -------
    list[dict]
        Each finding contains all group-by field values, plus:
        ``sample_count``, ``failure_count``, ``failure_rate``,
        ``threshold_used``.
    """
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for record in jobs:
        key = tuple(record.get(f, "__UNKNOWN__") for f in group_by)
        buckets[key].append(record)

    findings: list[dict] = []
    for key, records in buckets.items():
        if len(records) < min_sample_size:
            continue
        rate = _failure_rate(records, status_key)
        if rate > threshold:
            finding: dict[str, Any] = {}
            for field, value in zip(group_by, key):
                finding[field] = value
            failure_count = sum(
                1 for r in records if _is_failure(r.get(status_key, ""))
            )
            finding["sample_count"]    = len(records)
            finding["failure_count"]   = failure_count
            finding["failure_rate"]    = round(rate, 4)
            finding["threshold_used"]  = threshold
            findings.append(finding)

    # Sort most-severe first
    findings.sort(key=lambda f: f["failure_rate"], reverse=True)
    return findings


def detect_missing_correlations(
    internal: list[dict],
    vendor: list[dict],
    join_keys: tuple[str, str] = ("batch_id", "machine_id"),
) -> dict:
    """
    Identify batch+machine combinations present in one log source but absent
    in the other.

    Parameters
    ----------
    internal : list[dict]
        MES API log records.
    vendor : list[dict]
        Vendor CNC controller log records.
    join_keys : tuple[str, str]
        The pair of fields that form the correlation key.

    Returns
    -------
    dict with keys:
        ``in_internal_only``  — list of (batch_id, machine_id) tuples found
                                only in internal logs.
        ``in_vendor_only``    — list of (batch_id, machine_id) tuples found
                                only in vendor logs.
        ``matched_count``     — number of keys present in both sources.
        ``internal_total``    — total distinct keys in internal.
        ``vendor_total``      — total distinct keys in vendor.
        ``correlation_rate``  — matched_count / max(internal_total, vendor_total).
    """
    def _extract_keys(records: list[dict]) -> set[tuple]:
        return {
            tuple(r.get(k, "__MISSING__") for k in join_keys)
            for r in records
        }

    internal_keys = _extract_keys(internal)
    vendor_keys   = _extract_keys(vendor)

    in_internal_only = sorted(internal_keys - vendor_keys)
    in_vendor_only   = sorted(vendor_keys   - internal_keys)
    matched          = internal_keys & vendor_keys

    total = max(len(internal_keys), len(vendor_keys))
    corr_rate = len(matched) / total if total else 0.0

    return {
        "in_internal_only": [list(k) for k in in_internal_only],
        "in_vendor_only":   [list(k) for k in in_vendor_only],
        "matched_count":    len(matched),
        "internal_total":   len(internal_keys),
        "vendor_total":     len(vendor_keys),
        "correlation_rate": round(corr_rate, 4),
    }


def detect_machine_anomalies(
    correlated: list[dict],
    status_key: str = "internal_status",
    min_sample_size: int = 5,
    z_score_threshold: float = 2.0,
) -> list[dict]:
    """
    Find (machine_id, job_type) combinations whose failure rate is
    statistically anomalous compared to the fleet-wide baseline for that
    job type.

    Uses a **leave-one-out median / MAD** (median absolute deviation)
    approach so that a single severe outlier does not inflate the fleet
    baseline and hide itself.  For each machine being evaluated the fleet
    baseline is computed from *all other* machines of the same job type.
    The modified z-score is:

        z = 0.6745 * (rate - median_peers) / MAD_peers

    A machine is flagged when z >= z_score_threshold.

    Parameters
    ----------
    correlated : list[dict]
        Joined records produced by the correlator (each record has both
        internal and vendor fields merged together).
    status_key : str
        Field name for the outcome used to count failures.
    min_sample_size : int
        Machine+job_type groups with fewer records are excluded.
    z_score_threshold : float
        Modified z-score above which a machine is flagged (default 2.0).

    Returns
    -------
    list[dict]
        Each anomaly finding contains: ``machine_id``, ``job_type``,
        ``failure_rate``, ``fleet_median_rate``, ``fleet_mad``,
        ``z_score``, ``sample_count``, ``failure_count``,
        ``dominant_error_code`` (most common vendor error code, or None).
    """
    import math

    # Build (job_type, machine_id) -> records
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for rec in correlated:
        jt  = rec.get("job_type",  "__UNKNOWN__")
        mid = rec.get("machine_id", "__UNKNOWN__")
        groups[(jt, mid)].append(rec)

    # Compute per-group failure rates (skip undersized groups)
    group_rates: dict[tuple[str, str], dict] = {}
    for (jt, mid), recs in groups.items():
        if len(recs) < min_sample_size:
            continue
        fails = sum(1 for r in recs if _is_failure(r.get(status_key, "")))
        rate  = fails / len(recs)
        group_rates[(jt, mid)] = {
            "rate":          rate,
            "sample_count":  len(recs),
            "failure_count": fails,
            "records":       recs,
        }

    # Collect all rates per job_type for peer lookups
    job_type_all_rates: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (jt, mid), info in group_rates.items():
        job_type_all_rates[jt].append((mid, info["rate"]))

    def _median(values: list[float]) -> float:
        if not values:
            return 0.0
        sv = sorted(values)
        n  = len(sv)
        mid = n // 2
        return (sv[mid - 1] + sv[mid]) / 2.0 if n % 2 == 0 else sv[mid]

    def _mad(values: list[float], med: float) -> float:
        """Median absolute deviation."""
        if not values:
            return 0.0
        deviations = [abs(v - med) for v in values]
        return _median(deviations)

    # Flag anomalies using leave-one-out peer baseline
    findings: list[dict] = []
    for (jt, mid), info in group_rates.items():
        # Peer rates: all machines of the same job_type except this one
        peer_rates = [r for (m, r) in job_type_all_rates[jt] if m != mid]

        if not peer_rates:
            # Only one machine of this type — cannot compare
            continue

        med = _median(peer_rates)
        mad = _mad(peer_rates, med)

        # Modified z-score (Iglewicz & Hoaglin)
        if mad == 0.0:
            # All peers share the same rate.  Require at least 3 peers before
            # treating a deviation as anomalous (avoids flagging single-peer
            # comparisons as infinitely anomalous on small fleets).
            if len(peer_rates) < 3:
                continue
            z = 0.0 if info["rate"] == med else float("inf")
        else:
            z = 0.6745 * abs(info["rate"] - med) / mad

        # Only flag machines that are *worse* than peers, not just different
        if z < z_score_threshold or info["rate"] <= med:
            continue

        # Most common vendor error code among failures
        error_codes = [
            r.get("error_code")
            for r in info["records"]
            if r.get("error_code") not in (None, "", "null")
        ]
        dominant_error: str | None = None
        if error_codes:
            dominant_error = max(set(error_codes), key=error_codes.count)

        findings.append(
            {
                "machine_id":           mid,
                "job_type":             jt,
                "failure_rate":         round(info["rate"], 4),
                "fleet_median_rate":    round(med, 4),
                "fleet_mad":            round(mad, 4),
                "z_score":              round(z, 2),
                "sample_count":         info["sample_count"],
                "failure_count":        info["failure_count"],
                "dominant_error_code":  dominant_error,
            }
        )

    findings.sort(key=lambda f: f["z_score"], reverse=True)
    return findings
