"""Host regression tests; synthetic traces test software, not sensor accuracy."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import replay_capture as replay


def metadata(boot=123, charge_times=800):
    return {"type": "metadata", "boot_id": boot, "protocol_version": 1,
            "capture_decimation": 1, "pad_ids": list(range(15)),
            "project": "swipe", "mode": "diagnostic", "board": "capkey_6x6_50mm",
            "acquisition": {"charge_times": charge_times}}


def sample(timestamp, scan, deltas=None, boot=123):
    deltas = deltas or {}
    smooth = [20000 + deltas.get(pad, 0) for pad in range(15)]
    return {"type": "sample", "timestamp_us": timestamp, "scan_seq": scan,
            "dropped_scans": 0, "snapshot_duration_us": 30, "boot_id": boot,
            "registered_mask": 0x7FFE, "raw_valid_mask": 0x7FFE,
            "smooth_valid_mask": 0x7FFE, "benchmark_valid_mask": 0x7FFE,
            "raw": smooth[:], "smooth": smooth, "benchmark": [20000] * 15}


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.host, cls.source_hash = replay.build_host(Path(cls.temp.name) / "build")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_records(self, records, mode="legacy", policy="error"):
        path = Path(self.temp.name) / "frames.jsonl"
        sequence_by_boot = {}
        with path.open("w") as out:
            for record in records:
                record = dict(record)
                boot = record["boot_id"]
                packet = sequence_by_boot.get(boot, 0)
                record.setdefault("packet_seq", packet)
                sequence_by_boot[boot] = (record["packet_seq"] + 1) & replay.U32_MAX
                out.write(json.dumps(record) + "\n")
        results = []
        replay.replay(path, mode, policy, results.append, self.host, self.source_hash)
        return results

    def test_tap_and_mapped_action_with_complete_release(self):
        records = [metadata(), sample(0, 0), sample(20000, 1, {11: 6000, 1: 6000}),
                   sample(40000, 2, {11: 6000, 1: 6000}), sample(60000, 3), sample(80000, 4)]
        for mode in ("legacy", "pcb"):
            with self.subTest(mode=mode):
                out = self.run_records(records, mode)
                gestures = [r["gesture"] for r in out if r.get("gesture")]
                self.assertEqual(len(gestures), 1)
                event = gestures[0]
                self.assertEqual((event["grid"], event["type"], event["direction"]), (0, 1, 0))
                self.assertEqual(event["action"], {"type": "char", "value": "a"})
                self.assertTrue(out[-1]["continuous"])

    def test_east_swipe_uses_shared_detector_and_binding(self):
        for mode, second_x_pad in (("legacy", 2), ("pcb", 9)):
            with self.subTest(mode=mode):
                out = self.run_records([
                    metadata(), sample(0, 0), sample(20000, 1, {11: 6000, 1: 6000}),
                    sample(40000, 2, {11: 6000, 1: 6000}),
                    sample(60000, 3, {second_x_pad: 6000, 1: 6000}), sample(80000, 4)], mode)
                event = next(r["gesture"] for r in out if r.get("gesture"))
                self.assertEqual((event["grid"], event["type"], event["direction"]), (0, 3, 3))
                self.assertEqual(event["action"]["value"], "-")

    def test_trial_marker_does_not_reset_pending_onset(self):
        out = self.run_records([
            metadata(), sample(0, 0), sample(20000, 1, {11: 6000, 1: 6000}),
            {"type": "marker", "boot_id": 123, "token": "trial-2", "device_us": 30000, "scan_seq": 1},
            sample(40000, 2, {11: 6000, 1: 6000}), sample(60000, 3)])
        # Resetting at the marker would discard the first active scan and miss
        # this two-scan tap. Trial labels cannot alter detector state.
        self.assertEqual(out[-1]["gesture_events"], 1)
        self.assertEqual(out[-1]["detector_resets"], 0)
        self.assertEqual(sum(r["type"] == "marker" for r in out), 1)

    def test_reboot_resets_but_does_not_merge_traces(self):
        out = self.run_records([
            metadata(), sample(0, 0), sample(20000, 1, {11: 6000, 1: 6000}),
            metadata(456), sample(0, 0, boot=456),
            sample(20000, 1, {11: 6000, 1: 6000}, boot=456),
            sample(40000, 2, {11: 6000, 1: 6000}, boot=456), sample(60000, 3, boot=456)])
        self.assertEqual(out[-1]["gesture_events"], 1)
        self.assertEqual(out[-1]["detector_resets"], 1)

    def test_scan_gap_is_fatal_unless_explicitly_segmented(self):
        records = [metadata(), sample(0, 0), sample(20000, 2)]
        with self.assertRaisesRegex(replay.ReplayError, "scan sequence"):
            self.run_records(records)
        out = self.run_records(records, policy="reset")
        self.assertFalse(out[-1]["continuous"])
        self.assertEqual(out[-1]["detector_resets"], 1)

    def test_missing_channel_and_invalid_raw_are_not_silently_zero_filled(self):
        for field in ("registered_mask", "raw_valid_mask", "smooth_valid_mask", "benchmark_valid_mask"):
            with self.subTest(field=field):
                frame = sample(0, 0)
                frame[field] &= ~(1 << 12)
                with self.assertRaisesRegex(replay.ReplayError, "missing required"):
                    self.run_records([metadata(), frame])
                out = self.run_records([metadata(), frame, sample(20000, 1)], policy="reset")
                self.assertEqual(out[-1]["skipped_invalid_samples"], 1)

    def test_u32_scan_and_detector_timestamp_wrap(self):
        start = (1 << 32) - 10000
        out = self.run_records([
            metadata(), sample(start, replay.U32_MAX - 1),
            sample(start + 20000, replay.U32_MAX, {11: 6000, 1: 6000}),
            sample(start + 40000, 0, {11: 6000, 1: 6000}), sample(start + 60000, 1)])
        self.assertEqual(out[-1]["gesture_events"], 1)
        self.assertTrue(out[-1]["continuous"])
        self.assertEqual([r for r in out if r["type"] == "sample_result"][-1]["timestamp_us"], start + 60000)

    def test_negative_release_tail_modes_are_distinct(self):
        records = [metadata(), sample(0, 0, {11: -6000, 1: -6000})]
        legacy = next(r for r in self.run_records(records) if r["type"] == "sample_result")
        pcb = next(r for r in self.run_records(records, "pcb") if r["type"] == "sample_result")
        self.assertEqual(legacy["z"], 1.5)
        self.assertEqual(pcb["z"], 0)

    def test_isolated_active_scan_does_not_emit_a_gesture(self):
        out = self.run_records([
            metadata(), sample(0, 0), sample(20000, 1, {11: 6000, 1: 6000}),
            sample(40000, 2), sample(60000, 3, {11: 6000, 1: 6000}),
            sample(80000, 4)], "pcb")
        self.assertEqual(out[-1]["gesture_events"], 0)

    def test_synthetic_corner_onset_and_first_crossing_duration(self):
        # Generated landing drift: the first scan rounds to row 2,
        # while the following active scans occupy row 1.
        source = Path(self.temp.name) / "onset_regression.cpp"
        source.write_text(r'''
#include "gestureDetector.h"
#include <cmath>
int main() {
    GestureDetector detector;
    if (detector.update(.15f,.6f,2,0)) return 1;
    if (detector.update(.15f,.2f,2,20000)) return 2;
    if (detector.startGrid()!=0 || std::fabs(detector.startY()-.2f)>1e-6f) return 3;
    if (detector.update(.15f,.18f,2,40000)) return 4;
    if (!detector.update(0,0,0,60000)) return 5;
    auto event=detector.getDetectedGesture();
    if (event.type!=GESTURE_TAP || event.grid_position!=0) return 6;
    detector.reset();
    detector.update(1.2f,1.2f,2,0);
    detector.update(1.2f,1.2f,2,19000);
    if (!detector.update(0,0,0,500000)) return 7;
    if (detector.getDetectedGesture().type!=GESTURE_HOLD) return 8;
    return 0;
}
''')
        executable = source.with_suffix("")
        subprocess.run(["c++", "-std=c++17", "-O2", "-I", str(ROOT / "main"),
                        "-I", str(ROOT / "tools/include"), str(source),
                        str(ROOT / "main/gestureDetector.cpp"), str(ROOT / "main/keyMap.cpp"),
                        "-o", str(executable)], check=True)
        subprocess.run([str(executable)], check=True)

    def test_charge_time_normalization_preserves_equivalent_tap_and_floor(self):
        for mode in ("legacy", "pcb"):
            with self.subTest(mode=mode):
                out = self.run_records([
                    metadata(charge_times=200), sample(0, 0),
                    sample(20000, 1, {11: 1500, 1: 1500}),
                    sample(40000, 2, {11: 1500, 1: 1500}), sample(60000, 3),
                    sample(80000, 4, {11: 300, 1: 100})], mode)
                points = [record for record in out if record["type"] == "sample_result"]
                self.assertEqual(points[1]["z"], 1.5)
                self.assertEqual(points[1]["charge_times"], 200)
                self.assertEqual(points[1]["reference_charge_times"], 800)
                self.assertEqual(points[1]["delta_scale"], 4)
                self.assertEqual(points[1]["normalization_source"], "acquisition_metadata")
                self.assertAlmostEqual(points[4]["z"], 0.2, places=6)
                event = points[3]["gesture"]
                self.assertEqual((event["grid"], event["type"], event["direction"]), (0, 1, 0))
                self.assertEqual(event["action"]["value"], "a")
                self.assertEqual(out[0]["normalization"]["per_boot"][0]["charge_times"], 200)

    def test_charge_time_configuration_changes_only_with_recorded_boot(self):
        out = self.run_records([
            metadata(), sample(0, 0), sample(20000, 1, {11: 6000, 1: 6000}),
            sample(40000, 2, {11: 6000, 1: 6000}), sample(60000, 3),
            metadata(456, 200), sample(0, 0, boot=456),
            sample(20000, 1, {11: 1500, 1: 1500}, boot=456),
            sample(40000, 2, {11: 1500, 1: 1500}, boot=456), sample(60000, 3, boot=456)])
        self.assertEqual(out[-1]["gesture_events"], 2)
        self.assertEqual(out[-1]["detector_resets"], 1)
        points = [record for record in out if record["type"] == "sample_result"]
        self.assertEqual([record["charge_times"] for record in points], [800] * 4 + [200] * 4)

    def test_missing_legacy_charge_time_is_explicitly_assumed(self):
        old_metadata = metadata()
        del old_metadata["acquisition"]
        out = self.run_records([old_metadata, sample(0, 0)])
        notices = [record for record in out if record.get("reason") == "missing_charge_times_assumed_800"]
        self.assertEqual(len(notices), 1)
        self.assertEqual(out[0]["normalization"]["per_boot"][0]["source"], "assumed_legacy_v1_default")

    def test_invalid_charge_times_cannot_silently_fall_back(self):
        for value in (0, -1, True, "200", 200.0, None, 1 << 32):
            with self.subTest(value=value):
                with self.assertRaisesRegex(replay.ReplayError, "charge_times"):
                    self.run_records([metadata(charge_times=value), sample(0, 0)])

    def test_sparse_legacy_log_and_metadata_absence_are_rejected(self):
        path = Path(self.temp.name) / "legacy.log"
        path.write_text("I (999) gesture: raw channels: [1,2,3,4,5,6,7,8,9,10,11,12]\n")
        with self.assertRaisesRegex(replay.ReplayError, "legacy text logs"):
            replay.capture_metadata(path)
        path.write_text(json.dumps(sample(0, 0)) + "\n")
        with self.assertRaisesRegex(replay.ReplayError, "missing diagnostic metadata"):
            replay.capture_metadata(path)

    def test_backward_timestamp_and_packet_loss_are_rejected(self):
        with self.assertRaisesRegex(replay.ReplayError, "non-increasing timestamp"):
            self.run_records([metadata(), sample(20, 0), sample(10, 1)])
        frame = sample(20, 1)
        frame["packet_seq"] = 3
        with self.assertRaisesRegex(replay.ReplayError, "packet sequence"):
            self.run_records([metadata(), sample(0, 0), frame])

    def test_source_identity_is_recorded(self):
        out = self.run_records([metadata(), sample(0, 0)])
        self.assertEqual(out[0]["host_build_sha256"], self.source_hash)
        self.assertEqual(len(out[0]["input_sha256"]), 64)
        self.assertFalse(out[0]["trial_markers_reset_detector"])

    def test_explicit_startup_prefix_is_excluded_and_metadata_can_seed_recording(self):
        stale_meta = dict(metadata(99), capture_phase="startup", protocol_version=999,
                          packet_seq=1000, pad_ids=[])
        stale_sample = {"type": "sample", "boot_id": 99, "capture_phase": "startup",
                        "packet_seq": 999999}  # Fields intentionally unusable.
        provenance = dict(metadata(), capture_phase="startup", packet_seq=2000)
        ack = {"type": "marker", "boot_id": 123, "capture_phase": "recording",
               "packet_seq": 2001, "token": "capture-start-test", "device_us": 1000000,
               "scan_seq": 99}
        backlog = dict(sample(900000, 98), capture_phase="startup", packet_seq=2002)
        active = [dict(sample(1000000, 100), capture_phase="recording", packet_seq=2003),
                  dict(sample(1020000, 101, {11: 6000, 1: 6000}), capture_phase="recording"),
                  dict(sample(1040000, 102, {11: 6000, 1: 6000}), capture_phase="recording"),
                  dict(sample(1060000, 103), capture_phase="recording")]
        out = self.run_records([stale_meta, stale_sample, provenance, ack, backlog, *active])
        self.assertEqual(out[-1]["samples"], 4)
        self.assertEqual(out[-1]["gesture_events"], 1)
        self.assertTrue(out[-1]["continuous"])
        self.assertEqual(out[-1]["startup_records_skipped"], 4)
        self.assertEqual(out[-1]["startup_records_by_type"], {"metadata": 2, "sample": 2})
        self.assertEqual(out[0]["capture_metadata"][0]["boot_id"], 123)
        self.assertEqual(out[-1]["detector_resets"], 0)

    def test_recording_requires_its_own_boot_metadata(self):
        with self.assertRaisesRegex(replay.ReplayError, "missing diagnostic metadata"):
            self.run_records([dict(metadata(99), capture_phase="startup"), sample(0, 0)])

    def test_startup_cannot_hide_mid_recording_loss(self):
        with self.assertRaisesRegex(replay.ReplayError, "startup record after recording"):
            self.run_records([metadata(), sample(0, 0),
                              dict(sample(20000, 1), capture_phase="startup"), sample(40000, 2)])
        with self.assertRaisesRegex(replay.ReplayError, "unknown capture_phase"):
            self.run_records([metadata(), dict(sample(0, 0), capture_phase="discard")])


    def test_legacy_float_regression_and_invalid_core_mask(self):
        # Compile an independent copy of the old 12-channel calculation and
        # compare exact float values over signed and large random inputs.
        source = Path(self.temp.name) / "legacy_reference.cpp"
        source.write_text(r'''
#include "touch_processing.h"
#include <cmath>
#include <cstdint>
#include <cstdio>
int main() {
    const int pads[] = {1,2,12,4,5,6,7,8,9,10,11,3};
    const int axes[2][6] = {{10,1,7,11,5,3}, {0,8,2,9,4,6}};
    const float positions[] = {0,.8f,1.6f,2.4f,3.2f,4};
    uint32_t state = 0x12345678;
    for (int test = 0; test < 10000; ++test) {
        int32_t physical[15] = {};
        float magnitude[12], expected[3] = {}, total = 0;
        for (int i=0; i<12; ++i) {
            state = 1664525 * state + 1013904223;
            physical[pads[i]] = static_cast<int32_t>(state);
            if (test < 20) physical[pads[i]] %= 100;
            magnitude[i] = std::fabs(static_cast<float>(physical[pads[i]]));
            total += magnitude[i];
        }
        if (total >= 1500) {
            for (int axis=0; axis<2; ++axis) {
                float sum=0, weighted=0;
                for (int i=0; i<6; ++i) {
                    const float value=magnitude[axes[axis][i]];
                    sum += value;
                    weighted += value*positions[i];
                }
                float value=sum < 1e-3f ? 0 : weighted/sum;
                if (value < 0) value=0;
                if (value > 4) value=4;
                expected[axis]=value;
            }
            expected[2]=total/8000.0f;
        }
        auto actual=swipe::processTouch(physical, 0x1ffe);
        if (!actual.valid || actual.x!=expected[0] || actual.y!=expected[1] || actual.z!=expected[2]) return 1;
        if (swipe::processTouch(physical, 0x1ffa).valid) return 2;
    }
    if (swipe::processTouch(nullptr, 0x1ffe).valid) return 3;
    int32_t zero[15] = {};
    return swipe::processTouch(zero, 0x1ffe, swipe::TouchProcessingMode::Legacy, 0).valid ? 4 : 0;
}
''')
        executable = source.with_suffix("")
        subprocess.run(["c++", "-std=c++17", "-O2", "-I", str(ROOT / "main"), str(source),
                        str(ROOT / "main/touch_processing.cpp"), "-o", str(executable)], check=True)
        subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
