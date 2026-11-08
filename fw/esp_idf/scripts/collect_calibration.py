#!/usr/bin/env python3
"""Guided, loopback-only collection of labeled Swipe recordings.

The prompts are ground-truth *intent*, never inferred from sensor detections.
Interrupted and unacknowledged trials remain in the append-only journal. Resume
retries an interrupted target with a new trial ID. Capture continues while paused.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import random
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


KEYS = ("a", "n", "i", None, "h", "o", "r", "<SHIFT>",
        "t", "e", "s", "<BACKSPACE>", "<SPACE>", "<SPACE>", "<SPACE>", "<ENTER>")
PHASES = ("pre_idle", "contact", "post_idle")
UI_DIR = Path(__file__).with_name("calibration_ui")


def target_for_cell(index: int) -> dict:
    row, col = divmod(index, 4)
    return {"id": f"R{row + 1}C{col + 1}", "row": row + 1, "col": col + 1,
            "x_mm": 6.25 + 12.5 * col, "y_mm": 6.25 + 12.5 * row,
            "key": KEYS[index]}


def make_plan(block: str, seed: int = 42, pre_idle: float = 1,
              contact: float = 2, post_idle: float = 1) -> list[dict]:
    """Seeded intent plan. Validation is a separate fourth randomized pass."""
    durations = dict(zip(PHASES, (pre_idle, contact, post_idle)))
    if any(not math.isfinite(x) or x < 0.1 or x > 30 for x in durations.values()):
        raise ValueError("Phase durations must be between 0.1 and 30 seconds")
    if block == "positions":
        rng = random.Random(seed)
        trials = []
        for pass_index in range(4):
            cells = list(range(16))
            rng.shuffle(cells)
            for index in cells:
                target = target_for_cell(index)
                trials.append({"target": target, "expected_gesture": "hold",
                               "expected_key": None,
                               "intended_action": "stationary_contact",
                               "prompt": f"Touch and hold the center of {target['id']} until RELEASE.",
                               "split": "validation" if pass_index == 3 else "training",
                               "pass_index": pass_index + 1, "durations": durations.copy()})
        return trials
    if block != "pilot":
        raise ValueError("Block must be pilot or positions")
    trials = [{"target": None, "expected_gesture": "none", "expected_key": None,
               "intended_action": "hands_away", "prompt": "Keep both hands away from the board.",
               "durations": {"pre_idle": 0, "contact": 8, "post_idle": 0}}]
    for index in (0, 3, 15, 12):
        target = target_for_cell(index)
        trials.append({"target": target, "expected_gesture": "hold", "expected_key": None,
                       "intended_action": "stationary_contact",
                       "prompt": f"Touch and hold the center of {target['id']} until RELEASE.",
                       "durations": {"pre_idle": 1, "contact": 3, "post_idle": 1}})
    center = {"id": "CENTER", "row": None, "col": None, "x_mm": 25, "y_mm": 25, "key": None}
    trials.append({"target": center, "expected_gesture": "hold", "expected_key": None,
                   "intended_action": "stationary_contact", "prompt": "Hold the physical center of the board.",
                   "durations": {"pre_idle": 1, "contact": 4, "post_idle": 1}})
    for axis, direction, start, end in (("horizontal", "east", [6.25, 25], [43.75, 25]),
                                      ("vertical", "south", [25, 6.25], [25, 43.75])):
        target = {"id": axis.upper(), "row": None, "col": None, "x_mm": start[0], "y_mm": start[1],
                  "end_x_mm": end[0], "end_y_mm": end[1], "key": None}
        trials.append({"target": target, "expected_gesture": "swipe", "expected_key": None,
                       "intended_action": "continuous_traversal", "expected_direction": direction,
                       "prompt": f"Slowly trace the {axis} arrow across the board; release at the end.",
                       "durations": {"pre_idle": 1, "contact": 5, "post_idle": 1}})
    for trial in trials:
        trial.update(split="pilot", pass_index=1)
    return trials


class SyntheticSerial:
    """Deterministic wire fixture. Deliberately not responsive to UI touch cues."""
    def __init__(self, *args, **kwargs):
        from capture_protocol import encode_packet, TYPE_METADATA
        self.closed = False
        self.dtr = self.rts = False
        self.lock = threading.Lock()
        self.buffer = bytearray()
        self.next_sample = time.monotonic()
        self.seq = self.scan = 0
        self.metadata = {"protocol_version": 1, "boot_id": 0x53594E54,
                         "synthetic": True, "firmware": "SYNTHETIC UI TEST — NOT PHYSICAL DATA",
                         "project": "swipe-synthetic-fixture", "mode": "synthetic_diagnostic",
                         "board": "capkey_6x6_50mm", "board_is_simulated": True,
                         "app_version": "synthetic-v1", "idf_version": "not_applicable",
                         "elf_sha256": None, "sdkconfig_sha256": None,
                         "provenance": {"kind": "synthetic_serial_fixture",
                                        "generator": "collect_calibration.py:SyntheticSerial",
                                        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                        "firmware_artifacts": "not_applicable; no hardware or firmware binary"},
                         "channel_ids": list(range(1, 15)), "pad_ids": list(range(15)),
                         "registered_mask": 0x7ffe, "board_pad_mask": 0x1ffe, "capture_decimation": 1,
                         "acquisition": {"charge_times": 800},
                         "sample_period_us": 20000}
        self.buffer.extend(encode_packet(TYPE_METADATA, self.metadata, self.seq))
        self.seq += 1

    @property
    def in_waiting(self):
        return len(self.buffer)

    def read(self, size=4096):
        from capture_protocol import encode_packet, SAMPLE, TYPE_SAMPLE
        if self.closed:
            return b""
        with self.lock:
            now = time.monotonic()
            if now >= self.next_sample:
                self.scan += 1
                self.next_sample = now + 0.02
                baseline = [0] + [50000 + pad * 300 for pad in range(1, 15)]
                raw = [0] + [value + ((self.scan + pad) % 7) - 3
                             for pad, value in enumerate(baseline[1:], 1)]
                payload = SAMPLE.pack(self.scan * 20000, self.scan, 0, 80, 0x53594E54,
                                      0x7ffe, 0x7ffe, 0x7ffe, 0x7ffe,
                                      *raw, *raw, *baseline)
                self.buffer.extend(encode_packet(TYPE_SAMPLE, payload, self.seq))
                self.seq += 1
            if self.buffer:
                result = bytes(self.buffer[:size])
                del self.buffer[:size]
                return result
        time.sleep(0.005)
        return b""

    def write(self, data):
        from capture_protocol import encode_packet, TYPE_METADATA, TYPE_MARKER
        with self.lock:
            for line in data.decode("ascii").splitlines():
                if line.startswith("MARK "):
                    record = {"token": line[5:].strip(), "device_us": self.scan * 20000,
                              "scan_seq": self.scan, "boot_id": 0x53594E54, "synthetic": True}
                    self.buffer.extend(encode_packet(TYPE_MARKER, record, self.seq))
                    self.seq += 1
                elif line.strip() in ("META", "INFO", "HELLO"):
                    self.buffer.extend(encode_packet(TYPE_METADATA, self.metadata, self.seq))
                    self.seq += 1
        return len(data)

    def flush(self):
        pass

    def open(self):
        self.closed = False

    def close(self):
        self.closed = True


class Collector:
    """Single scheduler owns phase transitions; HTTP calls enqueue user commands."""
    def __init__(self, capture, session_dir: Path, *, synthetic=False, marker_timeout=2.5,
                 stale_timeout=2.5, clock=time.monotonic, start_worker=True):
        self.capture = capture
        self.session_dir = Path(session_dir)
        self.synthetic = synthetic
        self.clock = clock
        self.marker_timeout = marker_timeout
        self.stale_timeout = stale_timeout
        self.lock = threading.RLock()
        self.commands = queue.Queue()
        self.closed = threading.Event()
        self.journal = (self.session_dir / "trials.jsonl").open("x", encoding="utf-8", buffering=1)
        self.state = "idle"
        self.reason = "Choose the pilot, enter the setup details, then start."
        self.error = None
        self.environment = None
        self.plan = []
        self.index = 0
        self.block_id = None
        self.block = None
        self.block_number = self.trial_number = self.marker_number = 0
        self.current = None
        self.previous = None
        self.phase = None
        self.phase_end = None
        self.generation = 0
        self.pending = {}
        self.last_sample_count = 0
        self.last_sample_seen = self.clock()
        self.last_ui_seen = None
        self.last_quality = None
        self.capture_status = self.capture.status()
        self._write("collector_open", synthetic=synthetic, board_size_mm=[50, 50],
                    orientation="CapKey upright; row 1 at top, column 1 at left",
                    labels_are="user intent; phase windows are not exact contact timestamps")
        self.worker = None
        if start_worker:
            self.worker = threading.Thread(target=self._work, name="calibration-cues", daemon=True)
            self.worker.start()

    def _write(self, event, **fields):
        record = {"event": event, "host_time_ns": time.time_ns(),
                  "host_monotonic_ns": int(self.clock() * 1e9), "synthetic": self.synthetic, **fields}
        self.journal.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")

    def _ready(self):
        s = self.capture_status
        sample = s.get("latest_sample") or {}
        metadata = s.get("latest_metadata") or {}
        mask = sample.get("registered_mask", 0)
        required = metadata.get("board_pad_mask", 0x1ffe)
        same_boot = (sample.get("boot_id") is None or metadata.get("boot_id") is None
                     or sample["boot_id"] == metadata["boot_id"])
        valid = mask and all(sample.get(f"{kind}_valid_mask", 0) & mask == mask
                             for kind in ("raw", "smooth", "benchmark"))
        return bool(s.get("running") and s.get("ready") and s.get("capture_start_ack")
                    and s.get("latest_metadata") and s.get("samples", 0)
                    and valid and same_boot and mask & required == required
                    and self.clock() - self.last_sample_seen < self.stale_timeout)

    def command(self, action: str, payload=None):
        if action not in ("start", "pause", "resume", "skip", "mistake", "stop"):
            raise ValueError("Unknown action")
        payload = copy.deepcopy(payload or {})
        # Reject malformed requests synchronously; the scheduler checks state again.
        if action == "start":
            env = payload.get("environment")
            if not isinstance(env, dict) or any(not str(env.get(k, "")).strip()
                                                for k in ("cover", "grip", "finger")):
                raise ValueError("Cover, grip/support and finger fields are required; unknown is allowed")
            payload["seed"] = int(payload.get("seed", 42))
            payload["plan"] = make_plan(payload.get("block", "pilot"), payload["seed"],
                                        float(payload.get("pre_idle", 1)), float(payload.get("contact", 2)),
                                        float(payload.get("post_idle", 1)))
            with self.lock:
                if not self._ready():
                    raise ValueError("Waiting for device synchronization and fresh valid samples; labeled collection has not started")
                if self.state not in ("idle", "complete"):
                    raise ValueError("Finish or stop the current block first")
        elif action == "resume":
            with self.lock:
                if self.state != "paused" or not self._ready():
                    raise ValueError("Resume needs a paused block and fresh valid samples")
        elif action in ("pause", "skip"):
            with self.lock:
                if self.state not in ("running", "waiting_marker", "paused"):
                    raise ValueError("No active block")
        elif action == "mistake":
            with self.lock:
                if self.previous is None:
                    raise ValueError("No completed or interrupted trial to mark")
                # Bind the click to the trial the user saw, even if cues advance.
                payload["trial_id"] = self.previous["trial_id"]
        self.commands.put((action, payload))

    def _marker(self, purpose, continuation=None, **context):
        self.marker_number += 1
        token = f"ui.{self.marker_number:06d}.{purpose}"
        details = {"token": token, "purpose": purpose, "generation": self.generation,
                   "continuation": continuation, "deadline": self.clock() + self.marker_timeout,
                   **context}
        self._write("marker_requested", **{k: v for k, v in details.items()
                                          if k not in ("deadline", "continuation", "generation")})
        try:
            self.capture.mark(token)
        except Exception as exc:
            self._write("marker_failed", token=token, purpose=purpose, error=str(exc))
            if continuation and continuation[0] == "stop":
                self._stop_capture()
            elif continuation:
                self._pause(f"Marker send failed: {exc}", send_marker=False, outcome="missing_marker")
            return
        self.pending[token] = details
        if continuation and continuation[0] != "stop":
            self.state = "waiting_marker"
            self.reason = ""

    def _begin_trial(self):
        if self.index >= len(self.plan):
            self.state, self.reason = "complete", "Block complete. Raw capture is still running."
            self._write("block_end", block_id=self.block_id, block=self.block, trials=len(self.plan))
            self.current = None
            return
        self.trial_number += 1
        self.current = dict(copy.deepcopy(self.plan[self.index]),
                            trial_id=f"{self.block_id}.trial{self.trial_number:04d}",
                            block_id=self.block_id, plan_index=self.index)
        self.phase = None
        self.phase_end = None
        self._write("trial_intent", **self.current)
        self._next_phase()

    def _next_phase(self):
        start = PHASES.index(self.phase) + 1 if self.phase is not None else 0
        next_phase = next((p for p in PHASES[start:] if self.current["durations"][p] > 0), None)
        # The same acknowledged boundary closes the old phase and opens the next.
        self._marker("phase" if next_phase else "trial_end",
                     ("phase", next_phase) if next_phase else ("finish",),
                     trial_id=self.current["trial_id"], ending_phase=self.phase,
                     starting_phase=next_phase)

    def _finish_trial(self, token, ack):
        trial = self.current
        self._write("trial_outcome", trial_id=trial["trial_id"], outcome="completed",
                    label_status="intended_action_not_sensor_verified", marker_token=token, marker=ack)
        self.previous = copy.deepcopy(trial)
        self.current = None
        self.index += 1
        self._advance_or_validation_break(trial["split"])

    def _advance_or_validation_break(self, previous_split):
        # Validation requires a deliberate reposition and user resume.
        if (self.index < len(self.plan) and self.plan[self.index]["split"] == "validation"
                and previous_split != "validation"):
            self.phase = self.phase_end = None
            self.state = "paused"
            self.reason = "Validation block: lift your hand, reposition the device in the same orientation, then Resume."
            self._write("validation_break", block_id=self.block_id, next_plan_index=self.index)
        else:
            self._begin_trial()

    def _pause(self, reason, *, send_marker=True, outcome="interrupted"):
        self.generation += 1  # Late acknowledgments stay recorded but cannot advance cues.
        if self.current:
            self._write("trial_outcome", trial_id=self.current["trial_id"], outcome=outcome,
                        reason=reason, phase=self.phase, label_status="exclude_from_complete_trials")
            self.previous = copy.deepcopy(self.current)
            self.current = None
        self.phase = self.phase_end = None
        self.state, self.reason = "paused", reason
        self._write("pause", reason=reason, next_plan_index=self.index)
        if send_marker:
            self._marker("pause", next_plan_index=self.index)

    def _stop_capture(self):
        self.capture.stop()
        self.capture_status = self.capture.status()
        self.state, self.reason = "stopped", "Recording stopped. Files are saved in the session directory."
        self._write("collector_stop")
        self.journal.flush()
        os.fsync(self.journal.fileno())

    def _apply_command(self, action, payload):
        if action == "start":
            if self.state not in ("idle", "complete") or not self._ready():
                raise ValueError("Start was overtaken by another action or capture is no longer ready")
            self.block_number += 1
            self.block = payload.get("block", "pilot")
            self.block_id = f"block{self.block_number:02d}.{self.block}"
            self.plan, self.index = payload["plan"], 0
            self.environment = {k: str(v).strip() for k, v in payload["environment"].items()}
            self.generation += 1
            self.error = None
            self._write("block_start", block_id=self.block_id, block=self.block,
                        environment=self.environment, seed=payload["seed"], plan=self.plan,
                        validation_policy="Fourth randomized positions pass is reserved for validation; no fitting in collector")
            self._begin_trial()
        elif action == "pause" and self.state in ("running", "waiting_marker"):
            self._pause("Paused by user. Resume retries this target with a new trial ID.")
        elif action == "resume" and self.state == "paused":
            if not self._ready():
                raise ValueError("Capture not ready")
            self.error = None
            self._write("resume", next_plan_index=self.index)
            self._begin_trial()
        elif action == "skip" and self.state in ("running", "waiting_marker", "paused"):
            was_paused = self.state == "paused"
            previous_split = self.plan[self.index]["split"] if self.index < len(self.plan) else None
            self._pause("Target skipped by user.", outcome="skipped")
            if was_paused:
                self._write("plan_target_skipped", block_id=self.block_id, plan_index=self.index,
                            target=self.plan[self.index].get("target") if self.index < len(self.plan) else None)
            self.index += 1
            if not was_paused:
                self._advance_or_validation_break(previous_split)
        elif action == "mistake" and payload.get("trial_id"):
            self._write("label_correction", trial_id=payload["trial_id"],
                        correction="user_marked_mistake", reason=str(payload.get("reason", "")),
                        label_status="exclude_until_review")
            self.reason = f"Marked {payload['trial_id']} as a mistake; original recording preserved."
        elif action == "stop" and self.state != "stopped":
            if self.current:
                self._pause("Stopped by user.", send_marker=False, outcome="stopped")
            self.generation += 1
            self.state, self.reason = "stopping", "Finishing the recording…"
            self._marker("stop", ("stop",))

    @staticmethod
    def _quality_signature(status):
        quality = status.get("quality") or {}
        decoder = quality.get("decoder", status.get("decoder", {}))
        names = ("device_dropped_scans", "packet_gaps", "scan_gaps", "boot_changes",
                 "timestamp_regressions", "invalid_raw_samples", "invalid_smooth_samples",
                 "invalid_benchmark_samples", "missing_required_pad_samples", "packet_duplicates",
                 "packet_regressions", "scan_duplicates", "scan_regressions", "pad0_valid_samples",
                 "dropped_counter_regressions", "event_gaps", "event_duplicates", "event_regressions",
                 "event_timestamp_regressions", "processing_resets", "telemetry_dropped_samples",
                 "telemetry_dropped_events", "transport_failures", "telemetry_counter_regressions")
        return tuple(quality.get(k, 0) for k in names) + tuple(decoder.get(k, 0)
                            for k in ("crc_errors", "payload_errors", "length_errors", "stream_skipped_bytes",
                                      "version_errors", "unknown_types"))

    def tick(self):
        snapshot = self.capture.status()
        with self.lock:
            self.capture_status = snapshot
            count = snapshot.get("samples", 0)
            if count != self.last_sample_count:
                self.last_sample_count = count
                self.last_sample_seen = self.clock()
            quality = self._quality_signature(snapshot)
            quality_changed = self.last_quality is not None and quality != self.last_quality
            self.last_quality = quality
            if self.state in ("running", "waiting_marker"):
                if self.last_ui_seen is not None and self.clock() - self.last_ui_seen > 2.5:
                    self._pause("Cue display disconnected. The interrupted trial is excluded; return to this page, then Resume.",
                                outcome="cue_display_disconnected")
                elif not self._ready():
                    self._pause("Capture is disconnected, stale, or has invalid channel data. Check status before Resume.",
                                send_marker=False, outcome="capture_failure")
                elif quality_changed:
                    self._pause("Capture integrity counters changed. The interrupted trial is excluded; inspect status before Resume.",
                                outcome="capture_failure")
            while not self.commands.empty():
                action, payload = self.commands.get_nowait()
                try:
                    self._apply_command(action, payload)
                except Exception as exc:
                    self.error = str(exc)
                    self._write("command_error", action=action, error=self.error)
            acks = snapshot.get("marker_acks") or {}
            for token, pending in list(self.pending.items()):
                ack = acks.get(token)
                if ack is not None:
                    del self.pending[token]
                    self._write("marker_acknowledged", token=token, marker=ack,
                                late=pending["generation"] != self.generation)
                    continuation = pending["continuation"]
                    if not continuation or pending["generation"] != self.generation:
                        continue
                    if continuation[0] == "stop":
                        self._stop_capture()
                    elif self.current and continuation[0] == "phase":
                        old_phase, self.phase = self.phase, continuation[1]
                        if old_phase is not None:
                            self._write("phase_end", trial_id=self.current["trial_id"], phase=old_phase,
                                        marker_token=token, marker=ack)
                        self.phase_end = self.clock() + self.current["durations"][self.phase]
                        self.state, self.reason = "running", ""
                        self._write("phase_start", trial_id=self.current["trial_id"], phase=self.phase,
                                    marker_token=token, marker=ack)
                    elif self.current and continuation[0] == "finish":
                        self._write("phase_end", trial_id=self.current["trial_id"], phase=self.phase,
                                    marker_token=token, marker=ack)
                        self._finish_trial(token, ack)
                elif self.clock() >= pending["deadline"]:
                    del self.pending[token]
                    self._write("marker_timeout", token=token, purpose=pending["purpose"])
                    continuation = pending["continuation"]
                    if pending["generation"] != self.generation or not continuation:
                        continue
                    if continuation[0] == "stop":
                        self._stop_capture()
                    else:
                        self._pause("Device did not acknowledge the marker. Trial excluded; check connection, then Resume.",
                                    send_marker=False, outcome="missing_marker")
            if self.state == "running" and self.clock() >= self.phase_end:
                self._next_phase()

    def _work(self):
        while not self.closed.wait(0.025):
            try:
                self.tick()
            except Exception as exc:
                with self.lock:
                    self.error = str(exc)
                    self._pause(f"Collector error: {exc}", send_marker=False, outcome="collector_error")

    def status(self):
        with self.lock:
            capture = {k: copy.deepcopy(self.capture_status.get(k)) for k in
                       ("running", "ready", "capture_start_ack", "session_dir", "samples", "latest_metadata", "latest_sample", "quality", "errors")}
            capture["sample_age_s"] = round(self.clock() - self.last_sample_seen, 3)
            return {"synthetic": self.synthetic, "session_dir": str(self.session_dir),
                    "state": self.state, "reason": self.reason, "error": self.error,
                    "block": self.block, "block_id": self.block_id,
                    "index": self.index, "total": len(self.plan), "trial": copy.deepcopy(self.current),
                    "previous_trial": copy.deepcopy(self.previous), "phase": self.phase,
                    "remaining_s": max(0, self.phase_end - self.clock()) if self.phase_end else None,
                    "can_start": self.state in ("idle", "complete") and self._ready(),
                    "can_resume": self.state == "paused" and self._ready(), "capture": capture}

    def ui_seen(self):
        with self.lock:
            self.last_ui_seen = self.clock()

    def close(self):
        self.closed.set()
        if self.worker:
            self.worker.join(timeout=4)
        with self.lock:
            if not self.journal.closed:
                if self.current:
                    self._pause("Server closed.", send_marker=False, outcome="server_closed")
                self.capture.stop()
                self._write("collector_closed")
                self.journal.flush()
                os.fsync(self.journal.fileno())
                self.journal.close()


def make_handler(collector, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def _send(self, status, content, mime="application/json"):
            data = json.dumps(content).encode() if mime == "application/json" else content
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _local(self):
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            expected = f"127.0.0.1:{port}"
            if host != expected or (origin is not None and origin != f"http://{expected}"):
                self._send(403, {"error": "Only this loopback origin may control the collector"})
                return False
            return True

        def do_GET(self):
            if not self._local():
                return
            path = urlsplit(self.path).path
            if path == "/api/status":
                collector.ui_seen()
                self._send(200, collector.status())
                return
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path in assets:
                name, mime = assets[path]
                self._send(200, (UI_DIR / name).read_bytes(), mime)
            else:
                self._send(404, {"error": "Not found"})

        def do_POST(self):
            if not self._local():
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self._send(415, {"error": "JSON required"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 0 or size > 16384:
                    raise ValueError("Invalid request length")
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("JSON object required")
                path = urlsplit(self.path).path
                if not path.startswith("/api/"):
                    self._send(404, {"error": "Not found"})
                    return
                collector.command(path[5:], payload)
                self._send(202, {"accepted": True})
            except (ValueError, TypeError) as exc:
                self._send(400, {"error": str(exc)})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Serial device, e.g. /dev/ttyACM0")
    parser.add_argument("--output", type=Path, required=True, help="New session directory; existing paths are refused")
    parser.add_argument("--listen-port", type=int, default=8765, help="Loopback HTTP port (default: 8765)")
    parser.add_argument("--dry-run", action="store_true", help="Synthetic wire fixture; never physical calibration data")
    args = parser.parse_args()
    if not args.dry_run and not args.port:
        parser.error("--port is required unless --dry-run is set")
    if not 1 <= args.listen_port <= 65535:
        parser.error("--listen-port must be between 1 and 65535")
    from capture_session import CaptureSession
    capture = CaptureSession(serial_factory=SyntheticSerial) if args.dry_run else CaptureSession()
    collector = server = None
    try:
        capture.start(args.port or "SYNTHETIC", args.output,
                      metadata={"purpose": "guided_calibration", "synthetic": args.dry_run})
        collector = Collector(capture, args.output, synthetic=args.dry_run)
        server = ThreadingHTTPServer(("127.0.0.1", args.listen_port), make_handler(collector, args.listen_port))
        server.daemon_threads = True
        print(f"Open http://127.0.0.1:{args.listen_port}", flush=True)
        print(f"Session: {args.output.resolve()}", flush=True)
        if args.dry_run:
            print("SYNTHETIC UI TEST — not physical calibration data", flush=True)
        def terminate(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, terminate)
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            server.server_close()
        if collector:
            collector.close()
        else:
            capture.stop()


if __name__ == "__main__":
    main()
