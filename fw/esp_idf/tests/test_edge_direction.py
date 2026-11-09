"""Edge assistance must preserve the observed direction of a short stroke."""
from pathlib import Path
import math
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EdgeDirectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        source = Path(cls.temp.name) / "edge_detector.cpp"
        source.write_text(r'''
#include "gestureDetector.h"
#include <iostream>
int main() {
    GestureDetector detector;
    float x, y, z;
    uint32_t timestamp;
    while (std::cin >> x >> y >> z >> timestamp) {
        if (detector.update(x, y, z, timestamp)) {
            const auto event = detector.getDetectedGesture();
            std::cout << event.type << ' ' << event.direction << ' '
                      << unsigned(event.grid_position) << '\n';
        }
    }
}
''')
        cls.host = source.with_suffix("")
        subprocess.run(["c++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-I", str(ROOT / "main"), "-I", str(ROOT / "tools/include"),
                        str(source), str(ROOT / "main/gestureDetector.cpp"),
                        str(ROOT / "main/keyMap.cpp"), "-o", str(cls.host)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def events(self, points):
        result = subprocess.run([str(self.host)], text=True, capture_output=True, check=True,
                                input="".join(" ".join(map(str, point)) + "\n"
                                              for point in points))
        return [tuple(map(int, line.split())) for line in result.stdout.splitlines()]

    @staticmethod
    def stroke(x, y, dx, dy):
        points = [(x, y, 2, 0), (x, y, 2, 20000)]
        points += [(x + dx * i / 6, y + dy * i / 6, 2, (i + 1) * 20000)
                   for i in range(1, 7)]
        return points + [(0, 0, 0, 160000)]

    def test_inward_motion_is_not_reversed_at_any_edge(self):
        # Top N, left H, right Shift, and bottom Space all have an outward
        # binding. The prior helper incorrectly forced these inward strokes
        # toward that opposite binding.
        for x, y, dx, dy, grid in ((1.2, .2, 0, 1, 1), (.2, 1.2, 1, 0, 4),
                                   (2.8, 1.2, -1, 0, 7), (1.2, 2.8, 0, -1, 13)):
            for distance in (.11, .2, .3):
                with self.subTest(grid=grid, distance=distance):
                    self.assertEqual(self.events(self.stroke(x, y, dx * distance, dy * distance)),
                                     [(1, 0, grid)])

    def test_observed_outward_motion_still_receives_edge_assistance(self):
        for x, y, dx, dy, direction, grid in ((1.2, .25, 0, -.23, 1, 1),
                                             (.25, 1.2, -.23, 0, 7, 4),
                                             (2.75, 1.2, .23, 0, 3, 7),
                                             (1.2, 2.75, 0, .23, 5, 13)):
            with self.subTest(grid=grid):
                self.assertEqual(self.events(self.stroke(x, y, dx, dy)), [(3, direction, grid)])

    def test_small_outward_drift_remains_a_tap(self):
        # Small landing/lift drift should not become punctuation.
        # The edge helper needs a meaningful excursion.
        for distance in (.11, .15, .19):
            with self.subTest(distance=distance):
                self.assertEqual(self.events(self.stroke(1.2, .25, 0, -distance)), [(1, 0, 1)])

    def test_south_motion_from_n_cannot_become_north(self):
        # Generated straight paths must retain their direction at the top edge.
        for distance in (.34, .38, .42):
            with self.subTest(distance=distance):
                self.assertEqual(self.events(self.stroke(1.2, .2, 0, distance)),
                                 [(3, 5, 1)])



    def test_coherent_short_strokes_work_in_all_bound_directions(self):
        for direction, degrees in enumerate((90, 45, 0, -45, -90, -135, 180, 135), 1):
            dx = .34 * math.cos(math.radians(degrees))
            dy = -.34 * math.sin(math.radians(degrees))
            with self.subTest(direction=direction):
                self.assertEqual(self.events(self.stroke(1.2, 1.2, dx, dy)), [(3, direction, 5)])

    def test_short_excursion_with_a_wandering_path_remains_a_tap(self):
        xy = [(1.2, 1.2), (1.2, 1.2), (1.1, 1.22), (1.3, 1.18),
              (1.15, 1.22), (1.4, 1.18), (1.54, 1.2)]
        points = [(x, y, 2, i * 20000) for i, (x, y) in enumerate(xy)]
        self.assertEqual(self.events(points + [(0, 0, 0, 160000)]), [(1, 0, 5)])

    def test_straight_short_stroke_tolerates_small_release_recoil(self):
        # A 0.40-cell outward stroke followed by 0.08-cell recoil remains a
        # short swipe. This is generated geometry, not a recorded path.
        xs = [1, 1, 1.1, 1.2, 1.3, 1.4, 1.36, 1.32]
        points = [(x, 1, 2, i * 20000) for i, x in enumerate(xs)]
        self.assertEqual(self.events(points + [(0, 0, 0, 180000)]), [(3, 3, 5)])

    def test_substantial_recoil_and_return_are_not_short_swipes(self):
        for endpoint, expected in ((1.24, (1, 0, 5)), (1.15, (5, 3, 5))):
            xs = [1, 1, 1.1, 1.2, 1.3, 1.4, endpoint]
            points = [(x, 1, 2, i * 20000) for i, x in enumerate(xs)]
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.events(points + [(0, 0, 0, 160000)]), [expected])

    def test_out_back_out_wandering_is_not_a_coherent_short_stroke(self):
        # End retention alone is insufficient: this path finishes near its
        # peak, but reverses twice and travels much farther than its excursion.
        xs = [1, 1, 1.1, 1.2, 1.3, 1.4, 1.3, 1.22, 1.28, 1.35]
        points = [(x, 1, 2, i * 20000) for i, x in enumerate(xs)]
        self.assertEqual(self.events(points + [(0, 0, 0, 220000)]), [(1, 0, 5)])

    def test_recoil_uses_peak_direction_when_tail_crosses_a_sector_boundary(self):
        # Peak is 20 degrees (east), while the shorter endpoint is 25 degrees
        # (southeast). Match the normal swipe's peak/endpoint selection rule.
        peak_angle = math.radians(20)
        end_angle = math.radians(25)
        xy = [(1, 1), (1, 1)] + [
            (1 + distance * math.cos(peak_angle), 1 + distance * math.sin(peak_angle))
            for distance in (.1, .2, .3, .4)]
        xy.append((1 + .34 * math.cos(end_angle), 1 + .34 * math.sin(end_angle)))
        points = [(x, y, 2, i * 20000) for i, (x, y) in enumerate(xy)]
        self.assertEqual(self.events(points + [(0, 0, 0, 160000)]), [(3, 3, 5)])


if __name__ == "__main__":
    unittest.main()
