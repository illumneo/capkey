"""Protocol corruption, continuity and capture lifecycle tests; no device access."""
from __future__ import annotations

import json
from pathlib import Path
import queue
import struct
import sys
import tempfile
import time
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from capture_protocol import (CRC, HEADER, MAGIC, SAMPLE, CaptureQuality,
                              StreamDecoder, encode_packet)
from capture_session import CaptureSession


def sample_payload(timestamp=10000, scan=10, dropped=0, boot=42, mask=0x7ffe):
    return SAMPLE.pack(timestamp, scan, dropped, 125, boot, mask, mask, mask, mask,
                       *range(15), *range(100, 115), *range(200, 215))


def sample_record(sequence=1, **kwargs):
    return StreamDecoder().feed(encode_packet(2, sample_payload(**kwargs), sequence))[0]


class ProtocolTests(unittest.TestCase):
    def test_wire_layout_and_every_fragment_boundary(self):
        wire = encode_packet(2, sample_payload(timestamp=0x123456789abcdef0), 7)
        self.assertEqual(HEADER.size, 12)
        self.assertEqual(SAMPLE.size, 212)
        self.assertEqual(len(wire), 228)
        self.assertEqual(wire[:12], b"SWP1\x01\x02\xd4\x00\x07\x00\x00\x00")
        self.assertEqual(struct.unpack("<I", wire[-4:])[0], zlib.crc32(wire[:-4]))
        for split in range(len(wire) + 1):
            decoder = StreamDecoder()
            rows = decoder.feed(wire[:split]) + decoder.feed(wire[split:])
            self.assertEqual(len(rows), 1, split)
            row = rows[0]
            self.assertEqual(row["timestamp_us"], 0x123456789abcdef0)
            self.assertEqual(row["raw"], list(range(15)))
            self.assertEqual(row["smooth"], list(range(100, 115)))
            self.assertEqual(row["benchmark"], list(range(200, 215)))
            self.assertEqual(row["raw_valid_mask"], 0x7ffe)
            self.assertEqual(row["packet_seq"], 7)
            self.assertEqual(decoder.status()["skipped_bytes"], 0)

    def test_bytewise_noise_crc_and_resynchronization(self):
        good = encode_packet(2, sample_payload(), 8)
        bad = bytearray(good)
        bad[30] ^= 1
        stream = b"boot console\r\nSWSWP" + bad + good
        decoder = StreamDecoder()
        rows = []
        for byte in stream:
            rows.extend(decoder.feed(bytes([byte])))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["packet_seq"], 8)
        self.assertEqual(decoder.status()["crc_errors"], 1)
        self.assertEqual(decoder.status()["skipped_bytes"], len(stream) - len(good))

    def test_corrupt_length_does_not_hide_next_valid_frame(self):
        bogus = HEADER.pack(MAGIC, 1, 1, 4096, 0) + b"bad"
        decoder = StreamDecoder()
        rows = decoder.feed(bogus + encode_packet(1, {"firmware": "test"}, 1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["firmware"], "test")
        self.assertEqual(decoder.status()["length_errors"], 1)
        self.assertEqual(decoder.status()["skipped_bytes"], len(bogus))

    def test_version_length_payload_errors_are_reported(self):
        version = bytearray(encode_packet(1, {}, 0))
        version[4] = 2
        wrong_sample = encode_packet(2, b"short", 1)
        nonobject = encode_packet(1, b"[]", 2)
        invalid_marker = encode_packet(3, {"token": "t"}, 3)
        unknown = encode_packet(9, b"", 4)
        good = encode_packet(1, {"type": "wrong", "packet_seq": 999}, 5)
        decoder = StreamDecoder()
        rows = decoder.feed(version + wrong_sample + nonobject + invalid_marker + unknown + good)
        self.assertEqual(rows, [{"type": "metadata", "packet_seq": 5}])
        stats = decoder.status()
        self.assertEqual(stats["version_errors"], 1)
        self.assertEqual(stats["length_errors"], 1)
        self.assertEqual(stats["payload_errors"], 2)
        self.assertEqual(stats["unknown_types"], 1)
        self.assertEqual(stats["skipped_bytes"], len(version + wrong_sample + nonobject + invalid_marker + unknown))

    def test_truncated_tail_is_not_silently_discarded(self):
        decoder = StreamDecoder()
        decoder.feed(encode_packet(2, sample_payload())[:77])
        self.assertEqual(decoder.status()["buffered_bytes"], 77)
        decoder.finish()
        self.assertEqual(decoder.status()["trailing_bytes"], 77)
        decoder.finish()
        self.assertEqual(decoder.status()["trailing_bytes"], 77)

    def test_metadata_and_marker_force_wire_type(self):
        marker = {"token": "trial_1.begin", "device_us": 123, "scan_seq": 7,
                  "boot_id": 42, "type": "sample", "packet_seq": 999}
        row = StreamDecoder().feed(encode_packet(3, marker, 2))[0]
        self.assertEqual(row["type"], "marker")
        self.assertEqual(row["packet_seq"], 2)

    def test_rejects_nonfinite_json(self):
        decoder = StreamDecoder()
        self.assertEqual(decoder.feed(encode_packet(1, b'{"bad":NaN}')), [])
        self.assertEqual(decoder.status()["payload_errors"], 1)


class QualityTests(unittest.TestCase):
    def test_gaps_duplicates_regressions_and_reboot(self):
        q = CaptureQuality()
        q.observe({"type": "metadata", "packet_seq": 0, "boot_id": 42})
        q.observe(sample_record(1, scan=10, timestamp=10000))
        q.observe(sample_record(3, scan=13, timestamp=40000, dropped=2))
        q.observe(sample_record(3, scan=13, timestamp=40000, dropped=2))
        q.observe(sample_record(2, scan=12, timestamp=30000, dropped=2))
        q.observe({"type": "metadata", "packet_seq": 0, "boot_id": 43})
        q.observe(sample_record(1, scan=0, timestamp=100, boot=43))
        s = q.status()
        self.assertEqual(s["packet_gaps"], 1)
        self.assertEqual(s["scan_gaps"], 2)
        self.assertEqual(s["packet_duplicates"], 1)
        self.assertEqual(s["scan_duplicates"], 1)
        self.assertEqual(s["packet_regressions"], 1)
        self.assertEqual(s["scan_regressions"], 1)
        self.assertEqual(s["timestamp_regressions"], 2)
        self.assertEqual(s["boot_changes"], 1)
        self.assertEqual(s["device_dropped_scans"], 2)
        self.assertEqual(s["boot_ids"], [42, 43])
        self.assertFalse(s["missing_metadata"])

    def test_initial_drops_are_separate_from_losses_during_capture(self):
        q = CaptureQuality()
        q.observe(sample_record(100, scan=900, dropped=123))
        q.observe(sample_record(101, scan=901, timestamp=20000, dropped=123))
        self.assertEqual(q.status()["device_dropped_scans"], 0)
        self.assertEqual(q.status()["initial_device_dropped_scans"], 123)
        q.observe(sample_record(102, scan=905, timestamp=30000, dropped=126))
        self.assertEqual(q.status()["device_dropped_scans"], 3)
        self.assertEqual(q.status()["initial_device_dropped_scans_by_boot"], {"42": 123})

    def test_missing_required_pads_even_when_some_are_registered(self):
        q = CaptureQuality()
        q.observe(sample_record(mask=0x1ffc))
        self.assertEqual(q.status()["missing_required_pad_samples"], 1)
        q.observe({"type": "metadata", "packet_seq": 2, "board_pad_mask": 0x1ffc})
        q.observe(sample_record(3, scan=11, timestamp=20000, mask=0x1ffc))
        self.assertEqual(q.status()["missing_required_pad_samples"], 1)

    def test_uint32_wrap_and_measurement_validity(self):
        q = CaptureQuality()
        q.observe(sample_record(0xffffffff, scan=0xffffffff))
        q.observe(sample_record(0, scan=0, timestamp=20000))
        row = sample_record(1, scan=1, timestamp=30000)
        row["raw_valid_mask"] = 0x7ffc
        q.observe(row)
        s = q.status()
        self.assertEqual(s["scan_regressions"], 0)
        self.assertEqual(s["packet_regressions"], 0)
        self.assertEqual(s["scan_gaps"], 0)
        self.assertEqual(s["invalid_raw_samples"], 1)
        self.assertEqual(s["invalid_smooth_samples"], 0)
        self.assertEqual(s["measured_hz"], 100)


class FakeSerial:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.incoming = queue.Queue()
        self.sent = []
        self.wire = bytearray()
        self.closed = False
        self.opened = False
        self.sequence = 0
        self.fail_reads = False

    def open(self):
        self.opened = True

    def write(self, data):
        self.sent.append(data)
        if data == b"HELLO\n":
            payload = encode_packet(1, {"boot_id": 42, "firmware": "synthetic-test"}, 0)
            payload += encode_packet(2, sample_payload(), 1)
            self.sequence = 2
        elif data == b"STOP\n":
            return len(data)
        else:
            token = data.decode().strip().split(" ", 1)[1]
            own_start = token.startswith("capture-start-")
            payload = encode_packet(3, {"token": token, "device_us": 20000 if own_start else 30000,
                                       "scan_seq": 10 if own_start else 11, "boot_id": 42}, self.sequence)
            self.sequence += 1
            if own_start:
                payload += encode_packet(2, sample_payload(timestamp=20000, scan=11), self.sequence)
                self.sequence += 1
        self.wire.extend(payload)
        self.incoming.put(payload)
        return len(data)

    def read(self, count):
        if self.fail_reads:
            raise IOError("synthetic disconnect")
        try:
            return self.incoming.get(timeout=0.01)
        except queue.Empty:
            return b""

    def cancel_read(self):
        self.incoming.put(b"")

    def close(self):
        self.closed = True


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "session"
        self.fake = FakeSerial()
        self.session = CaptureSession(serial_factory=self.factory)

    def factory(self, **kwargs):
        self.fake.kwargs = kwargs
        return self.fake

    def tearDown(self):
        self.session.stop()
        self.tmp.cleanup()

    def wait_until(self, predicate):
        end = time.monotonic() + 2
        while not predicate():
            if time.monotonic() > end:
                self.fail("Timed out waiting for synthetic capture")
            time.sleep(0.005)

    def test_capture_archives_original_bytes_markers_and_provenance(self):
        self.session.start("synthetic", self.path, {"board": "50mm"})
        self.wait_until(lambda: self.session.status()["samples"] == 1)
        token = self.session.mark("trial_1.begin")
        ack = self.session.wait_for_marker(token)
        self.assertEqual(ack["device_us"], 30000)
        state = self.session.stop()
        self.assertFalse(state["running"])
        self.assertEqual(state["metadata"], {"board": "50mm"})
        self.assertTrue(state["quality"]["clean"], state["quality"]["issues"])
        self.assertEqual((self.path / "wire.bin").read_bytes(), bytes(self.fake.wire))
        frames = [json.loads(line) for line in (self.path / "frames.jsonl").read_text().splitlines()]
        self.assertEqual([r["type"] for r in frames], ["metadata", "sample", "marker", "sample", "marker"])
        self.assertEqual([r["capture_phase"] for r in frames], ["startup", "startup", "recording", "recording", "recording"])
        report = json.loads((self.path / "session.json").read_text())
        self.assertEqual(report["samples"], 1)
        self.assertTrue(self.fake.closed)
        self.assertTrue(self.fake.dtr)
        self.assertFalse(self.fake.rts)
        self.assertEqual(self.fake.kwargs["port"], None)
        self.assertEqual(self.fake.sent[0], b"HELLO\n")
        self.assertTrue(self.fake.sent[1].startswith(b"MARK capture-start-"))
        self.assertEqual(self.fake.sent[2:], [b"MARK trial_1.begin\n", b"STOP\n"])
        self.assertIsNotNone(state["capture_start_ack"])
        self.assertEqual(state["startup_samples"], 1)
        # Returned status must not expose mutable live state to the GUI.
        state["marker_acks"].clear()
        self.assertIn(token, self.session.status()["marker_acks"])

    def test_expected_attach_preamble_and_partial_stop_do_not_fail_quality(self):
        self.fake.incoming.put(b"startup console text\n" + encode_packet(2, sample_payload())[50:])
        self.session.start("synthetic", self.path)
        self.wait_until(lambda: self.session.status()["samples"] == 1)
        tail = encode_packet(2, sample_payload())[:30]
        self.fake.incoming.put(tail)
        self.wait_until(lambda: self.session.status()["quality"]["decoder"]["buffered_bytes"] == 30)
        state = self.session.stop()
        self.assertTrue(state["quality"]["clean"], state["quality"]["issues"])
        self.assertGreater(state["quality"]["decoder_total"]["startup_skipped_bytes"], 0)
        self.assertEqual(state["quality"]["decoder"]["stream_skipped_bytes"], 0)
        self.assertEqual(state["quality"]["decoder"]["trailing_bytes"], 30)

    def test_startup_backlog_and_post_ack_old_samples_are_archived_not_trained(self):
        original_write = self.fake.write
        def write(data):
            if not data.startswith(b"MARK capture-start-"):
                return original_write(data)
            self.fake.sent.append(data)
            token = data.decode().strip().split(" ", 1)[1]
            # A large pre-attach gap is followed by the live marker. Firmware then
            # drains two old queued scans before providing the first eligible scan.
            wire = encode_packet(2, sample_payload(timestamp=100000, scan=400, dropped=389), 450)
            wire += encode_packet(3, {"token": token, "device_us": 110000,
                                     "scan_seq": 402, "boot_id": 42}, 451)
            wire += encode_packet(2, sample_payload(timestamp=101000, scan=401, dropped=389), 452)
            wire += encode_packet(2, sample_payload(timestamp=102000, scan=402, dropped=389), 453)
            wire += encode_packet(2, sample_payload(timestamp=110000, scan=403, dropped=389), 454)
            wire += encode_packet(2, sample_payload(timestamp=120000, scan=404, dropped=389), 455)
            self.fake.wire.extend(wire)
            self.fake.incoming.put(wire)
            return len(data)
        self.fake.write = write
        self.session.start("synthetic", self.path)
        self.wait_until(lambda: self.session.status()["samples"] == 2)
        status = self.session.stop()
        self.assertEqual(status["startup_samples"], 4)
        self.assertEqual(status["latest_sample"]["scan_seq"], 404)
        self.assertEqual(status["quality"]["packet_gaps"], 0)
        self.assertEqual(status["quality"]["scan_gaps"], 0)
        self.assertEqual(status["quality"]["device_dropped_scans"], 0)
        self.assertEqual(status["quality"]["initial_device_dropped_scans"], 389)
        self.assertTrue(status["quality"]["clean"], status["quality"]["issues"])
        self.assertFalse(status["marker_pending"])
        self.assertEqual((self.path / "wire.bin").read_bytes(), bytes(self.fake.wire))
        rows = [json.loads(line) for line in (self.path / "frames.jsonl").read_text().splitlines()]
        active = [r for r in rows if r["type"] == "sample" and r["capture_phase"] == "recording"]
        self.assertEqual([r["scan_seq"] for r in active], [403, 404])

    def test_missing_start_ack_has_bounded_failure_and_zero_training_samples(self):
        original_write = self.fake.write
        def write(data):
            if data.startswith(b"MARK capture-start-"):
                self.fake.sent.append(data)
                return len(data)
            return original_write(data)
        self.fake.write = write
        self.session.start("synthetic", self.path)
        # Shorten the deadline in the fixture; production uses exactly five seconds.
        self.session._handshake_deadline = time.monotonic() + 0.03
        self.wait_until(lambda: not self.session.status()["running"])
        status = self.session.stop()
        self.assertEqual(status["samples"], 0)
        self.assertEqual(status["startup_samples"], 1)
        self.assertFalse(status["ready"])
        self.assertTrue(any("synchronization timed out" in error for error in status["errors"]))

    def test_metadata_is_required_even_when_start_marker_acknowledges(self):
        original_write = self.fake.write
        def write(data):
            if data == b"HELLO\n":
                self.fake.sent.append(data)
                return len(data)
            return original_write(data)
        self.fake.write = write
        self.session.start("synthetic", self.path)
        self.wait_until(lambda: not self.session.status()["running"])
        status = self.session.stop()
        self.assertEqual(status["samples"], 0)
        self.assertTrue(status["quality"]["missing_metadata"])
        self.assertTrue(any("no matching firmware metadata" in error for error in status["errors"]))

    def test_post_ack_corruption_in_same_read_is_not_hidden_as_startup(self):
        original_write = self.fake.write
        def write(data):
            if not data.startswith(b"MARK capture-start-"):
                return original_write(data)
            self.fake.sent.append(data)
            token = data.decode().strip().split(" ", 1)[1]
            ack = encode_packet(3, {"token": token, "device_us": 20000,
                                   "scan_seq": 10, "boot_id": 42}, 2)
            bad = bytearray(encode_packet(2, sample_payload(timestamp=20000, scan=11), 3))
            bad[30] ^= 1
            good = encode_packet(2, sample_payload(timestamp=30000, scan=12), 4)
            wire = ack + bad + good
            self.fake.wire.extend(wire)
            self.fake.incoming.put(wire)
            return len(data)
        self.fake.write = write
        self.session.start("synthetic", self.path)
        self.wait_until(lambda: self.session.status()["samples"] == 1)
        status = self.session.stop()
        self.assertEqual(status["quality"]["decoder"]["crc_errors"], 1)
        self.assertEqual(status["quality"]["packet_gaps"], 1)
        self.assertFalse(status["quality"]["clean"])

    def test_reboot_after_boundary_is_an_explicit_failure(self):
        self.session.start("synthetic", self.path)
        self.wait_until(lambda: self.session.status()["samples"] == 1)
        self.fake.incoming.put(encode_packet(2, sample_payload(timestamp=21000, scan=12, boot=43), 4))
        self.wait_until(lambda: not self.session.status()["running"])
        status = self.session.stop()
        self.assertEqual(status["samples"], 1)
        self.assertTrue(any("boot changed" in error for error in status["errors"]))

    def test_existing_directory_is_never_overwritten(self):
        self.path.mkdir()
        sentinel = self.path / "wire.bin"
        sentinel.write_bytes(b"original")
        with self.assertRaises(FileExistsError):
            self.session.start("synthetic", self.path)
        self.assertEqual(sentinel.read_bytes(), b"original")
        self.assertFalse(self.fake.opened)

    def test_bad_and_duplicate_marker_tokens_rejected(self):
        self.session.start("synthetic", self.path)
        for token in ("", "bad\nHELLO", "bad space", "x" * 81):
            with self.assertRaises(ValueError):
                self.session.mark(token)
        self.session.mark("unique")
        with self.assertRaises(ValueError):
            self.session.mark("unique")

    def test_disconnect_closes_and_reports_incomplete_capture(self):
        self.fake.fail_reads = True
        self.session.start("synthetic", self.path)
        self.wait_until(lambda: not self.session.status()["running"])
        state = self.session.stop()
        self.assertTrue(self.fake.closed)
        self.assertTrue(state["errors"])
        self.assertTrue(state["quality"]["missing_metadata"])
        self.assertFalse(state["quality"]["clean"])
        self.assertTrue((self.path / "session.json").exists())

    def test_open_failure_preserves_failure_report_and_closes(self):
        def bad_open():
            raise PermissionError("synthetic permission failure")
        self.fake.open = bad_open
        with self.assertRaises(PermissionError):
            self.session.start("synthetic", self.path)
        self.assertTrue(self.fake.closed)
        report = json.loads((self.path / "session.json").read_text())
        self.assertFalse(report["running"])
        self.assertTrue(report["errors"])


if __name__ == "__main__":
    unittest.main()
