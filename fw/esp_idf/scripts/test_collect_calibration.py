#!/usr/bin/env python3
"""Intent/marker state-machine tests; no serial device is opened."""
import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

from collect_calibration import Collector, SyntheticSerial, make_handler, make_plan


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeCapture:
    def __init__(self):
        self.state = {"running": True, "ready": True, "capture_start_ack": {"boot_id": 1}, "samples": 1,
                      "latest_metadata": {"boot_id": 1, "board_pad_mask": 0x1ffe},
                      "latest_sample": {"registered_mask": 0x1ffe, "raw_valid_mask": 0x1ffe,
                                        "smooth_valid_mask": 0x1ffe, "benchmark_valid_mask": 0x1ffe},
                      "marker_acks": {}, "quality": {}, "errors": []}
        self.requests = []

    def status(self):
        return copy.deepcopy(self.state)

    def mark(self, token):
        self.requests.append(token)
        return token

    def ack(self, token=None):
        token = token or self.requests[-1]
        self.state["marker_acks"][token] = {"token": token, "device_us": 100000,
                                           "scan_seq": self.state["samples"], "boot_id": 1}

    def stop(self):
        self.state["running"] = False
        return self.status()


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.clock, self.capture = FakeClock(), FakeCapture()
        self.collector = Collector(self.capture, Path(self.directory.name), clock=self.clock,
                                   marker_timeout=1, start_worker=False)
        self.collector.tick()

    def tearDown(self):
        self.collector.close()
        self.directory.cleanup()

    def events(self, kind=None):
        records = [json.loads(line) for line in
                   (Path(self.directory.name) / "trials.jsonl").read_text().splitlines()]
        return [r for r in records if kind is None or r["event"] == kind]

    def start(self, block="positions"):
        self.collector.command("start", {"block": block,
                               "environment": {"cover": "unknown", "grip": "desk", "finger": "index"}})
        self.collector.tick()

    def advance(self, seconds, sample=True):
        self.clock.advance(seconds)
        if sample:
            self.capture.state["samples"] += 1
        self.collector.tick()

    def test_randomized_plan_has_disjoint_trial_blocks_and_all_regions(self):
        first = make_plan("positions", 37)
        self.assertEqual(first, make_plan("positions", 37))
        self.assertNotEqual(first, make_plan("positions", 38))
        self.assertEqual(len(first), 64)
        for offset in (0, 16, 32, 48):
            self.assertEqual(len({x["target"]["id"] for x in first[offset:offset + 16]}), 16)
        self.assertTrue(all(t["split"] == "training" for t in first[:48]))
        self.assertTrue(all(t["split"] == "validation" for t in first[48:]))
        # Stationary calibration holds are not assigned tap-key outcomes.
        self.assertTrue(all(t["expected_key"] is None for t in first))

    def test_pilot_has_idle_corners_center_and_two_traversals(self):
        plan = make_plan("pilot")
        self.assertEqual(len(plan), 8)
        self.assertEqual(plan[0]["intended_action"], "hands_away")
        self.assertEqual(sum(sum(x["durations"].values()) for x in plan), 48)
        self.assertEqual({x["expected_direction"] for x in plan if "expected_direction" in x}, {"east", "south"})

    def test_start_requires_metadata_and_all_required_channels(self):
        self.capture.state["latest_metadata"] = None
        self.collector.tick()
        with self.assertRaises(ValueError):
            self.start()
        self.capture.state["latest_metadata"] = {"board_pad_mask": 0x1ffe}
        self.capture.state["latest_sample"]["registered_mask"] = 0x1ffc
        self.collector.tick()
        with self.assertRaises(ValueError):
            self.start()
        self.assertEqual(self.events("trial_intent"), [])

    def test_no_cue_timer_until_device_ack(self):
        self.start()
        self.assertEqual(self.collector.state, "waiting_marker")
        self.assertIsNone(self.collector.phase_end)
        self.advance(0.8)
        self.assertEqual(self.events("phase_start"), [])
        self.capture.ack()
        self.collector.tick()
        self.assertEqual(self.collector.phase, "pre_idle")
        self.assertAlmostEqual(self.collector.phase_end, self.clock() + 1)

    def test_start_rejects_metadata_from_previous_boot(self):
        self.capture.state["latest_sample"]["boot_id"] = 2
        self.collector.tick()
        with self.assertRaises(ValueError):
            self.start()

    def test_start_requires_own_handshake_even_if_samples_are_present(self):
        for missing in ("ready", "capture_start_ack"):
            with self.subTest(missing=missing):
                saved = self.capture.state[missing]
                self.capture.state[missing] = None
                self.collector.tick()
                self.assertFalse(self.collector.status()["can_start"])
                with self.assertRaises(ValueError):
                    self.start()
                self.capture.state[missing] = saved
        self.assertEqual(self.events("trial_intent"), [])

    def test_timeout_excludes_trial_and_late_ack_cannot_advance(self):
        self.start()
        token = self.capture.requests[-1]
        self.advance(1.1)
        self.assertEqual(self.collector.state, "paused")
        self.assertEqual(self.events("trial_outcome")[-1]["outcome"], "missing_marker")
        self.capture.ack(token)
        self.collector.tick()
        self.assertEqual(self.collector.state, "paused")
        self.assertEqual(self.events("phase_start"), [])

    def test_pause_keeps_capture_and_resume_retries_with_new_id(self):
        self.start()
        first = self.collector.current["trial_id"]
        target = self.collector.current["target"]
        old_token = self.capture.requests[-1]
        self.collector.command("pause")
        self.collector.tick()
        self.assertTrue(self.capture.state["running"])
        self.collector.command("resume")
        self.collector.tick()
        self.assertNotEqual(self.collector.current["trial_id"], first)
        self.assertEqual(self.collector.current["target"], target)
        self.capture.ack(old_token)
        self.collector.tick()
        self.assertEqual(self.collector.state, "waiting_marker")
        self.assertEqual(self.events("phase_start"), [])

    def test_complete_trial_uses_acknowledged_boundaries_without_detection(self):
        self.start()
        for duration in (1, 2, 1):
            self.capture.ack()
            self.collector.tick()
            self.advance(duration + 0.01)
        self.capture.ack()
        self.collector.tick()
        outcomes = self.events("trial_outcome")
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]["outcome"], "completed")
        self.assertEqual(len(self.events("phase_start")), 3)
        self.assertEqual(len(self.events("phase_end")), 3)
        self.assertEqual(self.collector.index, 1)

    def test_skip_at_validation_boundary_still_requires_reposition(self):
        self.start()
        self.collector.index = 47
        self.collector.current = dict(self.collector.plan[47], trial_id="last.training")
        self.collector.command("skip")
        self.collector.tick()
        self.assertEqual(self.collector.index, 48)
        self.assertEqual(self.collector.state, "paused")
        self.assertIsNone(self.collector.current)
        self.assertIn("Validation", self.collector.reason)
        self.assertEqual(len(self.events("validation_break")), 1)

    def test_mistake_correction_is_append_only_and_bound_at_click(self):
        self.start()
        first = self.collector.current["trial_id"]
        self.collector.command("pause")
        self.collector.tick()
        self.collector.command("mistake")
        self.collector.previous = {"trial_id": "newer.trial"}
        self.collector.tick()
        self.assertEqual(self.events("label_correction")[-1]["trial_id"], first)
        self.assertEqual(len(self.events("trial_intent")), 1)

    def test_stalled_capture_excludes_current_trial(self):
        self.start()
        self.capture.ack()
        self.collector.tick()
        self.advance(3, sample=False)
        self.assertEqual(self.collector.state, "paused")
        self.assertEqual(self.events("trial_outcome")[-1]["outcome"], "capture_failure")

    def test_new_loss_pauses_but_old_loss_does_not_prevent_ready(self):
        self.capture.state["quality"] = {"device_dropped_scans": 5}
        self.collector.tick()
        self.start()
        self.capture.ack()
        self.collector.tick()
        self.capture.state["quality"]["device_dropped_scans"] = 6
        self.collector.tick()
        self.assertEqual(self.collector.state, "paused")
        self.assertEqual(self.events("trial_outcome")[-1]["outcome"], "capture_failure")

    def test_disconnected_cue_display_pauses_without_stopping_capture(self):
        self.collector.ui_seen()
        self.start()
        self.capture.ack()
        self.collector.tick()
        self.advance(3)
        self.assertEqual(self.collector.state, "paused")
        self.assertEqual(self.events("trial_outcome")[-1]["outcome"], "cue_display_disconnected")
        self.assertTrue(self.capture.state["running"])

    def test_telemetry_loss_excludes_trial_even_when_acquisition_is_contiguous(self):
        self.start()
        self.capture.ack()
        self.collector.tick()
        self.capture.state["samples"] += 1
        self.capture.state["quality"]["telemetry_dropped_events"] = 1
        self.collector.tick()
        self.assertEqual(self.collector.state, "paused")
        self.assertEqual(self.events("trial_outcome")[-1]["outcome"], "capture_failure")
        self.assertTrue(self.capture.state["running"])

    def test_http_rejects_external_origin_and_does_not_expose_files(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.collector, 0))
        server.RequestHandlerClass = make_handler(self.collector, server.server_port)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        try:
            connection.request("GET", "/api/status")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["state"], "idle")
            connection.request("POST", "/api/stop", "{}", {"Content-Type": "application/json", "Origin": "https://other.example"})
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            connection.request("GET", "/../collect_calibration.py")
            response = connection.getresponse()
            self.assertEqual(response.status, 404)
            response.read()
            self.assertTrue(self.collector.commands.empty())
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            worker.join(2)


class CaptureHandshakeIntegrationTest(unittest.TestCase):
    def test_real_capture_handshake_enables_start_but_never_starts_cues(self):
        from capture_session import CaptureSession
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "synthetic-session"
            capture = CaptureSession(serial_factory=SyntheticSerial)
            collector = None
            try:
                capture.start("SYNTHETIC", directory, metadata={"synthetic": True})
                collector = Collector(capture, directory, synthetic=True, start_worker=False)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    collector.tick()
                    if collector.status()["can_start"]:
                        break
                    time.sleep(0.005)
                status = collector.status()
                self.assertTrue(status["capture"]["ready"])
                self.assertIsNotNone(status["capture"]["capture_start_ack"])
                metadata = status["capture"]["latest_metadata"]
                self.assertTrue(metadata["synthetic"])
                self.assertTrue(metadata["board_is_simulated"])
                self.assertEqual(metadata["board"], "capkey_6x6_50mm")
                self.assertEqual(metadata["acquisition"]["charge_times"], 800)
                self.assertIsNone(metadata["elf_sha256"])
                self.assertIsNone(metadata["sdkconfig_sha256"])
                self.assertEqual(len(metadata["provenance"]["generator_sha256"]), 64)
                self.assertTrue(status["can_start"])
                self.assertEqual(status["state"], "idle")
                self.assertIsNone(status["trial"])
                events = [json.loads(line) for line in (directory / "trials.jsonl").read_text().splitlines()]
                self.assertEqual([x for x in events if x["event"] == "trial_intent"], [])
                collector.command("start", {"block": "pilot", "environment":
                                   {"cover": "synthetic", "grip": "none", "finger": "none"}})
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    collector.tick()
                    if collector.status()["state"] == "running":
                        break
                    time.sleep(0.005)
                self.assertEqual(collector.status()["state"], "running")
                self.assertEqual(collector.current["intended_action"], "hands_away")
                self.assertTrue(capture.status()["quality"]["clean"])
            finally:
                if collector:
                    collector.close()
                else:
                    capture.stop()


if __name__ == "__main__":
    unittest.main()
