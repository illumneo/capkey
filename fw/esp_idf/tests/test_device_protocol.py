"""On-device decision framing and independent acquisition/telemetry accounting."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from capture_protocol import CaptureQuality, StreamDecoder, encode_packet
from capture_session import CaptureSession
from test_capture_protocol import FakeSerial, sample_payload, sample_record


def event_payload(event="gesture", **changes):
    value = dict(event=event, boot_id=42, event_seq=10, scan_seq=11,
                 timestamp_us=20000, processing_epoch=0, model="pcb",
                 x=0.25, y=0.5, z=0.0, start_x=0.2, start_y=0.5,
                 max_distance=0.05, gesture_type=1, direction=0, grid_position=0,
                 action={"type": "char", "char_code": 97, "label": "a"},
                 output_backend="log_only", hid_sent=False,
                 reason="capture_start_idle" if event == "idle_checkpoint" else "acquisition_gap",
                 acq_dropped_scans=0, telemetry_dropped_samples=0,
                 telemetry_dropped_events=0, transport_failures=0)
    value.update(changes)
    return value


def event_record(sequence, **changes):
    return StreamDecoder().feed(encode_packet(4, event_payload(**changes), sequence))[0]


class DeviceProtocolTests(unittest.TestCase):
    def test_every_fragment_boundary_preserves_actual_action(self):
        wire = encode_packet(4, event_payload(action={"type": "char", "char_code": 34, "label": '"'}), 9)
        for split in range(len(wire) + 1):
            decoder = StreamDecoder()
            rows = decoder.feed(wire[:split]) + decoder.feed(wire[split:])
            self.assertEqual(len(rows), 1, split)
            self.assertEqual(rows[0]["type"], "device_event")
            self.assertEqual(rows[0]["action"]["label"], '"')
            self.assertFalse(rows[0]["hid_sent"])
            self.assertEqual(decoder.status()["payload_errors"], 0)

    def test_hid_queue_acceptance_does_not_claim_delivery(self):
        for queued, sent in ((True, None), (False, False), (True, True)):
            with self.subTest(queued=queued, sent=sent):
                row = event_record(8, output_backend="usb_hid", hid_queued=queued, hid_sent=sent)
                self.assertIs(row["hid_queued"], queued)
                self.assertIs(row["hid_sent"], sent)
        # Log-only captures remain compatible, with or without an explicit queue field.
        self.assertFalse(event_record(9)["hid_sent"])
        self.assertFalse(event_record(10, hid_queued=False)["hid_queued"])

    def test_hid_state_rejects_false_delivery_claims_and_non_boolean_types(self):
        invalid = [dict(output_backend="unknown"), dict(hid_queued=True),
                   dict(hid_queued=0), dict(hid_sent=0),
                   dict(output_backend="usb_hid", hid_sent=None),
                   dict(output_backend="usb_hid", hid_queued=1, hid_sent=None),
                   dict(output_backend="usb_hid", hid_queued=None, hid_sent=False),
                   dict(output_backend="usb_hid", hid_queued=True, hid_sent=False),
                   dict(output_backend="usb_hid", hid_queued=True, hid_sent=1),
                   dict(output_backend="usb_hid", hid_queued=False, hid_sent=None),
                   dict(output_backend="usb_hid", hid_queued=False, hid_sent=True)]
        for changes in invalid:
            with self.subTest(changes=changes):
                decoder = StreamDecoder()
                rows = decoder.feed(encode_packet(4, event_payload(**changes)))
                self.assertEqual(rows, [])
                self.assertEqual(decoder.status()["payload_errors"], 1)
        payload = event_payload(output_backend="usb_hid", hid_queued=True)
        del payload["hid_sent"]
        decoder = StreamDecoder()
        self.assertEqual(decoder.feed(encode_packet(4, payload)), [])
        self.assertEqual(decoder.status()["payload_errors"], 1)

    def test_hid_status_and_diagnostic_ack_are_preserved(self):
        metadata = dict(output_backend="usb_hid", hid_layout="US", hid_mounted=True,
                        hid_shift_pending=False, hid_enabled=True, hid_enqueued=12,
                        hid_completed=10, hid_failed=1, hid_queue_drops=2,
                        hid_state_actions=3, hid_queue_depth=1)
        marker = dict(token="ascii-a", device_us=2345, scan_seq=67, boot_id=42,
                      hid_accepted=True)
        rows = StreamDecoder().feed(encode_packet(1, metadata, 1) + encode_packet(3, marker, 2))
        self.assertEqual(rows[0]["hid_completed"], 10)
        self.assertEqual(rows[0]["hid_failed"], 1)
        self.assertTrue(rows[1]["hid_accepted"])
        for key in ("hid_enqueued", "hid_completed", "hid_failed", "hid_queue_drops",
                    "hid_state_actions", "hid_queue_depth"):
            for value in (True, -1, 1 << 32, 1.5):
                with self.subTest(key=key, value=value):
                    decoder = StreamDecoder()
                    self.assertEqual(decoder.feed(encode_packet(1, dict(metadata, **{key: value}))), [])
                    self.assertEqual(decoder.status()["payload_errors"], 1)
        for key in ("hid_mounted", "hid_suspended", "hid_shift_pending", "hid_enabled"):
            decoder = StreamDecoder()
            self.assertEqual(decoder.feed(encode_packet(1, dict(metadata, **{key: 1}))), [])
        decoder = StreamDecoder()
        self.assertEqual(decoder.feed(encode_packet(3, dict(marker, hid_accepted=1))), [])

    def test_crc_damage_recovers_next_event(self):
        wire = bytearray(encode_packet(4, event_payload(), 1))
        wire[50] ^= 1
        decoder = StreamDecoder()
        rows = decoder.feed(wire + encode_packet(4, event_payload(event_seq=11), 2))
        self.assertEqual([r["event_seq"] for r in rows], [11])
        self.assertEqual(decoder.status()["crc_errors"], 1)

    def test_malformed_events_fail_as_payload_not_unknown_type(self):
        invalid = [dict(event="unknown"), dict(event_seq=True), dict(timestamp_us=-1),
                   dict(processing_epoch=1 << 32), dict(gesture_type=True), dict(direction=9),
                   dict(grid_position=16), dict(model="unrecorded"), dict(x="0"), dict(x=10 ** 400),
                   dict(action={"type": "char", "char_code": 300, "label": "x"}),
                   dict(action={"type": "bogus", "char_code": 0, "label": ""}),
                   dict(hid_sent=True), dict(transport_failures=-1)]
        for changes in invalid:
            with self.subTest(changes=changes):
                decoder = StreamDecoder()
                self.assertEqual(decoder.feed(encode_packet(4, event_payload(**changes))), [])
                self.assertEqual(decoder.status()["payload_errors"], 1)
                self.assertEqual(decoder.status()["unknown_types"], 0)

    def test_completed_none_gesture_is_preserved(self):
        row = event_record(1, gesture_type=0, action={"type": "none", "char_code": 0, "label": ""})
        self.assertEqual(row["gesture_type"], 0)
        self.assertEqual(row["action"]["type"], "none")

    def test_event_between_samples_does_not_consume_acquisition_sequence(self):
        quality = CaptureQuality()
        quality.observe(sample_record(1, scan=11, timestamp=20000))
        quality.observe(event_record(2, event="idle_checkpoint"))
        quality.observe(event_record(3, event_seq=11))
        quality.observe(sample_record(4, scan=12, timestamp=40000))
        status = quality.status()
        self.assertEqual(status["samples"], 2)
        self.assertEqual(status["device_event_records"], 2)
        self.assertEqual(status["idle_checkpoints"], 1)
        self.assertEqual(status["gesture_events"], 1)
        self.assertEqual(status["marker_records"], 0)
        for key in ("scan_gaps", "scan_duplicates", "packet_gaps", "event_gaps", "event_timestamp_regressions"):
            self.assertEqual(status[key], 0, key)

    def test_event_losses_and_resets_are_separate_from_acquisition_loss(self):
        quality = CaptureQuality()
        quality.observe(event_record(1, event_seq=20))
        quality.observe(event_record(2, event="processing_reset", event_seq=23, processing_epoch=1))
        quality.observe(event_record(3, event_seq=23))
        quality.observe(event_record(4, event_seq=22, timestamp_us=19000))
        status = quality.status()
        self.assertEqual(status["event_gaps"], 2)
        self.assertEqual(status["event_duplicates"], 1)
        self.assertEqual(status["event_regressions"], 1)
        self.assertEqual(status["event_timestamp_regressions"], 1)
        self.assertEqual(status["processing_resets"], 1)
        self.assertEqual(status["device_dropped_scans"], 0)

    def test_tail_counters_detect_backpressure_even_with_contiguous_frames(self):
        quality = CaptureQuality()
        quality.observe(dict(type="metadata", packet_seq=0, boot_id=42,
                             telemetry_dropped_samples=200, telemetry_dropped_events=5,
                             transport_failures=7))
        quality.observe(sample_record(1, scan=11, timestamp=20000))
        quality.observe(sample_record(2, scan=12, timestamp=40000))
        quality.observe(dict(type="metadata", packet_seq=3, boot_id=42,
                             telemetry_dropped_samples=207, telemetry_dropped_events=6,
                             transport_failures=9))
        status = quality.status()
        self.assertEqual(status["telemetry_dropped_samples"], 7)
        self.assertEqual(status["telemetry_dropped_events"], 1)
        self.assertEqual(status["transport_failures"], 2)
        self.assertEqual(status["device_dropped_scans"], 0)
        self.assertEqual(status["packet_gaps"], 0)
        self.assertEqual(status["scan_gaps"], 0)
        self.assertEqual(status["initial_telemetry_counters_by_boot"]["42"]["telemetry_dropped_samples"], 200)

    def test_counter_wrap_and_regression(self):
        quality = CaptureQuality()
        quality.observe(event_record(1, telemetry_dropped_events=0xffffffff, event_seq=0xffffffff))
        quality.observe(event_record(2, telemetry_dropped_events=0, event_seq=0))
        quality.observe(event_record(3, telemetry_dropped_events=0xffffffff, event_seq=1))
        self.assertEqual(quality.status()["telemetry_dropped_events"], 1)
        self.assertEqual(quality.status()["telemetry_counter_regressions"], 1)
        self.assertEqual(quality.status()["event_gaps"], 0)


class RuntimeSerial(FakeSerial):
    def write(self, data):
        self.sent.append(data)
        if data == b"HELLO\n":
            rows = [(1, dict(boot_id=42, event_protocol_version=1, streaming=True,
                             telemetry_dropped_samples=0, telemetry_dropped_events=0, transport_failures=0)),
                    (4, event_payload(timestamp_us=10000, event_seq=9))]
        elif data.startswith(b"MARK capture-start-"):
            token = data.decode().strip().split(" ", 1)[1]
            rows = [(3, dict(token=token, device_us=20000, scan_seq=10, boot_id=42)),
                    (4, event_payload(timestamp_us=15000, event_seq=10)),
                    (2, sample_payload(timestamp=20000, scan=11)),
                    (4, event_payload(event="idle_checkpoint", event_seq=11)),
                    (4, event_payload(event_seq=12))]
        elif data == b"STOP\n":
            # Completed pre-STOP work must be drained before final metadata.
            rows = [(2, sample_payload(timestamp=40000, scan=12)),
                    (4, event_payload(timestamp_us=40000, scan_seq=12, event_seq=13)),
                    (1, dict(boot_id=42, event_protocol_version=1, streaming=False,
                             telemetry_dropped_samples=2, telemetry_dropped_events=0, transport_failures=0))]
        else:
            raise AssertionError(data)
        wire = b""
        for kind, payload in rows:
            wire += encode_packet(kind, payload, self.sequence)
            self.sequence += 1
        if data == b"STOP\n":
            wire += b"Gesture after STOP: outside recording\r\n"
        self.wire.extend(wire)
        self.incoming.put(wire)
        return len(data)


class RuntimeSessionTests(unittest.TestCase):
    def test_boundary_filter_and_final_counter_drain(self):
        fake = RuntimeSerial()
        session = CaptureSession(serial_factory=lambda **kwargs: fake)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "capture"
            try:
                session.start("synthetic", output)
                deadline = time.monotonic() + 2
                while session.status()["device_events"] != 2 and time.monotonic() < deadline:
                    time.sleep(0.005)
                state = session.stop()
                self.assertEqual(state["samples"], 2)
                self.assertEqual(state["device_events"], 3)
                self.assertEqual(state["startup_device_events"], 2)
                self.assertTrue(state["stop_metadata_received"])
                self.assertEqual(state["quality"]["packet_gaps"], 0)
                self.assertEqual(state["quality"]["event_gaps"], 0)
                self.assertEqual(state["quality"]["telemetry_dropped_samples"], 2)
                self.assertEqual(state["quality"]["decoder"]["stream_skipped_bytes"], 0)
                self.assertFalse(state["quality"]["clean"])
                self.assertIn("telemetry_dropped_samples: 2", state["quality"]["issues"])
                self.assertEqual((output / "wire.bin").read_bytes(), bytes(fake.wire))
                events = [json.loads(line) for line in (output / "frames.jsonl").read_text().splitlines()
                          if json.loads(line)["type"] == "device_event"]
                self.assertEqual([r["capture_phase"] for r in events], ["startup", "startup", "recording", "recording", "recording"])
            finally:
                session.stop()


if __name__ == "__main__":
    unittest.main()
