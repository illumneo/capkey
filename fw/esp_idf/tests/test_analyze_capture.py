import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analyze_capture import analyze_session


class AnalyzeCaptureTests(unittest.TestCase):
    def fixture(self, path):
        metadata = {"type": "metadata", "capture_phase": "startup", "boot_id": 42,
                    "acquisition": {"charge_times": 200, "benchmark_filter": "IIR4"}}
        sample = {"type": "sample", "capture_phase": "recording", "boot_id": 42,
                  "registered_mask": 0x1ffe, "raw_valid_mask": 0x1ffe,
                  "smooth_valid_mask": 0x1ffe, "benchmark_valid_mask": 0x1ffe,
                  "snapshot_duration_us": 100}
        rows = [metadata, dict(sample, capture_phase="startup", timestamp_us=0, scan_seq=0,
                               raw=[10**9]*15, smooth=[10**9]*15, benchmark=[0]*15)]
        for i in range(5):
            rows.append(dict(sample, timestamp_us=(i+1)*10000, scan_seq=i+1,
                             raw=[1000+2*i]*15, smooth=[1010+2*i]*15, benchmark=[1000]*15))
        # One invalid raw read must not pollute that pad's raw/delta statistics.
        rows[-1]["raw_valid_mask"] &= ~(1 << 2)
        (path / "frames.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
        (path / "session.json").write_text(json.dumps({"quality": {"clean": True, "issues": []}}))

    def test_statistics_phase_exclusion_and_measurement_masks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            self.fixture(path)
            report = analyze_session(path)
            self.assertEqual(report["condition"], "unlabeled")
            self.assertEqual(report["record_counts"]["excluded_samples_startup"], 1)
            self.assertEqual(report["record_counts"]["recording_samples_analyzed"], 5)
            self.assertEqual(report["timing"]["median_scan_hz"], 100)
            self.assertEqual(report["gpio"]["1"]["raw"]["mean"], 1004)
            self.assertEqual(report["gpio"]["1"]["raw"]["mad"], 2)
            self.assertAlmostEqual(report["gpio"]["1"]["raw"]["fractional_mad"], 2/1004)
            self.assertEqual(report["gpio"]["1"]["raw_mad_per_charge"], .01)
            self.assertEqual(report["gpio"]["1"]["smooth_minus_benchmark"]["mean"], 14)
            self.assertEqual(report["gpio"]["2"]["raw"]["n"], 4)
            self.assertEqual(report["gpio"]["2"]["raw_minus_benchmark"]["n"], 4)
            self.assertEqual(report["gpio"]["2"]["smooth_minus_benchmark"]["n"], 5)
            self.assertEqual(report["gpio"]["13"]["raw"]["n"], 0)
            self.assertTrue(any("Unlabeled" in text for text in report["warnings"]))

    def test_confirmed_idle_is_an_explicit_caller_assertion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            self.fixture(path)
            report = analyze_session(path, confirmed_idle=True)
            self.assertEqual(report["condition"], "caller_confirmed_idle")
            self.assertTrue(any("does not verify" in text for text in report["warnings"]))

    def test_no_recording_samples_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "frames.jsonl").write_text(json.dumps({"type": "sample", "capture_phase": "startup"}))
            with self.assertRaisesRegex(ValueError, "No valid samples"):
                analyze_session(path)


if __name__ == "__main__":
    unittest.main()
