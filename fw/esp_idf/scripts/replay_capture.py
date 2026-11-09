#!/usr/bin/env python3
"""Replay complete diagnostic captures through the shared C++ touch/gesture code.

No serial access. Text logs containing only occasional raw readings cannot be
replayed: they omit the idle/release frames on which gesture state depends.
Results describe this source tree, whose digest is recorded in the output;
they do not claim to reconstruct a different firmware build automatically.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_MASK = 0x1FFE
U32_MAX = (1 << 32) - 1
REFERENCE_CHARGE_TIMES = 800
BUILD_INPUTS = (
    "main/touch_processing.h", "main/touch_processing.cpp",
    "main/gestureDetector.h", "main/gestureDetector.cpp",
    "main/gestureTypes.h", "main/gestureConfig.h", "main/gestureLayout.h",
    "main/keyMap.h", "main/keyMap.cpp", "tools/replay_main.cpp",
    "tools/include/esp_log.h",
)


class ReplayError(ValueError):
    pass


def integer(record: dict, key: str, maximum: int = U32_MAX) -> int:
    value = record.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
        raise ReplayError(f"{key} must be an integer in 0..{maximum}")
    return value


def records(path: Path) -> Iterator[tuple[int, dict]]:
    with path.open("rb") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-finite constant {value}")))
            except (ValueError, UnicodeError) as exc:
                raise ReplayError(
                    f"line {number}: expected decoded capture JSONL; legacy text logs "
                    "lack complete timestamped idle/release samples and cannot be replayed"
                ) from exc
            if not isinstance(record, dict) or record.get("type") not in ("metadata", "sample", "marker", "device_event"):
                raise ReplayError(f"line {number}: expected metadata, sample, marker, or device_event record")
            yield number, record


def capture_phase(record: dict) -> str:
    # Only the collector's explicit handshake annotation permits exclusion.
    # Older complete captures without the annotation remain fully replayed.
    phase = record.get("capture_phase", "recording")
    if phase not in ("startup", "recording"):
        raise ReplayError(f"unknown capture_phase {phase!r}")
    return phase


def charge_normalization(record: dict) -> dict:
    acquisition = record.get("acquisition", {})
    if not isinstance(acquisition, dict):
        raise ReplayError("metadata acquisition must be an object")
    assumed = "charge_times" not in acquisition
    charge_times = REFERENCE_CHARGE_TIMES if assumed else integer(acquisition, "charge_times")
    if charge_times == 0:
        raise ReplayError("metadata acquisition.charge_times must be greater than zero")
    return {"charge_times": charge_times, "reference_charge_times": REFERENCE_CHARGE_TIMES,
            "delta_scale": REFERENCE_CHARGE_TIMES / charge_times,
            "source": "assumed_legacy_v1_default" if assumed else "acquisition_metadata"}


def capture_metadata(path: Path) -> dict[int, dict]:
    """Find provenance for recording boots, excluding unrelated startup boots.

    The HELLO response can precede the start-marker ACK. Its metadata may seed
    that boot's provenance, but never sequence checks or the processing model.
    Recording metadata takes precedence when a periodic record is available.
    """
    recording_boots = set()
    candidates = []
    for number, record in records(path):
        phase = capture_phase(record)
        if phase == "recording":
            recording_boots.add(integer(record, "boot_id"))
        if record["type"] == "metadata":
            candidates.append((number, record, phase))
    active_metadata_boots = {record.get("boot_id") for _, record, phase in candidates
                             if phase == "recording"}
    metadata = {}
    for number, record, phase in candidates:
        if phase == "startup":
            boot = record.get("boot_id")
            if (not isinstance(boot, int) or isinstance(boot, bool) or
                    boot not in recording_boots or boot in active_metadata_boots):
                continue
        boot_id = integer(record, "boot_id")
        if record.get("protocol_version") != 1 or record.get("capture_decimation") != 1:
            raise ReplayError(f"line {number}: replay requires protocol_version=1 and capture_decimation=1")
        if record.get("pad_ids") != list(range(15)):
            raise ReplayError(f"line {number}: metadata must declare physical pad order 0..14")
        # Changes of calibration/configuration within a boot must never be merged.
        identity = {key: record.get(key) for key in (
            "project", "mode", "board", "protocol_version", "pad_ids", "capture_decimation",
            "elf_sha256", "sdkconfig_sha256", "acquisition",
        )}
        previous = metadata.get(boot_id)
        if previous is not None and previous["identity"] != identity:
            raise ReplayError(f"line {number}: metadata identity changed within boot {boot_id}")
        metadata[boot_id] = {"identity": identity, "record": record,
                             "normalization": charge_normalization(record)}
    if not metadata:
        raise ReplayError("missing diagnostic metadata; sparse legacy channel logs are not a complete replay dataset")
    missing = recording_boots - metadata.keys()
    if missing:
        raise ReplayError(f"missing metadata for recording boot(s): {sorted(missing)}")
    return metadata


def build_host(build_dir: Path | None = None) -> tuple[Path, str]:
    compiler = os.environ.get("CXX", "c++")
    flags = ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror"]
    try:
        compiler_version = subprocess.run(
            [compiler, "--version"], check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReplayError(f"cannot run C++ compiler {compiler!r}") from exc
    digest = hashlib.sha256(compiler_version + repr(flags).encode())
    for relative in BUILD_INPUTS:
        digest.update(relative.encode() + b"\0" + (ROOT / relative).read_bytes())
    source_hash = digest.hexdigest()
    build_dir = build_dir or ROOT / ".calibration" / "host"
    executable = build_dir / f"replay-{source_hash[:20]}"
    if not executable.exists():
        build_dir.mkdir(parents=True, exist_ok=True)
        temporary = executable.with_suffix(f".tmp-{os.getpid()}")
        command = [compiler, *flags, "-I", str(ROOT / "tools/include"), "-I", str(ROOT / "main"),
                   str(ROOT / "tools/replay_main.cpp"), str(ROOT / "main/touch_processing.cpp"),
                   str(ROOT / "main/gestureDetector.cpp"), str(ROOT / "main/keyMap.cpp"),
                   "-o", str(temporary)]
        try:
            subprocess.run(command, check=True, stdout=sys.stderr)
            temporary.replace(executable)
        except subprocess.CalledProcessError as exc:
            raise ReplayError("host replay compilation failed") from exc
        finally:
            temporary.unlink(missing_ok=True)
    return executable, source_hash


def sample_deltas(record: dict) -> tuple[list[int], int, list[str]]:
    reasons = []
    masks = {key: integer(record, key, 0x7FFF) for key in (
        "registered_mask", "raw_valid_mask", "smooth_valid_mask", "benchmark_valid_mask")}
    for name, mask in masks.items():
        if mask & 1:
            reasons.append(f"{name} marks internal pad 0 valid")
        if mask & REQUIRED_MASK != REQUIRED_MASK:
            reasons.append(f"{name} missing required GPIOs 1..12")
    arrays = {}
    for key in ("raw", "smooth", "benchmark"):
        array = record.get(key)
        if not isinstance(array, list) or len(array) != 15:
            raise ReplayError(f"{key} must contain 15 physical-pad readings")
        if any(not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= U32_MAX
               for value in array):
            raise ReplayError(f"{key} readings must be unsigned 32-bit integers")
        arrays[key] = array
    deltas = [a - b for a, b in zip(arrays["smooth"], arrays["benchmark"])]
    if any(not -(1 << 31) <= delta < (1 << 31) for delta in deltas):
        raise ReplayError("smooth-minus-benchmark exceeds signed 32-bit range")
    mask = masks["registered_mask"] & masks["smooth_valid_mask"] & masks["benchmark_valid_mask"]
    return deltas, mask, reasons


class DeviceParity:
    """Compare recorded decisions only after an explicit device-idle checkpoint.

    Samples and their device events are emitted in one ordered bundle. An event
    must match the preceding sample; never pair gestures merely by list order.
    """
    def __init__(self, emit):
        self.emit = emit
        self.epoch = None
        self.pending = None
        self.last_event = None
        self.segments = self.compared = self.matched = self.errors = self.ignored = self.samples = 0

    def mismatch(self, reason, **details):
        self.errors += 1
        self.emit(dict(type="device_parity_mismatch", reason=reason, **details))

    def finish_pending(self):
        if self.pending is not None:
            self.mismatch("missing_device_gesture", boot_id=self.pending["boot_id"],
                          scan_seq=self.pending["scan_seq"], expected=self.pending["gesture"])
            self.pending = None

    def unsync(self):
        self.finish_pending()
        self.epoch = self.last_event = None

    def sample(self, result):
        self.finish_pending()
        if self.epoch is not None:
            self.samples += 1
            if result["gesture"] is not None:
                self.pending = result

    def event(self, record, latest, synchronize):
        kind = record.get("event")
        epoch = (integer(record, "boot_id"), integer(record, "processing_epoch"))
        sequence = integer(record, "event_seq")
        scan = integer(record, "scan_seq")
        timestamp = integer(record, "timestamp_us", (1 << 64) - 1)
        if self.last_event is not None and self.epoch is not None:
            if (sequence - self.last_event) & U32_MAX != 1:
                self.mismatch("device_event_sequence_gap", previous=self.last_event, current=sequence)
        self.last_event = sequence
        if kind == "idle_checkpoint":
            if (latest is None or latest["boot_id"] != epoch[0] or
                    latest["scan_seq"] != scan or latest["timestamp_us"] != timestamp):
                raise ReplayError("idle checkpoint does not follow its recorded sample")
            if latest.get("below_release_threshold") is not True:
                raise ReplayError("idle checkpoint references a sample above the release threshold")
            if self.epoch != epoch:
                self.finish_pending()
                synchronize()
                self.epoch = epoch
                self.segments += 1
                self.emit(dict(type="device_parity_sync", boot_id=epoch[0],
                               processing_epoch=epoch[1], scan_seq=scan, timestamp_us=timestamp))
            return
        if kind == "processing_reset":
            self.unsync()
            return
        if kind != "gesture":
            raise ReplayError(f"unknown device event {kind!r}")
        for key in ("gesture_type", "direction", "grid_position"):
            integer(record, key, 255)
        if self.epoch is None:
            self.ignored += 1
            return
        if epoch != self.epoch:
            self.mismatch("processing_epoch_changed_without_reset", recorded=list(epoch),
                          expected=list(self.epoch))
            self.unsync()
            return
        self.compared += 1
        expected = self.pending
        if expected is None or (expected["boot_id"], expected["scan_seq"], expected["timestamp_us"]) != (epoch[0], scan, timestamp):
            self.mismatch("unexpected_device_gesture", boot_id=epoch[0], scan_seq=scan,
                          recorded=record)
            return
        self.pending = None
        gesture = expected["gesture"]
        differences = {}
        for device_key, host_key in (("gesture_type", "type"), ("direction", "direction"),
                                     ("grid_position", "grid")):
            if record.get(device_key) != gesture[host_key]:
                differences[device_key] = [gesture[host_key], record.get(device_key)]
        for key in ("x", "y", "z", "start_x", "start_y", "max_distance"):
            wanted = expected[key] if key in ("x", "y", "z") else gesture[key]
            actual = record.get(key)
            if (not isinstance(actual, (int, float)) or isinstance(actual, bool) or
                    not math.isfinite(actual) or not math.isclose(wanted, actual, abs_tol=1e-4, rel_tol=1e-5)):
                differences[key] = [wanted, actual]
        action = record.get("action")
        wanted_action = gesture["action"] or {"type": "none", "value": ""}
        actual_action = None
        if isinstance(action, dict):
            action_type = action.get("type")
            value = action.get("label", "") if action_type in ("string", "special") else ""
            if action_type == "char":
                char_code = action.get("char_code")
                if isinstance(char_code, int) and not isinstance(char_code, bool) and 0 <= char_code <= 255:
                    value = chr(char_code)
                else:
                    value = None
            actual_action = {"type": action_type, "value": value}
        if actual_action != wanted_action:
            differences["action"] = [wanted_action, actual_action]
        if record.get("model") != "pcb":
            differences["model"] = ["pcb", record.get("model")]
        if differences:
            self.mismatch("decision_differs", boot_id=epoch[0], scan_seq=scan, differences=differences)
        else:
            self.matched += 1

    def summary(self):
        self.finish_pending()
        return {"synchronized_segments": self.segments, "compared_gestures": self.compared,
                "matched_gestures": self.matched, "mismatches": self.errors,
                "ignored_before_sync": self.ignored, "samples_after_sync": self.samples,
                "verified": self.segments > 0 and self.samples > 0 and self.errors == 0}


def replay(path: Path, mode: str, gap_policy: str, emit, executable: Path, source_hash: str,
           verify_device: bool = False) -> dict:
    metadata = capture_metadata(path)
    if verify_device and mode != "pcb":
        raise ReplayError("device verification requires --mode pcb")
    parity = DeviceParity(emit) if verify_device else None
    latest_result = None
    if mode == "pcb" and any(item["record"].get("board") != "capkey_6x6_50mm"
                             for item in metadata.values()):
        raise ReplayError("pcb mode requires metadata identifying the capkey_6x6_50mm board")
    input_hash = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            input_hash.update(chunk)
    emit({"type": "replay_metadata", "schema_version": 1, "mode": mode,
          "experimental": mode == "pcb", "input_sha256": input_hash.hexdigest(),
          "host_build_sha256": source_hash, "gap_policy": gap_policy,
          "delta_source": "smooth-minus-benchmark", "initial_detector_state": "idle",
          "normalization": {"kind": "linear_charge_time", "reference_charge_times": REFERENCE_CHARGE_TIMES,
                            "assumption": "signed deltas proportional to charge_times; not a calibrated response model",
                            "per_boot": [dict(metadata[boot]["normalization"], boot_id=boot) for boot in metadata]},
          "trial_markers_reset_detector": False, "verify_device": verify_device,
          "device_idle_checkpoint_sync": verify_device,
          "capture_metadata": [metadata[boot]["record"] for boot in metadata]})
    for boot, item in metadata.items():
        if item["normalization"]["source"] == "assumed_legacy_v1_default":
            emit({"type": "replay_notice", "reason": "missing_charge_times_assumed_800",
                  "boot_id": boot, "charge_times": REFERENCE_CHARGE_TIMES})
    count = events = resets = invalid = discontinuities = 0
    startup_skipped = Counter()
    saw_recording_sample = False
    previous_boot = previous_packet = previous_scan = previous_timestamp = previous_dropped = None
    configured_boot = None
    previous_transport_counters = {}
    with subprocess.Popen([str(executable), mode], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True, bufsize=1) as host:
        def exchange(command: str) -> dict:
            assert host.stdin is not None and host.stdout is not None
            host.stdin.write(command + "\n")
            host.stdin.flush()
            line = host.stdout.readline()
            if not line:
                raise ReplayError("host replay ended unexpectedly")
            return json.loads(line)

        def reset(reason: str, line: int, boot: int):
            nonlocal resets
            exchange("R")
            if parity:
                parity.unsync()
            resets += 1
            emit({"type": "replay_reset", "reason": reason, "source_line": line, "boot_id": boot})

        try:
            for number, record in records(path):
                try:
                    if capture_phase(record) == "startup":
                        if saw_recording_sample:
                            raise ReplayError("startup record after recording samples began")
                        startup_skipped[record["type"]] += 1
                        # A marker ACK may precede a few queued pre-boundary
                        # samples. Their explicit exclusion creates intentional
                        # packet-number holes before the first active sample.
                        previous_packet = None
                        continue
                    boot = integer(record, "boot_id")
                    packet = integer(record, "packet_seq")
                    if boot not in metadata:
                        raise ReplayError(f"missing metadata for boot {boot}")
                    reboot = previous_boot is not None and boot != previous_boot
                    if reboot:
                        reset("recorded_reboot", number, boot)
                        previous_packet = previous_scan = previous_timestamp = previous_dropped = None
                        previous_transport_counters.clear()
                        latest_result = None
                    if boot != configured_boot:
                        exchange(f"C {metadata[boot]['normalization']['charge_times']}")
                        configured_boot = boot
                    previous_boot = boot
                    reasons = []
                    # A lost final bundle has no later scan to reveal its gap.
                    # Cumulative counters in events/metadata expose that loss;
                    # counts already present on attachment are only a baseline.
                    for key in ("telemetry_dropped_samples", "telemetry_dropped_events", "transport_failures"):
                        if key not in record:
                            continue
                        value = integer(record, key)
                        before = previous_transport_counters.get(key)
                        if before is not None and value != before:
                            reasons.append(f"{key} changed {before}->{value}")
                        previous_transport_counters[key] = value
                    if previous_packet is not None and (packet - previous_packet) & U32_MAX != 1:
                        reasons.append(f"packet sequence {previous_packet}->{packet}")
                    previous_packet = packet
                    if record["type"] != "sample":
                        if reasons:
                            discontinuities += 1
                            if gap_policy == "error":
                                raise ReplayError("; ".join(reasons))
                            reset("; ".join(reasons), number, boot)
                        if record["type"] in ("marker", "device_event"):
                            emit(dict(record, source_line=number))
                        if record["type"] == "device_event":
                            if parity:
                                parity.event(record, latest_result, lambda: exchange("R"))
                            if record.get("event") == "processing_reset":
                                discontinuities += 1
                                if gap_policy == "error":
                                    raise ReplayError("device processing reset: " + str(record.get("reason")))
                                reset("device_processing_reset", number, boot)
                        continue
                    timestamp = integer(record, "timestamp_us", (1 << 64) - 1)
                    saw_recording_sample = True
                    scan = integer(record, "scan_seq")
                    dropped = integer(record, "dropped_scans")
                    integer(record, "snapshot_duration_us")
                    deltas, mask, invalid_reasons = sample_deltas(record)
                    if previous_scan is not None and (scan - previous_scan) & U32_MAX != 1:
                        reasons.append(f"scan sequence {previous_scan}->{scan}")
                    if previous_timestamp is not None and timestamp <= previous_timestamp:
                        reasons.append(f"non-increasing timestamp {previous_timestamp}->{timestamp}")
                    if previous_dropped is not None and dropped != previous_dropped:
                        reasons.append(f"dropped_scans changed {previous_dropped}->{dropped}")
                    if previous_dropped is None and dropped:
                        emit({"type": "replay_notice", "reason": "drops_before_first_observed_sample",
                              "boot_id": boot, "dropped_scans": dropped, "source_line": number})
                    previous_scan, previous_timestamp, previous_dropped = scan, timestamp, dropped
                    reasons.extend(invalid_reasons)
                    if reasons:
                        discontinuities += 1
                        emit({"type": "replay_discontinuity", "source_line": number,
                              "boot_id": boot, "reasons": reasons})
                        if gap_policy == "error":
                            raise ReplayError("; ".join(reasons))
                        reset("; ".join(reasons), number, boot)
                    if invalid_reasons:
                        invalid += 1
                        continue
                    result = exchange(" ".join(map(str, [
                        "S", number, timestamp & U32_MAX, mask, *deltas])))
                    result.update(timestamp_us=timestamp, scan_seq=scan, boot_id=boot,
                                  normalization_source=metadata[boot]["normalization"]["source"])
                    latest_result = result
                    if parity:
                        parity.sample(result)
                    emit(result)
                    count += 1
                    events += result["gesture"] is not None
                except ReplayError as exc:
                    raise ReplayError(f"line {number}: {exc}") from exc
        finally:
            assert host.stdin is not None
            host.stdin.close()
            # The host writes one short result per exchange, so no unread output
            # remains when closing a successful or failed replay.
            host.wait()
        if host.returncode:
            raise ReplayError(f"host replay exited {host.returncode}")
    summary = {"type": "replay_summary", "complete": True, "samples": count,
               "gesture_events": events, "detector_resets": resets,
               "discontinuities": discontinuities, "skipped_invalid_samples": invalid,
               "continuous": discontinuities == 0,
               "startup_records_skipped": sum(startup_skipped.values()),
               "startup_records_by_type": dict(startup_skipped)}
    if not count:
        raise ReplayError("capture contains no replayable sample frames")
    if startup_skipped:
        emit({"type": "replay_notice", "reason": "explicit_capture_startup_excluded",
              "records": sum(startup_skipped.values()), "by_type": dict(startup_skipped)})
    if parity:
        summary["device_parity"] = parity.summary()
        summary["device_parity"]["verified"] &= summary["continuous"]
    emit(summary)
    if parity and not summary["device_parity"]["verified"]:
        raise ReplayError("on-device replay verification failed; see device_parity in replay_summary")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Decoded frames.jsonl from a capture session")
    parser.add_argument("--mode", choices=("legacy", "pcb"), default="legacy")
    parser.add_argument("--gap-policy", choices=("error", "reset"), default="error",
                        help="Default stops on missing/invalid data; reset explicitly segments a damaged stream")
    parser.add_argument("--verify-device", action="store_true",
                        help="Require recorded device decisions to match after an idle checkpoint (pcb mode)")
    parser.add_argument("--output", type=Path, help="JSONL output (default: stdout); existing files are not overwritten")
    args = parser.parse_args()
    output = None
    try:
        # Validate provenance before invoking the compiler or creating output.
        capture_metadata(args.input)
        executable, source_hash = build_host()
        output = args.output.open("x", encoding="utf-8") if args.output else sys.stdout
        replay(args.input, args.mode, args.gap_policy,
               lambda record: print(json.dumps(record, separators=(",", ":"), allow_nan=False), file=output),
               executable, source_hash, verify_device=args.verify_device)
        return 0
    except (ReplayError, OSError, subprocess.SubprocessError) as exc:
        print(f"Replay failed: {exc}", file=sys.stderr)
        return 2
    finally:
        if output is not None and output is not sys.stdout:
            output.close()


if __name__ == "__main__":
    raise SystemExit(main())
