#!/usr/bin/env python3
"""Describe recorded touch signals; unlabeled data is not evidence of touch SNR.

Example: python3 scripts/analyze_capture.py .calibration/sessions/transport-check
Use --confirmed-idle only when the recording condition is independently known.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics


def summarize(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "sd": None, "median": None, "mad": None,
                "robust_sigma": None, "min": None, "max": None, "range": None,
                "fractional_mad": None}
    median = statistics.median(values)
    mad = statistics.median(abs(x - median) for x in values)
    return {"n": len(values), "mean": statistics.fmean(values),
            "sd": statistics.stdev(values) if len(values) > 1 else 0.0,
            "median": median, "mad": mad, "robust_sigma": 1.4826 * mad,
            "min": min(values), "max": max(values), "range": max(values) - min(values),
            "fractional_mad": mad / abs(median) if median else None}


def percentile(values: list[float], fraction: float):
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * fraction
    lo = int(pos)
    hi = math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def analyze_session(directory: str | Path, confirmed_idle: bool = False) -> dict:
    directory = Path(directory).expanduser().resolve()
    frame_path = directory / "frames.jsonl"
    raw_bytes = frame_path.read_bytes()
    session_path = directory / "session.json"
    session = json.loads(session_path.read_text()) if session_path.exists() else None
    counts = Counter()
    rows = []
    metadata = []
    for number, line in enumerate(raw_bytes.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict):
            raise ValueError(f"Line {number}: expected JSON object")
        kind = record.get("type", "unknown")
        phase = record.get("capture_phase", "unspecified")
        counts["total_records"] += 1
        counts[f"records_{phase}"] += 1
        if kind == "metadata":
            metadata.append(record)
        if kind != "sample":
            continue
        counts["total_samples"] += 1
        if phase != "recording":
            counts[f"excluded_samples_{phase}"] += 1
            continue
        required = ("timestamp_us", "scan_seq", "boot_id", "registered_mask",
                    "raw_valid_mask", "smooth_valid_mask", "benchmark_valid_mask",
                    "snapshot_duration_us")
        valid = all(isinstance(record.get(key), int) and not isinstance(record[key], bool)
                    and record[key] >= 0 for key in required)
        for name in ("raw", "smooth", "benchmark"):
            values = record.get(name)
            valid = valid and isinstance(values, list) and len(values) == 15
            if valid:
                valid = all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 0xffffffff
                            for v in values)
        if not valid:
            counts["excluded_invalid_sample_rows"] += 1
            continue
        rows.append(record)
    if not rows:
        raise ValueError("No valid samples explicitly marked capture_phase=recording")
    counts["recording_samples_analyzed"] = len(rows)
    boots = sorted({row["boot_id"] for row in rows})
    relevant_metadata = [m for m in metadata if m.get("boot_id") in boots]
    metadata_by_boot = {}
    for record in relevant_metadata:
        metadata_by_boot[str(record["boot_id"])] = record
    intervals = []
    for before, after in zip(rows, rows[1:]):
        if after["boot_id"] == before["boot_id"]:
            delta = after["timestamp_us"] - before["timestamp_us"]
            if delta > 0:
                intervals.append(delta)
            else:
                counts["non_increasing_timestamps"] += 1
    interval_stats = summarize(intervals)
    interval_stats.update(p95=percentile(intervals, .95), p99=percentile(intervals, .99))
    timing = {
        "device_interval_us": interval_stats,
        "median_scan_hz": 1e6 / statistics.median(intervals) if intervals else None,
        "mean_scan_hz": len(intervals) * 1e6 / sum(intervals) if intervals else None,
        "snapshot_duration_us": summarize([r["snapshot_duration_us"] for r in rows]),
    }
    warnings = []
    if not confirmed_idle:
        warnings.append("Unlabeled recording: variability may contain touch or movement; these statistics are descriptive, not an idle-noise or touch-SNR claim.")
    else:
        warnings.append("Idle condition supplied by caller; this report does not verify that the surface was untouched.")
    if session is None:
        warnings.append("session.json is missing; acquisition integrity report unavailable.")
    elif not session.get("quality", {}).get("clean", False):
        warnings.append("Session integrity is not clean; inspect integrity.issues before comparing measurements.")
    if len(boots) != 1:
        warnings.append("Multiple boots are pooled; use separate stable captures for acquisition comparisons.")
    missing_boots = [boot for boot in boots if str(boot) not in metadata_by_boot]
    if missing_boots:
        warnings.append(f"Firmware metadata missing for boots: {missing_boots}")
    if counts["excluded_invalid_sample_rows"] or counts["non_increasing_timestamps"]:
        warnings.append("Invalid rows or non-increasing device timestamps were found; see record_counts.")
    settings = []
    for record in relevant_metadata:
        acquisition = record.get("acquisition", {})
        if acquisition not in settings:
            settings.append(acquisition)
    charge_times = settings[0].get("charge_times") if len(settings) == 1 else None
    if not isinstance(charge_times, (int, float)) or isinstance(charge_times, bool) or charge_times <= 0:
        charge_times = None
        warnings.append("A single valid charge_times setting is unavailable; per-charge normalization omitted.")
    if len(settings) > 1:
        warnings.append("Acquisition settings differ within this recording; pooled per-GPIO statistics are not a controlled configuration comparison.")
    gpio_stats = {}
    for pad in range(1, 15):
        bit = 1 << pad
        pad_values = {name: [] for name in ("raw", "smooth", "benchmark", "raw_minus_benchmark", "smooth_minus_benchmark")}
        invalid = Counter()
        raw_pairs = []
        previous = None
        for row in rows:
            if not row["registered_mask"] & bit:
                invalid["unregistered"] += 1
                previous = None
                continue
            valid = {name: bool(row[name + "_valid_mask"] & bit) for name in ("raw", "smooth", "benchmark")}
            for name in valid:
                if valid[name]:
                    pad_values[name].append(row[name][pad])
                else:
                    invalid[name] += 1
            for name in ("raw", "smooth"):
                if valid[name] and valid["benchmark"]:
                    pad_values[name + "_minus_benchmark"].append(row[name][pad] - row["benchmark"][pad])
            if valid["raw"]:
                if (previous is not None and row["boot_id"] == previous["boot_id"] and
                        ((row["scan_seq"] - previous["scan_seq"]) & 0xffffffff) == 1):
                    raw_pairs.append(row["raw"][pad] - previous["raw"][pad])
                previous = row
            else:
                previous = None
        stats = {name: summarize(values) for name, values in pad_values.items()}
        diff_stats = summarize(raw_pairs)
        stats.update(physical_electrode=pad <= 12, invalid_or_unregistered=dict(invalid),
                     raw_consecutive_difference=diff_stats,
                     difference_robust_sigma_estimate=(diff_stats["robust_sigma"] / math.sqrt(2)
                                                      if diff_stats["n"] else None),
                     raw_mad_per_charge=(stats["raw"]["mad"] / charge_times
                                         if charge_times and stats["raw"]["n"] else None),
                     raw_sigma_per_charge=(stats["raw"]["robust_sigma"] / charge_times
                                           if charge_times and stats["raw"]["n"] else None))
        gpio_stats[str(pad)] = stats
    return {
        "session_dir": str(directory), "frames_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "condition": "caller_confirmed_idle" if confirmed_idle else "unlabeled",
        "record_counts": dict(counts), "boot_ids": boots,
        "integrity": session.get("quality") if session else None,
        "capture_start_ack": session.get("capture_start_ack") if session else None,
        "metadata_by_boot": metadata_by_boot, "acquisition_settings": settings,
        "timing": timing, "gpio": gpio_stats, "warnings": warnings,
        "interpretation": [
            "MAD is median absolute deviation from the median; robust_sigma = 1.4826 * MAD.",
            "fractional_mad = MAD / abs(median), a fraction rather than percent; per-charge fields use raw counter units divided by charge_times.",
            "Consecutive-difference sigma assumes independent stationary noise and excludes missing scans; it is descriptive for unlabeled motion.",
            "Hardware benchmark and smooth IIR coefficients operate per scan: changing scan rate also changes their time constants in seconds.",
            "Compare raw counters/charge or fractional raw variation across configurations; smoothed-minus-benchmark alone cannot establish touch signal-to-noise ratio.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--confirmed-idle", action="store_true", help="Assert independently known idle recording conditions")
    parser.add_argument("--output", type=Path, help="Write a new JSON report; existing files are refused")
    args = parser.parse_args()
    try:
        report = analyze_session(args.session_dir, confirmed_idle=args.confirmed_idle)
        rendered = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as output:
                output.write(rendered)
            print(args.output)
        else:
            print(rendered, end="")
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, f"Analysis failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
