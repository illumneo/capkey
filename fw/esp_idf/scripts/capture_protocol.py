#!/usr/bin/env python3
"""Version 1 Swipe acquisition framing. No hardware or third-party dependencies."""
from __future__ import annotations

import json
import math
import struct
import zlib
from collections import Counter
from typing import Any

MAGIC = b"SWP1"
VERSION = 1
MAX_PAYLOAD = 4096
HEADER = struct.Struct("<4sBBHI")
CRC = struct.Struct("<I")
SAMPLE = struct.Struct("<QIIIIHHHH45I")
TYPE_METADATA = 1
TYPE_SAMPLE = 2
TYPE_MARKER = 3
TYPE_DEVICE_EVENT = 4
TYPE_HID_LOG = 5


def _validate_event(out: dict) -> None:
    if out.get("event") not in ("gesture", "processing_reset", "idle_checkpoint"):
        raise ValueError("Unknown device event")
    for key in ("boot_id", "event_seq", "scan_seq", "timestamp_us", "processing_epoch"):
        value = out.get(key)
        limit = 0xffffffffffffffff if key == "timestamp_us" else 0xffffffff
        if type(value) is not int or not 0 <= value <= limit:
            raise ValueError(f"Device event needs unsigned integer {key}")
    if out.get("model") != "pcb":
        raise ValueError("Device event needs model=pcb")
    for key in ("telemetry_dropped_samples", "telemetry_dropped_events", "transport_failures", "acq_dropped_scans"):
        if key in out and (type(out[key]) is not int or not 0 <= out[key] <= 0xffffffff):
            raise ValueError(f"Invalid device counter {key}")
    if out["event"] != "gesture":
        if not isinstance(out.get("reason"), str):
            raise ValueError("Device checkpoint/reset needs a reason")
        return
    for key in ("x", "y", "z", "start_x", "start_y", "max_distance"):
        try:
            finite = type(out.get(key)) in (int, float) and math.isfinite(out[key])
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError(f"Gesture needs finite {key}")
    for key, maximum in (("gesture_type", 7), ("direction", 8), ("grid_position", 15)):
        if type(out.get(key)) is not int or not 0 <= out[key] <= maximum:
            raise ValueError(f"Invalid gesture {key}")
    action = out.get("action")
    if not isinstance(action, dict) or action.get("type") not in ("none", "char", "string", "backspace", "special"):
        raise ValueError("Gesture needs a typed action")
    if (type(action.get("char_code")) is not int or not 0 <= action["char_code"] <= 255 or
            not isinstance(action.get("label"), str)):
        raise ValueError("Gesture needs action char_code and label")
    backend = out.get("output_backend")
    if backend == "log_only":
        if out.get("hid_sent") is not False or ("hid_queued" in out and out["hid_queued"] is not False):
            raise ValueError("Log-only events cannot queue or send HID output")
    elif backend == "usb_hid":
        queued = out.get("hid_queued")
        if type(queued) is not bool or "hid_sent" not in out:
            raise ValueError("USB HID events need boolean hid_queued and explicit hid_sent")
        sent = out["hid_sent"]
        # Recognition records queue acceptance, not eventual host delivery.
        # A future completion record may explicitly report true; null is pending.
        if ((queued and sent is not None and sent is not True) or
                (not queued and sent is not False)):
            raise ValueError("Inconsistent USB HID queued/sent state")
    else:
        raise ValueError("Unknown runtime output backend")


def _validate_hid_log(out: dict) -> None:
    def integer(key, maximum=0xffffffff):
        value = out.get(key)
        if type(value) is not int or not 0 <= value <= maximum:
            raise ValueError(f"HID log needs unsigned integer {key}")
    if not isinstance(out.get("token"), str) or not out["token"]:
        raise ValueError("HID log needs query token")
    integer("boot_id")
    if out.get("event") == "summary":
        for key in ("after_seq", "oldest_seq", "latest_seq", "overwritten",
                    "overwritten_at_end", "lost_before_query"):
            integer(key, 0xffffffffffffffff)
        for key in ("retained", "returned", "missing_during_query"):
            integer(key, 32)
        for key in ("hid_failed", "hid_queue_drops"):
            integer(key)
        if out.get("error") not in ("", "recording_active", "cursor_ahead"):
            raise ValueError("Unknown HID log query error")
        if out.get("hid_layout") != "US":
            raise ValueError("HID log needs US layout")
        identity = out.get("recognizer_sha256")
        if not isinstance(identity, str) or len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
            raise ValueError("HID log needs recognizer identity")
        for key in ("coherent_swipe_min_distance", "coherent_swipe_min_efficiency",
                    "coherent_swipe_min_end_ratio", "edge_swipe_min_distance"):
            value = out.get(key)
            if type(value) not in (int, float) or not 0 < value <= 4:
                raise ValueError(f"Invalid HID log policy bound {key}")
        if out.get("coherent_efficiency_basis") != "peak/path":
            raise ValueError("Unknown coherent swipe efficiency basis")
        if out["oldest_seq"] > out["latest_seq"] or out["overwritten_at_end"] < out["overwritten"]:
            raise ValueError("Inconsistent HID log bounds")
        return
    if out.get("event") != "completion" or out.get("source") not in ("physical", "diagnostic"):
        raise ValueError("Unknown HID log record")
    for key in ("completion_seq", "completed_us", "timestamp_us"):
        integer(key, 0xffffffffffffffff)
    if out["completion_seq"] == 0 or out["completed_us"] < out["timestamp_us"]:
        raise ValueError("Invalid HID completion identity/time")
    for key in ("usb_generation", "processing_epoch", "event_seq", "scan_seq", "diagnostic_id", "duration_us", "hid_failed", "hid_queue_drops"):
        integer(key)
    for key, maximum in (("grid", 15), ("gesture_type", 7), ("direction", 8)):
        integer(key, maximum)
    if out["source"] == "physical" and (out["event_seq"] == 0 or out["diagnostic_id"] != 0):
        raise ValueError("Physical completion needs a gesture event identity")
    if out["source"] == "diagnostic" and (out["event_seq"] != 0 or out["diagnostic_id"] == 0):
        raise ValueError("Diagnostic completion needs its diagnostic identity")
    for key in ("start_x", "start_y", "end_x", "end_y", "peak_dx", "peak_dy", "max_distance", "path_length"):
        value = out.get(key)
        try:
            finite = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError(f"HID log needs finite {key}")
    for key in ("caps_lock", "shift_before", "shift_after", "state_only"):
        if type(out.get(key)) is not bool:
            raise ValueError(f"HID log needs boolean {key}")
    presses = out.get("presses")
    if not isinstance(presses, list) or len(presses) > 31:
        raise ValueError("HID log press count exceeds fixed capacity")
    for press in presses:
        if (not isinstance(press, list) or len(press) != 7 or
                any(type(value) is not int or not 0 <= value <= 255 for value in press)):
            raise ValueError("HID log needs modifier plus six usages per press")
    if out["state_only"] != (len(presses) == 0):
        raise ValueError("Inconsistent state-only completion")


def _validate_hid_metadata(out: dict) -> None:
    # Optional for older captures; when present, preserve strict JSON types.
    for key in ("hid_enqueued", "hid_completed", "hid_failed", "hid_queue_drops",
                "hid_state_actions", "hid_queue_depth"):
        if key in out and (type(out[key]) is not int or not 0 <= out[key] <= 0xffffffff):
            raise ValueError(f"Invalid HID metadata counter {key}")
    for key in ("hid_mounted", "hid_suspended", "hid_shift_pending", "hid_enabled"):
        if key in out and type(out[key]) is not bool:
            raise ValueError(f"HID metadata needs boolean {key}")
    if "hid_layout" in out and out["hid_layout"] != "US":
        raise ValueError("Unknown HID keyboard layout")


def encode_packet(packet_type: int, payload: bytes | dict, packet_seq: int = 0) -> bytes:
    """Encode a reference packet; useful for fixtures and protocol conformance."""
    if isinstance(payload, dict):
        payload = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("Payload exceeds protocol limit")
    body = HEADER.pack(MAGIC, VERSION, packet_type, len(payload), packet_seq) + payload
    return body + CRC.pack(zlib.crc32(body))


def decode_payload(packet_type: int, payload: bytes, packet_seq: int) -> dict[str, Any]:
    if packet_type == TYPE_SAMPLE:
        if len(payload) != SAMPLE.size:
            raise ValueError(f"Sample length {len(payload)} != {SAMPLE.size}")
        v = SAMPLE.unpack(payload)
        keys = ("timestamp_us", "scan_seq", "dropped_scans", "snapshot_duration_us",
                "boot_id", "registered_mask", "raw_valid_mask", "smooth_valid_mask",
                "benchmark_valid_mask")
        out = dict(zip(keys, v[:9]))
        out.update(type="sample", raw=list(v[9:24]), smooth=list(v[24:39]),
                   benchmark=list(v[39:54]))
    elif packet_type in (TYPE_METADATA, TYPE_MARKER, TYPE_DEVICE_EVENT, TYPE_HID_LOG):
        def invalid_constant(value: str):
            raise ValueError(f"Invalid JSON numeric constant {value}")
        out = json.loads(payload.decode("utf-8"), parse_constant=invalid_constant)
        if not isinstance(out, dict):
            raise ValueError("JSON record must be an object")
        out["type"] = {TYPE_METADATA: "metadata", TYPE_MARKER: "marker", TYPE_DEVICE_EVENT: "device_event", TYPE_HID_LOG: "hid_log"}[packet_type]
        if packet_type == TYPE_DEVICE_EVENT:
            _validate_event(out)
        if packet_type == TYPE_HID_LOG:
            _validate_hid_log(out)
        if packet_type == TYPE_METADATA:
            _validate_hid_metadata(out)
        if packet_type == TYPE_MARKER:
            if not isinstance(out.get("token"), str):
                raise ValueError("Marker needs a string token")
            if "hid_accepted" in out and type(out["hid_accepted"]) is not bool:
                raise ValueError("HID acknowledgement needs boolean hid_accepted")
            for key in ("device_us", "scan_seq", "boot_id"):
                if not isinstance(out.get(key), int) or isinstance(out[key], bool) or out[key] < 0:
                    raise ValueError(f"Marker needs a nonnegative integer {key}")
    else:
        raise ValueError(f"Unknown packet type {packet_type}")
    out["packet_seq"] = packet_seq
    return out


class StreamDecoder:
    """Incremental decoder which accounts for corrupt, ignored and partial bytes."""
    def __init__(self):
        self.buffer = bytearray()
        self.counters = Counter({key: 0 for key in (
            "bytes_received", "packets_decoded", "skipped_bytes", "startup_skipped_bytes",
            "stream_skipped_bytes", "crc_errors",
            "version_errors", "length_errors", "payload_errors", "unknown_types",
            "trailing_bytes")})

    def _skip(self, count: int):
        self.counters["skipped_bytes"] += count
        category = "stream_skipped_bytes" if self.counters["packets_decoded"] else "startup_skipped_bytes"
        self.counters[category] += count
        del self.buffer[:count]

    def feed(self, chunk: bytes, on_record=None) -> list[dict[str, Any]]:
        self.counters["bytes_received"] += len(chunk)
        self.buffer.extend(chunk)
        records = []
        while self.buffer:
            pos = self.buffer.find(MAGIC)
            if pos < 0:
                # Keep only a suffix which may be the beginning of the next magic.
                keep = next((n for n in range(min(3, len(self.buffer)), 0, -1)
                             if self.buffer[-n:] == MAGIC[:n]), 0)
                self._skip(len(self.buffer) - keep)
                break
            if pos:
                self._skip(pos)
            if len(self.buffer) < HEADER.size:
                break
            _, version, packet_type, size, sequence = HEADER.unpack_from(self.buffer)
            if version != VERSION:
                self.counters["version_errors"] += 1
                self._skip(1)
                continue
            if size > MAX_PAYLOAD or (packet_type == TYPE_SAMPLE and size != SAMPLE.size):
                self.counters["length_errors"] += 1
                self._skip(1)
                continue
            total = HEADER.size + size + CRC.size
            if len(self.buffer) < total:
                # A corrupted length can otherwise swallow later valid frames.
                # Only resynchronize early if a *complete CRC-valid* candidate exists.
                next_pos = self.buffer.find(MAGIC, 1)
                found = False
                while next_pos >= 0 and len(self.buffer) - next_pos >= HEADER.size:
                    _, nv, nt, ns, _ = HEADER.unpack_from(self.buffer, next_pos)
                    end = next_pos + HEADER.size + ns
                    if (nv == VERSION and ns <= MAX_PAYLOAD and
                            (nt != TYPE_SAMPLE or ns == SAMPLE.size) and
                            len(self.buffer) >= end + CRC.size and
                            zlib.crc32(self.buffer[next_pos:end]) == CRC.unpack_from(self.buffer, end)[0]):
                        self.counters["length_errors"] += 1
                        self._skip(next_pos)
                        found = True
                        break
                    next_pos = self.buffer.find(MAGIC, next_pos + 1)
                if found:
                    continue
                break
            body = self.buffer[:HEADER.size + size]
            expected = CRC.unpack_from(self.buffer, HEADER.size + size)[0]
            if zlib.crc32(body) != expected:
                self.counters["crc_errors"] += 1
                self._skip(1)
                continue
            payload = bytes(self.buffer[HEADER.size:HEADER.size + size])
            del self.buffer[:total]
            try:
                record = decode_payload(packet_type, payload, sequence)
            except (ValueError, UnicodeError, struct.error):
                self.counters["unknown_types" if packet_type not in (1, 2, 3, 4, 5) else "payload_errors"] += 1
                self.counters["skipped_bytes"] += total
                category = "stream_skipped_bytes" if self.counters["packets_decoded"] else "startup_skipped_bytes"
                self.counters[category] += total
                continue
            self.counters["packets_decoded"] += 1
            records.append(record)
            if on_record is not None:
                on_record(record)
        return records

    def finish(self) -> None:
        self.counters["trailing_bytes"] += len(self.buffer)
        self.buffer.clear()

    def status(self) -> dict:
        return dict(self.counters, buffered_bytes=len(self.buffer))


class CaptureQuality:
    """Continuity diagnostics, not a claim that the sensor samples are accurate."""
    def __init__(self):
        self.counts = Counter({k: 0 for k in (
            "samples", "metadata_records", "marker_records", "packet_gaps",
            "packet_duplicates", "packet_regressions", "scan_gaps", "scan_duplicates",
            "scan_regressions", "timestamp_regressions", "boot_changes",
            "device_dropped_scans", "initial_device_dropped_scans", "invalid_raw_samples", "invalid_smooth_samples",
            "invalid_benchmark_samples", "pad0_valid_samples", "zero_registered_samples",
            "dropped_counter_regressions", "missing_required_pad_samples",
            "device_event_records", "gesture_events", "processing_resets", "idle_checkpoints",
            "event_gaps", "event_duplicates", "event_regressions", "event_timestamp_regressions",
            "telemetry_dropped_samples", "telemetry_dropped_events", "transport_failures",
            "telemetry_counter_regressions")})
        self.boot_ids: list[int] = []
        self.required_pad_mask = 0x1ffe
        self.initial_dropped_by_boot: dict[str, int] = {}
        self.boot_id = None
        self.last_packet = None
        self.last_scan = None
        self.last_timestamp = None
        self.last_dropped = None
        self.first_timestamp = None
        self.last_sample_timestamp = None
        self.last_event = self.last_event_timestamp = None
        self.telemetry_counters = {}
        self.initial_telemetry_counters = {}
        self.intervals_us: list[int] = []

    @staticmethod
    def _delta(current: int, previous: int) -> int:
        return (current - previous) & 0xffffffff

    def observe(self, record: dict) -> None:
        boot = record.get("boot_id")
        changed = boot is not None and self.boot_id is not None and boot != self.boot_id
        if boot is not None and boot != self.boot_id:
            if changed:
                self.counts["boot_changes"] += 1
                self.last_packet = self.last_scan = self.last_timestamp = self.last_dropped = None
                self.last_event = self.last_event_timestamp = None
                self.telemetry_counters = {}
            self.boot_id = boot
            if boot not in self.boot_ids:
                self.boot_ids.append(boot)
        seq = record["packet_seq"]
        if self.last_packet is not None:
            delta = self._delta(seq, self.last_packet)
            if delta == 0:
                self.counts["packet_duplicates"] += 1
            elif delta >= 0x80000000:
                self.counts["packet_regressions"] += 1
            else:
                self.counts["packet_gaps"] += delta - 1
        self.last_packet = seq
        kind = record["type"]
        # These counters are sampled at serialization by the sole device writer,
        # not at acquisition. They must therefore be monotonic in wire order even
        # when metadata is interleaved with queued old samples/events.
        for key in ("telemetry_dropped_samples", "telemetry_dropped_events", "transport_failures"):
            value = record.get(key)
            if type(value) is not int or not 0 <= value <= 0xffffffff:
                continue
            if key not in self.telemetry_counters:
                self.initial_telemetry_counters.setdefault(str(boot), {})[key] = value
            else:
                delta = self._delta(value, self.telemetry_counters[key])
                if delta >= 0x80000000:
                    self.counts["telemetry_counter_regressions"] += 1
                else:
                    self.counts[key] += delta
            self.telemetry_counters[key] = value
        if kind == "device_event":
            self.counts["device_event_records"] += 1
            self.counts[{"gesture": "gesture_events", "processing_reset": "processing_resets",
                         "idle_checkpoint": "idle_checkpoints"}[record["event"]]] += 1
            if self.last_event is not None:
                delta = self._delta(record["event_seq"], self.last_event)
                if delta == 0:
                    self.counts["event_duplicates"] += 1
                elif delta >= 0x80000000:
                    self.counts["event_regressions"] += 1
                else:
                    self.counts["event_gaps"] += delta - 1
            if self.last_event_timestamp is not None and record["timestamp_us"] < self.last_event_timestamp:
                self.counts["event_timestamp_regressions"] += 1
            self.last_event = record["event_seq"]
            self.last_event_timestamp = record["timestamp_us"]
            return
        if kind != "sample":
            if kind == "metadata" and isinstance(record.get("board_pad_mask"), int):
                self.required_pad_mask = record["board_pad_mask"]
            self.counts["metadata_records" if kind == "metadata" else "marker_records"] += 1
            return
        self.counts["samples"] += 1
        scan, timestamp, dropped = record["scan_seq"], record["timestamp_us"], record["dropped_scans"]
        if self.last_scan is not None:
            delta = self._delta(scan, self.last_scan)
            if delta == 0:
                self.counts["scan_duplicates"] += 1
            elif delta >= 0x80000000:
                self.counts["scan_regressions"] += 1
            else:
                self.counts["scan_gaps"] += delta - 1
        if self.last_timestamp is not None:
            interval = timestamp - self.last_timestamp
            if interval <= 0:
                self.counts["timestamp_regressions"] += 1
            else:
                # Histogram summaries can be recomputed from frames.jsonl; keep memory bounded.
                if len(self.intervals_us) < 100000:
                    self.intervals_us.append(interval)
        if self.first_timestamp is None:
            self.first_timestamp = timestamp
        if self.last_dropped is None:
            self.counts["initial_device_dropped_scans"] += dropped
            self.initial_dropped_by_boot[str(record["boot_id"])] = dropped
        else:
            delta = self._delta(dropped, self.last_dropped)
            if delta < 0x80000000:
                self.counts["device_dropped_scans"] += delta
            else:
                self.counts["dropped_counter_regressions"] += 1
        self.last_scan, self.last_timestamp, self.last_dropped = scan, timestamp, dropped
        self.last_sample_timestamp = timestamp
        mask = record["registered_mask"]
        if not mask:
            self.counts["zero_registered_samples"] += 1
        if mask & self.required_pad_mask != self.required_pad_mask:
            self.counts["missing_required_pad_samples"] += 1
        for field in ("raw", "smooth", "benchmark"):
            valid = record[field + "_valid_mask"]
            if valid & mask != mask:
                self.counts["invalid_" + field + "_samples"] += 1
        if (mask | record["raw_valid_mask"] | record["smooth_valid_mask"] |
                record["benchmark_valid_mask"]) & 1:
            self.counts["pad0_valid_samples"] += 1

    def status(self) -> dict:
        intervals = sorted(self.intervals_us)
        median = intervals[len(intervals) // 2] if intervals else None
        return dict(self.counts, boot_ids=list(self.boot_ids),
                    required_pad_mask=self.required_pad_mask,
                    initial_device_dropped_scans_by_boot=dict(self.initial_dropped_by_boot),
                    initial_telemetry_counters_by_boot=self.initial_telemetry_counters,
                    missing_metadata=self.counts["metadata_records"] == 0,
                    first_device_timestamp_us=self.first_timestamp,
                    last_device_timestamp_us=self.last_sample_timestamp,
                    interval_count=len(intervals), median_interval_us=median,
                    max_interval_us=max(intervals) if intervals else None,
                    measured_hz=1e6 / median if median else None)
