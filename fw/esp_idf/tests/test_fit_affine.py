"""Historical fitter must not turn ambiguous contact counts into shifted labels."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fit_affine


class AffineInputTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def log(self, name, points, release=True, contact_samples=3):
        path = self.root / name
        lines = ["boot chatter", "centroid (x,y,z)x1e3 = (0, 0, 0)"]
        for x, y in points:
            lines.extend(f"centroid (x,y,z)x1e3 = ({round(x * 1000)}, {round(y * 1000)}, 3000)"
                         for _ in range(contact_samples))
            lines.append("centroid (x,y,z)x1e3 = (0, 0, 0)")
        if not release:
            lines.pop()
        path.write_text("\n".join(lines) + "\n")
        return path

    def collect(self, paths, repeat=1):
        return fit_affine.collect_correspondences(paths, fit_affine.expected_targets(taps_per_target=repeat), 2, 1, 3)

    def test_default_centres_match_detector_rounding(self):
        targets = fit_affine.expected_targets()
        self.assertEqual(targets, [(float(x), float(y)) for y in range(4) for x in range(4)])
        self.assertEqual(targets[0], (0, 0))
        self.assertEqual(targets[-1], (3, 3))
        self.assertEqual(fit_affine.parse_args(["unused.log"]).taps_per_target, 1)

    def test_two_taps_per_target_uses_all_32_contacts_with_correct_labels(self):
        targets = fit_affine.expected_targets(taps_per_target=2)
        measured = [(x + (i % 2) * 0.1, y + 0.2) for i, (x, y) in enumerate(targets)]
        path = self.log("double.log", measured)
        sources, labels, origins = self.collect([path], repeat=2)
        self.assertEqual(len(sources), len(measured))
        for source, point in zip(sources, measured):
            for actual, expected in zip(source, point):
                self.assertAlmostEqual(actual, expected)
        self.assertEqual(labels, targets)
        self.assertEqual(labels[:4], [(0, 0), (0, 0), (1, 0), (1, 0)])
        self.assertEqual(labels[-2:], [(3, 3), (3, 3)])
        self.assertEqual(origins[-1], (str(path), 32))
        with self.assertRaisesRegex(ValueError, "found 32 complete contacts, expected exactly 16"):
            self.collect([path])

    def test_each_file_receives_a_complete_independent_target_sequence(self):
        targets = fit_affine.expected_targets()
        first = self.log("first.log", targets)
        second_points = [(x + 0.1, y + 0.2) for x, y in targets]
        second = self.log("second.log", second_points)
        sources, labels, origins = self.collect([first, second])
        self.assertEqual(len(sources), 32)
        self.assertEqual(labels, targets * 2)
        self.assertEqual(origins[16], (str(second), 1))
        self.assertAlmostEqual(sources[16][0], 0.1)

    def test_complementary_incomplete_files_cannot_be_concatenated_into_labels(self):
        targets = fit_affine.expected_targets()
        first = self.log("first-half.log", targets[:8])
        second = self.log("second-half.log", targets[8:])
        with self.assertRaisesRegex(ValueError, "found 8 complete contacts, expected exactly 16"):
            self.collect([first, second])

    def test_missing_or_extra_contacts_abort_before_fitting(self):
        targets = fit_affine.expected_targets()
        for count in (0, 15, 17):
            points = (targets + [(0, 0)])[:count]
            path = self.log(f"count-{count}.log", points)
            with self.subTest(count=count), patch.object(fit_affine, "affine_fit") as fit:
                with self.assertRaisesRegex(SystemExit, "expected exactly 16"):
                    fit_affine.main([str(path)])
                fit.assert_not_called()

    def test_unterminated_eof_contact_is_not_a_valid_last_tap(self):
        path = self.log("truncated.log", fit_affine.expected_targets(), release=False)
        with self.assertRaisesRegex(ValueError, "Contact 16 is unterminated"):
            self.collect([path])

    def test_short_extra_contact_is_rejected_instead_of_shifting_labels(self):
        samples = [(0, 0, 0), (0, 0, 3), (0, 0, 0)]
        for x, y in fit_affine.expected_targets():
            samples.extend([(x, y, 3)] * 3 + [(0, 0, 0)])
        with self.assertRaisesRegex(ValueError, "Contact 1 has only 1 samples"):
            fit_affine.detect_taps(samples, 2, 1, 3)

    def test_malformed_expected_pair_is_never_skipped(self):
        for spec in ("", "0:0,bad,1:1", "0:0,", "1:2:3", "nan:0", "0:inf", "a:1"):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                fit_affine.expected_targets(spec)
        self.assertEqual(fit_affine.expected_targets("0:0,1.25:2", 2), [(0, 0), (0, 0), (1.25, 2), (1.25, 2)])

    def test_malformed_centroid_and_invalid_encoding_are_rejected(self):
        path = self.root / "bad.log"
        path.write_text("unrelated console\ncentroid (x,y,z)x1e3 = (0, nope, 0)\n")
        with self.assertRaisesRegex(ValueError, "bad.log:2: malformed centroid"):
            fit_affine.load_centroids(path)
        path.write_bytes(b"\xff\n")
        with self.assertRaises(UnicodeDecodeError):
            fit_affine.load_centroids(path)

    def test_invalid_thresholds_and_repetition_are_cli_errors(self):
        for flags in (["--taps-per-target", "0"], ["--min-samples", "0"],
                      ["--z-on", "nan"], ["--z-on", "1", "--z-off", "2"]):
            with self.subTest(flags=flags), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                fit_affine.parse_args(["unused.log", *flags])

    def test_direct_fit_refuses_mismatched_pair_lengths(self):
        with self.assertRaises(ValueError):
            fit_affine.affine_fit([(0, 0), (1, 0), (0, 1)], [(0, 0), (1, 0)])


if __name__ == "__main__":
    unittest.main()
