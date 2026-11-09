#!/usr/bin/env python3
"""Loss-accounted serial acquisition, used by the guided UI and bounded CLI.

This module imports pyserial only when a real capture starts. Importing it never
opens hardware. Session directories are exclusive and never overwritten.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import queue
import re
import threading
import time
import uuid
from pathlib import Path

from capture_protocol import CaptureQuality, StreamDecoder

TOKEN = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")


class _StopMetadataReceived(Exception):
    """Internal decoder boundary: subsequent bytes are outside this recording."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class CaptureSession:
    def __init__(self, serial_factory=None):
        self._serial_factory = serial_factory
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._commands = queue.Queue()
        self._thread = None
        self._serial = None
        self._wire = self._frames = self._command_log = None
        self._path = None
        self._started_monotonic = None
        self._stopped_monotonic = None
        self._last_sample_monotonic = None
        self._decoder = StreamDecoder()
        self._quality = CaptureQuality()
        self._decoder_baseline = None
        self._handshake_deadline = None
        self._state = {
            "running": False, "ready": False, "session_dir": None, "samples": 0,
            "startup_records": 0, "startup_samples": 0, "capture_start_ack": None,
            "startup_device_events": 0, "device_events": 0,
            "latest_device_event": None, "stop_metadata_received": False,
            "capture_start_token": None,
            "latest_sample": None, "latest_metadata": None,
            "marker_acks": {}, "marker_pending": {}, "errors": [],
            "started_at": None, "stopped_at": None,
        }

    def start(self, port: str, session_dir: str | Path, metadata=None) -> dict:
        """Start once; preserves a failed session's artifacts and records errors."""
        with self._lock:
            if self._path is not None:
                raise RuntimeError("A CaptureSession instance can only be started once")
            user_metadata = {} if metadata is None else copy.deepcopy(metadata)
            json.dumps(user_metadata, allow_nan=False)  # fail before filesystem/device side effects
            path = Path(session_dir).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.mkdir(exist_ok=False)
            self._path = path
            self._started_monotonic = time.monotonic()
            self._state.update(session_dir=str(path), started_at=utc_now(), port=port,
                               metadata=user_metadata, protocol="SWP1-v1",
                               serial_settings={"baudrate": 115200, "dtr": True, "rts": False,
                                                "timeout_seconds": 0.1},
                               artifacts={"wire": "wire.bin", "frames": "frames.jsonl",
                                          "commands": "commands.jsonl"})
            try:
                self._wire = (path / "wire.bin").open("xb")
                self._frames = (path / "frames.jsonl").open("x", encoding="utf-8")
                self._command_log = (path / "commands.jsonl").open("x", encoding="utf-8")
                factory = self._serial_factory
                if factory is None:
                    import serial
                    factory = serial.Serial
                self._serial = factory(port=None, baudrate=115200, timeout=0.1,
                                       write_timeout=1, exclusive=True)
                self._serial.dtr = True
                self._serial.rts = False
                self._serial.port = port
                self._serial.open()
                self._state["running"] = True
                self._commands.put(("HELLO", None))
                self._state["capture_start_token"] = "capture-start-" + uuid.uuid4().hex
                self._handshake_deadline = time.monotonic() + 5
                self.mark(self._state["capture_start_token"])
                self._persist()
                self._thread = threading.Thread(target=self._run, name="swipe-capture", daemon=True)
                self._thread.start()
            except Exception as exc:
                self._state["errors"].append(f"Capture start failed: {type(exc).__name__}: {exc}")
                self._state["running"] = False
                self._state["stopped_at"] = utc_now()
                self._stopped_monotonic = time.monotonic()
                self._close_resources()
                self._persist()
                raise
        return self.status()

    def mark(self, token: str) -> str:
        """Queue MARK; the UI must wait for marker_acks before timing a phase."""
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise ValueError("Marker token must be 1–80 letters, digits, underscores, dots or hyphens")
        with self._lock:
            if not self._state["running"] or self._stop.is_set():
                raise RuntimeError("Capture is not running")
            if token in self._state["marker_pending"] or token in self._state["marker_acks"]:
                raise ValueError(f"Marker token already used: {token}")
            self._state["marker_pending"][token] = {"requested_at": utc_now(),
                                                     "host_monotonic_ns": time.monotonic_ns()}
            self._commands.put(("MARK " + token, token))
        return token

    def wait_for_marker(self, token: str, timeout: float = 2) -> dict:
        deadline = time.monotonic() + timeout
        with self._condition:
            while token not in self._state["marker_acks"]:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"No device acknowledgement for marker {token}")
                if not self._state["running"]:
                    raise RuntimeError(f"Capture stopped before marker {token} was acknowledged")
                self._condition.wait(remaining)
            return copy.deepcopy(self._state["marker_acks"][token])

    def _run(self):
        last_persist = time.monotonic()
        try:
            while not self._stop.is_set():
                while True:
                    try:
                        command, token = self._commands.get_nowait()
                    except queue.Empty:
                        break
                    request = {"command": command, "sent_at": utc_now(),
                               "host_monotonic_ns": time.monotonic_ns()}
                    self._command_log.write(json.dumps(request, separators=(",", ":")) + "\n")
                    self._command_log.flush()
                    message = (command + "\n").encode("ascii")
                    count = self._serial.write(message)
                    if count != len(message):
                        raise IOError(f"Incomplete command write ({count}/{len(message)} bytes)")
                chunk = self._serial.read(4096)
                if chunk:
                    # Archive before decoding, including corruption and console text.
                    self._wire.write(chunk)
                    self._wire.flush()
                    with self._condition:
                        self._decoder.feed(chunk, self._accept_record)
                        self._frames.flush()
                        self._condition.notify_all()
                now = time.monotonic()
                if not self._state["ready"] and now >= self._handshake_deadline:
                    raise TimeoutError("Capture synchronization timed out: firmware metadata and start MARK acknowledgement required within 5 seconds")
                if now - last_persist >= 1:
                    self._persist()
                    last_persist = now
        except Exception as exc:
            with self._lock:
                self._state["errors"].append(f"Capture failed: {type(exc).__name__}: {exc}")
        finally:
            with self._condition:
                if self._send_stop_best_effort():
                    self._drain_stop_metadata()
                self._decoder.finish()
                self._state["running"] = False
                self._state["ready"] = False
                self._state["stopped_at"] = utc_now()
                self._stopped_monotonic = time.monotonic()
                self._close_resources()
                try:
                    self._persist()
                except OSError as exc:
                    self._state["errors"].append(f"Cannot save final session report: {exc}")
                self._condition.notify_all()

    def _accept_record(self, record: dict):
        """Called at the exact decoder boundary, before parsing later packet bytes."""
        kind = record["type"]
        boundary = self._state["capture_start_ack"]
        own_ack = kind == "marker" and record["token"] == self._state["capture_start_token"]
        failure = None
        if kind == "metadata":
            self._state["latest_metadata"] = record
        if own_ack and boundary is None:
            metadata = self._state["latest_metadata"]
            if metadata is None or metadata.get("boot_id") != record["boot_id"]:
                failure = "Start MARK acknowledgement has no matching firmware metadata"
            else:
                boundary = record
                self._state["capture_start_ack"] = record
                self._state["ready"] = True
                self._quality = CaptureQuality()
                self._quality.observe(metadata)
                self._quality.last_packet = None
                self._decoder_baseline = self._decoder.status()
        eligible = boundary is not None and failure is None
        if eligible and record.get("boot_id") != boundary["boot_id"]:
            eligible = False
            failure = "Firmware boot changed after synchronized capture start"
        if eligible and kind in ("sample", "device_event") and record["timestamp_us"] < boundary["device_us"]:
            eligible = False
            if self._state["samples"] or self._state["device_events"]:
                failure = f"Stale pre-start {kind} appeared after recording samples/events"
        record["capture_phase"] = "recording" if eligible else "startup"
        self._frames.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")
        if kind == "marker":
            self._state["marker_acks"][record["token"]] = record
            self._state["marker_pending"].pop(record["token"], None)
        if eligible:
            self._quality.observe(record)
            if kind == "sample":
                self._state["samples"] += 1
                self._state["latest_sample"] = record
                self._last_sample_monotonic = time.monotonic()
            elif kind == "device_event":
                self._state["device_events"] += 1
                self._state["latest_device_event"] = record
        else:
            self._state["startup_records"] += 1
            if kind == "sample":
                self._state["startup_samples"] += 1
            elif kind == "device_event":
                self._state["startup_device_events"] += 1
            if boundary is not None and not self._state["samples"] and not self._state["device_events"]:
                # The firmware may still drain old queued samples after sending ACK.
                # Their deliberate exclusion must not manufacture packet loss.
                self._quality.last_packet = None
        if failure:
            self._frames.flush()
            raise RuntimeError(failure)

    def _send_stop_best_effort(self):
        if self._serial is None:
            return False
        try:
            self._command_log.write(json.dumps({"command": "STOP", "sent_at": utc_now(),
                                                "host_monotonic_ns": time.monotonic_ns()}) + "\n")
            self._command_log.flush()
            if self._serial.write(b"STOP\n") != 5:
                raise IOError("Incomplete STOP write")
            return True
        except Exception as exc:
            self._state["stop_command_error"] = str(exc)
            if (self._state["latest_metadata"] or {}).get("event_protocol_version") == 1:
                self._state["errors"].append(f"STOP command failed; final telemetry counters unverified: {exc}")
            return False

    def _drain_stop_metadata(self):
        """Bounded final-counter drain; older diagnostic firmware has no STOP ACK."""
        runtime_protocol = (self._state["latest_metadata"] or {}).get("event_protocol_version") == 1
        if not runtime_protocol:
            return
        deadline = time.monotonic() + 1.0

        def accept(record):
            self._accept_record(record)
            if record["type"] == "metadata" and record.get("streaming") is False:
                self._state["stop_metadata_received"] = True
                raise _StopMetadataReceived()

        try:
            while time.monotonic() < deadline:
                chunk = self._serial.read(4096)
                if chunk:
                    self._wire.write(chunk)
                    self._wire.flush()
                    self._decoder.feed(chunk, accept)
        except _StopMetadataReceived:
            return
        except Exception as exc:
            self._state["errors"].append(f"Final telemetry drain failed: {type(exc).__name__}: {exc}")
            return
        finally:
            self._frames.flush()
        self._state["errors"].append("Final streaming=false metadata not received within 1 second; tail loss counters unverified")

    def _close_resources(self):
        for name in ("_serial", "_wire", "_frames", "_command_log"):
            resource = getattr(self, name)
            if resource is not None:
                try:
                    resource.close()
                except Exception as exc:
                    self._state["errors"].append(f"Closing {name} failed: {exc}")
                setattr(self, name, None)

    def _persist(self):
        with self._lock:
            if self._path is None:
                return
            temporary = self._path / "session.json.tmp"
            temporary.write_text(json.dumps(self.status(), indent=2, allow_nan=False) + "\n", encoding="utf-8")
            temporary.replace(self._path / "session.json")

    def status(self) -> dict:
        with self._lock:
            state = copy.deepcopy(self._state)
            quality = self._quality.status()
            totals = self._decoder.status()
            quality["decoder_total"] = totals
            quality["decoder"] = {key: (value if key == "buffered_bytes" else value - (self._decoder_baseline or {}).get(key, 0))
                                  for key, value in totals.items()}
            quality["missing_metadata"] = state["latest_metadata"] is None
            quality["unacknowledged_markers"] = sorted(state["marker_pending"])
            end_time = self._stopped_monotonic or time.monotonic()
            state["elapsed_seconds"] = end_time - self._started_monotonic if self._started_monotonic is not None else 0
            state["seconds_since_last_sample"] = end_time - self._last_sample_monotonic if self._last_sample_monotonic is not None else None
            problems = []
            if state["capture_start_ack"] is None:
                problems.append("No synchronized capture start acknowledgement")
            if quality["missing_metadata"]:
                problems.append("No firmware metadata received")
            if not state["samples"]:
                problems.append("No acquisition samples received")
            elif state["seconds_since_last_sample"] > 1:
                problems.append(f"No acquisition sample received for {state['seconds_since_last_sample']:.2f} seconds")
            for name in ("packet_gaps", "packet_duplicates", "packet_regressions", "scan_gaps",
                         "scan_duplicates", "scan_regressions", "timestamp_regressions",
                         "boot_changes", "device_dropped_scans", "invalid_raw_samples",
                         "invalid_smooth_samples", "invalid_benchmark_samples", "pad0_valid_samples",
                         "zero_registered_samples", "dropped_counter_regressions", "missing_required_pad_samples",
                         "event_gaps", "event_duplicates", "event_regressions", "event_timestamp_regressions",
                         "processing_resets", "telemetry_dropped_samples", "telemetry_dropped_events",
                         "transport_failures", "telemetry_counter_regressions"):
                if quality[name]:
                    problems.append(f"{name}: {quality[name]}")
            # Startup console/partial frame and an unfinished packet at stop are
            # preserved and counted, but do not invalidate complete acquired frames.
            for name in ("stream_skipped_bytes", "crc_errors", "version_errors", "length_errors",
                         "payload_errors", "unknown_types"):
                if quality["decoder"][name]:
                    problems.append(f"decoder {name}: {quality['decoder'][name]}")
            if quality["unacknowledged_markers"]:
                problems.append("Unacknowledged markers: " + ", ".join(quality["unacknowledged_markers"]))
            problems.extend(state["errors"])
            quality["issues"] = problems
            quality["clean"] = not problems
            state["quality"] = quality
            return state

    def stop(self) -> dict:
        self._stop.set()
        serial_port = self._serial
        if serial_port is not None:
            try:
                serial_port.cancel_read()
            except (AttributeError, OSError):
                pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(3)
            if thread.is_alive():
                # A broken driver must not keep an apparently successful capture alive.
                if serial_port is not None:
                    serial_port.close()
                thread.join(2)
                if thread.is_alive():
                    with self._lock:
                        self._state["errors"].append("Capture thread failed to stop after serial close")
                    raise RuntimeError("Capture thread failed to stop")
        return self.status()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--session-dir", required=True, type=Path)
    parser.add_argument("--duration", required=True, type=float, help="Maximum recording time in seconds")
    parser.add_argument("--metadata", type=Path, help="Optional JSON object describing capture conditions")
    args = parser.parse_args()
    if not 0 < args.duration <= 24 * 60 * 60:
        parser.error("--duration must be greater than zero and at most 86400 seconds")
    metadata = json.loads(args.metadata.read_text()) if args.metadata else {}
    session = CaptureSession()
    try:
        session.start(args.port, args.session_dir, metadata)
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline and session.status()["running"]:
            time.sleep(min(0.2, max(0, deadline - time.monotonic())))
    except KeyboardInterrupt:
        pass
    finally:
        report = session.stop()
    print(json.dumps({"session_dir": report["session_dir"], "samples": report["samples"],
                      "quality": report["quality"]}, indent=2))
    return 0 if report["quality"]["clean"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
