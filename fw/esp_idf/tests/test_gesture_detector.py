"""Shared-detector regressions: generated synthetic geometry."""
from pathlib import Path
import math
import random
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DetectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        source = Path(cls.temp.name) / "detector.cpp"
        source.write_text(r'''
#include "gestureDetector.h"
#include <iostream>
int main() {
    GestureDetector detector;
    float x,y,z;
    uint32_t time;
    while (std::cin >> x >> y >> z >> time) {
        if (detector.update(x,y,z,time)) {
            const auto event=detector.getDetectedGesture();
            std::cout << event.type << ' ' << event.direction << ' '
                      << unsigned(event.grid_position) << '\n';
        }
    }
}
''')
        cls.host = source.with_suffix("")
        subprocess.run(["c++", "-std=c++17", "-O2", "-I", str(ROOT / "main"),
                        "-I", str(ROOT / "tools/include"), str(source),
                        str(ROOT / "main/gestureDetector.cpp"), str(ROOT / "main/keyMap.cpp"),
                        "-o", str(cls.host)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def events(self, points):
        result = subprocess.run([str(self.host)],
                                input="".join(" ".join(map(str, point)) + "\n" for point in points),
                                text=True, capture_output=True, check=True)
        return [tuple(map(int, line.split())) for line in result.stdout.splitlines()]

    def test_slow_unbound_edge_drift_within_hold_tolerance_is_a_hold(self):
        # This unbound A-up drift fits the widened hold budget; duration now
        # distinguishes the brief lowercase press from a requested capital.
        contact = [(.2,.2,2,0), (.2,.2,2,20000), (.2,.18,2,40000),
                   (.2,.14,2,60000), (.2,.07,2,80000)]
        self.assertEqual(self.events(contact + [(.2,.07,0,400000)]), [(1,0,0)])
        self.assertEqual(self.events(contact + [(.2,.07,0,3000000)]), [(2,0,0)])

    def test_unbound_edge_motion_beyond_hold_tolerance_remains_a_tap(self):
        contact = [(.3,.3,2,0), (.3,.3,2,20000), (.3,.2,2,40000),
                   (.3,.1,2,60000), (.3,.03,2,80000)]
        self.assertEqual(self.events(contact + [(.3,.03,0,3000000)]), [(1,0,0)])

    def test_all_letter_holds_use_the_first_crossing_duration(self):
        for grid in (0,1,2,4,5,6,8,9,10):
            x, y = grid % 4, grid // 4
            with self.subTest(grid=grid):
                contact = [(x,y,2,0), (x,y,2,20000)]
                self.assertEqual(self.events(contact + [(x,y,0,499999)]), [(1,0,grid)])
                self.assertEqual(self.events(contact + [(x,y,0,500000)]),
                                 [(2,0,grid)])

    def test_stationary_command_pads_release_once_after_slow_presses(self):
        # These mapped command pads have no hold gesture or auto-repeat.
        for grid in (7,11,12,13,14,15):
            x,y=grid%4,grid//4
            for duration in (500000,800000,3000000):
                contact=[(x,y,2,0),(x,y,2,20000),(x,y,2,duration-20000)]
                with self.subTest(grid=grid,duration=duration):
                    self.assertEqual(self.events(contact),[])
                    self.assertEqual(self.events(contact+[(0,0,0,duration)]),[(1,0,grid)])

    def test_stationary_o_preserves_bound_hold_precedence(self):
        for duration,expected in ((499999,1),(500000,2),(800000,2),(3000000,2)):
            self.assertEqual(self.events([(1,1,2,0),(1,1,2,20000),(1,1,2,duration-1),
                                          (0,0,0,duration)]),[(expected,0,5)])

    def test_release_position_cannot_change_swipe_direction(self):
        for endpoint in ((0,0), (3,3)):
            for destination, gesture in ((1.8,3), (2.8,4)):
                with self.subTest(endpoint=endpoint, destination=destination):
                    self.assertEqual(self.events([
                        (1.2,1.2,2,0), (1.2,1.2,2,20000),
                        (destination,1.2,2,40000), (*endpoint,0,60000)]), [(gesture,3,5)])

    def test_release_position_cannot_destroy_swipe_return(self):
        self.assertEqual(self.events([
            (1.2,1.2,2,0), (1.2,1.2,2,20000), (1.8,1.2,2,40000),
            (1.2,1.2,2,60000), (0,0,0,80000)]), [(5,3,5)])

    def test_one_release_sample_rearms_the_next_touch(self):
        self.assertEqual(self.events([
            (0,0,2,0), (0,0,2,20000), (0,0,0,40000),
            (0,0,2,60000), (0,0,2,80000), (0,0,0,100000)]), [(1,0,0), (1,0,0)])

    def test_release_rearm_still_requires_two_active_samples(self):
        self.assertEqual(self.events([
            (0,0,2,0), (0,0,2,20000), (0,0,0,40000),
            (0,0,2,60000), (0,0,0,80000), (0,0,2,100000), (0,0,0,120000)]), [(1,0,0)])

    def test_all_eight_o_cell_directions_and_returns(self):
        for direction, degrees in enumerate((90,45,0,-45,-90,-135,180,135), 1):
            dx=.6*math.cos(math.radians(degrees))
            dy=-.6*math.sin(math.radians(degrees))
            outward=[(1.2,1.2,2,0), (1.2,1.2,2,20000)]
            outward += [(1.2+dx*i/20,1.2+dy*i/20,2,(i+1)*20000)
                        for i in range(1,21)]
            with self.subTest(direction=direction):
                self.assertEqual(self.events(outward+[(0,0,0,440000)]), [(3,direction,5)])
                returning=outward+[(1.2+dx*(1-i/20),1.2+dy*(1-i/20),2,(i+21)*20000)
                                   for i in range(1,21)]
                self.assertEqual(self.events(returning+[(0,0,0,840000)]), [(5,direction,5)])

    @staticmethod
    def circle(radius, steps, sense=1, arc=2*math.pi):
        points=[(1+radius,1,2,0), (1+radius,1,2,20000)]
        points += [(1+radius*math.cos(sense*arc*i/steps),
                    1+radius*math.sin(sense*arc*i/steps),2,(i+1)*20000)
                   for i in range(1,steps+1)]
        return points+[(0,0,0,(steps+2)*20000)]

    def test_circles_both_directions_across_history_and_counter_boundaries(self):
        # Same ideal geometry at different sampling densities, including the
        # former 8-bit accumulator wrap. These are not measured touch traces.
        for radius in (.1,.2,.3):
            for steps in (24,48,64,128,256,257,272,512):
                for sense, gesture in ((1,6),(-1,7)):
                    with self.subTest(radius=radius, steps=steps, sense=sense):
                        self.assertEqual(self.events(self.circle(radius,steps,sense)),
                                         [(gesture,0,5)])

    def test_stationary_holds_and_tiny_jitter_do_not_become_circles(self):
        rng=random.Random(7)
        for count in (30,64,257,512):
            points=[(1.2,1.2,2,0), (1.2,1.2,2,20000)]
            points += [(1.2+rng.uniform(-.01,.01),1.2+rng.uniform(-.01,.01),2,(i+2)*20000)
                       for i in range(count)]
            with self.subTest(count=count):
                self.assertEqual(self.events(points+[(0,0,0,(count+3)*20000)]), [(2,0,5)])
        self.assertEqual(self.events(self.circle(.01,64)), [(2,0,5)])

    def test_pauses_do_not_change_circle_direction_or_point_eligibility(self):
        for sense, gesture in ((1,6),(-1,7)):
            for repeats in (1,5,32):
                points=[]
                for x,y,z,_ in self.circle(.2,24,sense)[:-1]:
                    for _ in range(repeats):
                        points.append((x,y,z,len(points)*20000))
                points.append((0,0,0,len(points)*20000))
                with self.subTest(sense=sense,repeats=repeats):
                    self.assertEqual(self.events(points), [(gesture,0,5)])

    def test_incomplete_arc_and_closed_scribble_do_not_become_circles(self):
        for sense in (1,-1):
            events=self.events(self.circle(.3,64,sense,1.5*math.pi))
            self.assertTrue(all(event[0] not in (6,7) for event in events))
        # A closed figure eight has substantial motion and enough points, but
        # its opposite lobes cancel area and must not win over return/hold.
        points=[(1,1,2,0), (1,1,2,20000)]
        points += [(1+.25*math.sin(2*math.pi*i/128),
                    1+.2*math.sin(4*math.pi*i/128),2,(i+1)*20000) for i in range(1,129)]
        self.assertTrue(all(event[0] not in (6,7)
                            for event in self.events(points+[(0,0,0,2600000)])))



    @staticmethod
    def closed_path(xy):
        """Synthetic contact: confirm the initial coordinate, follow, release."""
        return [(xy[0][0],xy[0][1],2,0)] + [
            (x,y,2,(i+1)*20000) for i,(x,y) in enumerate(xy)
        ] + [(0,0,0,(len(xy)+1)*20000)]

    @staticmethod
    def ellipse_xy(a,b,turns,rotation,sense=1):
        angle=math.radians(rotation)
        xy=[]
        for i in range(turns*96+1):
            phase=sense*2*math.pi*i/96
            x,y=a*math.cos(phase),b*math.sin(phase)
            xy.append((1+x*math.cos(angle)-y*math.sin(angle),
                       1+x*math.sin(angle)+y*math.cos(angle)))
        return xy

    def test_repeated_circles_and_ellipses_are_rotation_invariant(self):
        for a,b in ((.2,.2),(.3,.15)):
            for turns in (1,2,4):
                for rotation in (0,45,90):
                    for sense,gesture in ((1,6),(-1,7)):
                        with self.subTest(a=a,b=b,turns=turns,rotation=rotation,sense=sense):
                            xy=self.ellipse_xy(a,b,turns,rotation,sense)
                            self.assertEqual(self.events(self.closed_path(xy)),[(gesture,0,5)])

    def test_thin_repeated_loops_are_not_circles_even_diagonally(self):
        for turns in (1,2,4,8):
            for rotation in (0,45,90):
                for sense in (1,-1):
                    with self.subTest(turns=turns,rotation=rotation,sense=sense):
                        xy=self.ellipse_xy(.3,.02,turns,rotation,sense)
                        self.assertTrue(all(e[0] not in (6,7)
                                            for e in self.events(self.closed_path(xy))))

    def test_opposing_unequal_loops_and_long_tail_do_not_become_circles(self):
        for second_radius in (.15,.2,.3):
            # Two oppositely oriented lobes joined at the initial touch.
            xy=[(1+.2*(1-math.cos(2*math.pi*i/96)),1+.2*math.sin(2*math.pi*i/96))
                for i in range(97)]
            xy += [(1-second_radius*(1-math.cos(2*math.pi*i/96)),
                    1+second_radius*math.sin(2*math.pi*i/96)) for i in range(1,97)]
            with self.subTest(second_radius=second_radius):
                self.assertTrue(all(e[0] not in (6,7)
                                    for e in self.events(self.closed_path(xy))))
        # A tiny incidental circle cannot override a long straight excursion,
        # including a closed out-and-back tail that passes the closure guard.
        for returns in (False,True):
            xy=self.ellipse_xy(.1,.1,1,0)
            xy += [(1.1+i/60,1) for i in range(1,61)]
            if returns:
                xy += [(2.1-i/60,1) for i in range(1,61)]
            self.assertTrue(all(e[0] not in (6,7)
                                for e in self.events(self.closed_path(xy))))

    def test_motion_outside_hold_tolerance_can_still_be_a_tap(self):
        # Motion outside hold tolerance must not select a hold, but remains
        # tap-like below movement-gesture thresholds. Synthetic boundary only.
        for excursion,expected in ((.08,2),(.14,2),(.225,2),(.27,1)):
            points=[(1,1,2,0),(1,1,2,20000),(1+excursion,1,2,700000),(0,0,0,1000000)]
            self.assertEqual(self.events(points),[(expected,0,5 if expected else 0)])


if __name__ == "__main__":
    unittest.main()
