"""Real detector -> keymap -> HID encoding; synthetic paths, no device access."""
import json
import math
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LETTER_CELLS = tuple(zip((0,1,2,4,5,6,8,9,10), "anihortes"))
# Physical start cell, direction, and its existing lowercase swipe character.
DIRECTIONAL_LETTERS = (
    (0,4,'v'), (1,5,'l'), (2,6,'x'), (4,3,'k'),
    (5,1,'u'), (5,2,'p'), (5,3,'b'), (5,4,'j'),
    (5,5,'d'), (5,6,'g'), (5,7,'c'), (5,8,'q'),
    (6,7,'m'), (8,2,'y'), (9,1,'w'), (9,3,'z'), (10,8,'f'),
)


class ReturnCapitalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        source = Path(cls.temp.name) / "typing.cpp"
        source.write_text(r'''
#include "gestureDetector.h"
#include "keyMap.h"
#include "hid_action.h"
#include <iostream>
int main() {
    GestureDetector detector;
    KeyMap keymap;
    HidActionEncoder encoder;
    float x,y,z;
    uint32_t timestamp;
    unsigned sample=0;
    while (std::cin >> x >> y >> z >> timestamp) {
        if (detector.update(x,y,z,timestamp)) {
            const auto gesture=detector.getDetectedGesture();
            const auto action=keymap.execute(gesture.grid_position,gesture.type,gesture.direction);
            HidActionPlan plan;
            const bool before=encoder.shiftPending();
            // Match runtime dispatch: intentional None actions never enter HID.
            const bool encoded=action.type!=KeyActionType::None && encoder.encode(action,plan);
            if (encoded) encoder.commit(plan);
            std::cout << "{\"sample\":" << sample << ",\"gesture\":" << gesture.type
                      << ",\"direction\":" << gesture.direction << ",\"grid\":"
                      << unsigned(gesture.grid_position) << ",\"action\":" << unsigned(action.type)
                      << ",\"char\":" << unsigned(static_cast<unsigned char>(action.ch))
                      << ",\"encoded\":" << encoded << ",\"shift_before\":" << before
                      << ",\"shift_after\":" << encoder.shiftPending() << ",\"reports\":[";
            for (unsigned i=0;i<plan.report_count;++i) {
                if(i) std::cout << ',';
                std::cout << '[' << unsigned(plan.reports[i].modifier);
                for (auto key:plan.reports[i].keycodes) std::cout << ',' << unsigned(key);
                std::cout << ']';
            }
            std::cout << "]}\n";
        }
        ++sample;
    }
}
''')
        cls.host = source.with_suffix("")
        subprocess.run(["c++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-I", str(ROOT / "main"), "-I", str(ROOT / "tools/include"),
                        str(source), str(ROOT / "main/gestureDetector.cpp"),
                        str(ROOT / "main/keyMap.cpp"), str(ROOT / "main/hid_action.cpp"),
                        "-o", str(cls.host)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def events(self, points):
        data = "".join(" ".join(map(str,point)) + "\n" for point in points)
        result = subprocess.run([str(self.host)], input=data, text=True,
                                capture_output=True, check=True)
        return [json.loads(line) for line in result.stdout.splitlines()]

    @staticmethod
    def swipe(grid, direction, returning):
        x,y = grid % 4,grid // 4
        angle = math.radians((90,45,0,-45,-90,-135,180,135)[direction-1])
        dx,dy = .65 * math.cos(angle),-.65 * math.sin(angle)
        xy = [(x,y),(x,y)] + [(x+dx*i/12,y+dy*i/12) for i in range(1,13)]
        if returning:
            xy += [(x+dx*(1-i/12),y+dy*(1-i/12)) for i in range(1,13)]
        return [(a,b,2,i*20000) for i,(a,b) in enumerate(xy)] + [(0,0,0,len(xy)*20000)]

    @staticmethod
    def tap(grid, duration=100000):
        x,y = grid % 4 + .1,grid // 4 + .1
        return [(x,y,2,0),(x,y,2,20000),(x+.02,y-.01,2,40000),
                (0,0,0,duration)]

    @staticmethod
    def join(*contacts):
        points = []; offset = 0
        for contact in contacts:
            points += [(x,y,z,t+offset) for x,y,z,t in contact]
            offset = points[-1][3] + 20000
        return points

    def assert_character(self, event, character):
        self.assertEqual(event["action"],1)
        self.assertEqual(event["char"],ord(character))
        self.assertTrue(event["encoded"])
        self.assert_reports(event,character)

    def assert_reports(self, event, character):
        if character.isalpha():
            usage = ord(character.lower()) - ord('a') + 4
            modifier = 2 if character.isupper() else 0
        elif character.isdigit():
            usage = 0x27 if character == '0' else 0x1e + int(character) - 1
            modifier = 0
        else:
            raise AssertionError("helper expects a letter or digit")
        self.assertEqual(event["reports"],[[modifier,usage,0,0,0,0,0],[0]*7])

    def test_all_directional_letters_and_returns_emit_once_on_release(self):
        for grid,direction,letter in DIRECTIONAL_LETTERS:
            for returning in (False,True):
                contact = self.swipe(grid,direction,returning)
                with self.subTest(grid=grid,direction=direction,returning=returning):
                    self.assertEqual(self.events(contact[:-1]),[])
                    events = self.events(contact + [(0,0,0,contact[-1][3]+20000)])
                    self.assertEqual(len(events),1)
                    event = events[0]
                    self.assertEqual(event["sample"],len(contact)-1)
                    self.assertEqual((event["gesture"],event["direction"],event["grid"]),
                                     (5 if returning else 3,direction,grid))
                    self.assert_character(event,letter.upper() if returning else letter)

    def test_nine_counterclockwise_digits_and_silent_clockwise_circles(self):
        for (grid,_),digit in zip(LETTER_CELLS,"123456789"):
            for sense,gesture in ((-1,7),(1,6)):
                cx,cy = grid%4+.2,grid//4+.2
                xy = [(cx+.18,cy),(cx+.18,cy)]
                xy += [(cx+.18*math.cos(sense*2*math.pi*i/96),
                        cy+.18*math.sin(sense*2*math.pi*i/96)) for i in range(1,97)]
                contact = [(x,y,2,i*20000) for i,(x,y) in enumerate(xy)]
                with self.subTest(grid=grid,gesture=gesture):
                    self.assertEqual(self.events(contact),[])
                    events = self.events(contact+[(0,0,0,len(contact)*20000)])
                    self.assertEqual(len(events),1)
                    self.assertEqual((events[0]["gesture"],events[0]["grid"]),(gesture,grid))
                    if gesture == 7:
                        self.assert_character(events[0],digit)
                    else:
                        self.assertEqual(events[0]["action"],0)
                        self.assertFalse(events[0]["encoded"])
                        self.assertEqual(events[0]["reports"],[])

    def test_one_shot_shift_plus_primary_tap_still_works_for_every_letter_cell(self):
        for grid,letter in LETTER_CELLS:
            with self.subTest(grid=grid):
                events = self.events(self.join(self.tap(7),self.tap(grid),self.tap(grid)))
                self.assertEqual(len(events),3)
                self.assertEqual(events[0]["reports"],[])
                self.assertTrue(events[0]["shift_after"])
                self.assertEqual(events[1]["char"],ord(letter))
                self.assert_reports(events[1],letter.upper())
                self.assertFalse(events[1]["shift_after"])
                self.assert_character(events[2],letter)

    def test_all_letter_holds_have_the_same_half_second_boundary(self):
        for grid,letter in LETTER_CELLS:
            for duration,gesture,char in ((499999,1,letter),(500000,2,letter.upper()),
                                          (3000000,2,letter.upper())):
                contact = self.tap(grid,duration)
                with self.subTest(grid=grid,duration=duration):
                    self.assertEqual(self.events(contact[:-1]),[])
                    events = self.events(contact+[(0,0,0,duration+20000)])
                    self.assertEqual(len(events),1)
                    self.assertEqual(events[0]["gesture"],gesture)
                    self.assert_character(events[0],char)

    def test_slow_command_pads_remain_single_taps(self):
        for grid in (7,11,12,13,14,15):
            with self.subTest(grid=grid):
                events = self.events(self.tap(grid,3000000))
                self.assertEqual(len(events),1)
                self.assertEqual(events[0]["gesture"],1)
                self.assertEqual(len(events[0]["reports"]),0 if grid==7 else 2)

    @staticmethod
    def synthetic_waypoints(xy, duration=800000):
        """Generate evenly spaced samples between independent ideal waypoints."""
        points = [(*xy[0],2,0),(*xy[0],2,20000)]
        steps = 10 * (len(xy)-1)
        index = 0
        for start,end in zip(xy,xy[1:]):
            for step in range(1,11):
                index += 1
                fraction = step/10
                points.append((start[0]+fraction*(end[0]-start[0]),
                               start[1]+fraction*(end[1]-start[1]),2,
                               20000+round(index*(duration-40000)/steps)))
        return points + [(0,0,0,duration)]

    def test_t_hold_accepts_generated_landing_drift(self):
        for excursion in (.10, .15, .20):
            for duration in (600000, 800000, 1000000):
                contact = self.synthetic_waypoints(
                    [(0, 2), (excursion, 2), (excursion / 2, 2)], duration)
                with self.subTest(excursion=excursion, duration=duration):
                    self.assertEqual(self.events(contact[:-1]), [])
                    events = self.events(contact)
                    self.assertEqual(len(events), 1)
                    self.assertEqual(events[0]["gesture"], 2)
                    self.assert_character(events[0], 'T')

    def test_return_uses_supported_peak_when_initial_cardinal_direction_is_unbound(self):
        # Generated northwest return paths with initially cardinal motion.
        start,peak,end = (2,2),(1.3,1.3),(1.8,1.85)
        for initial in ((2,1.72),(1.72,2)):
            with self.subTest(initial=initial):
                events = self.events(self.synthetic_waypoints([start,initial,peak,end]))
                self.assertEqual(len(events),1)
                self.assertEqual((events[0]["gesture"],events[0]["direction"]),(5,8))
                self.assert_character(events[0],'F')

    def test_f_return_closure_accepts_point54_but_rejects_point56(self):
        # Controlled radial paths isolate the relaxed return threshold.
        start,peak = (2,2),(1.35,1.35)
        for fraction,gesture,letter in ((.54,5,'F'),(.56,3,'f'),(1,3,'f')):
            end = tuple(a+fraction*(b-a) for a,b in zip(start,peak))
            with self.subTest(closure_fraction=fraction):
                events = self.events(self.synthetic_waypoints([start,peak,end]))
                self.assertEqual(len(events),1)
                self.assertEqual((events[0]["gesture"],events[0]["direction"]),(gesture,8))
                self.assert_character(events[0],letter)

    def test_curved_x_preserves_valid_initial_southwest_return_direction(self):
        # Generated early southwest motion followed by a farther westward peak.
        start, initial, peak, end = (2.2, .2), (1.9, .5), (1.2, .45), (2, .25)
        events = self.events(self.synthetic_waypoints([start, initial, peak, end], 600000))
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]["gesture"], events[0]["direction"]), (5, 6))
        self.assert_character(events[0], 'X')

    def test_slow_edge_punctuation_is_not_stolen_by_a_hold(self):
        for start,axis,letter,grid,direction in (
                ((1.2,.3),(0,-1),'^',1,1),
                ((.3,1.2),(-1,0),'(',4,7)):
            for distance in (.21,.225,.245):
                end = tuple(a+distance*b for a,b in zip(start,axis))
                with self.subTest(letter=letter,distance=distance):
                    events = self.events(self.synthetic_waypoints([start,end],900000))
                    self.assertEqual(len(events),1)
                    self.assertEqual((events[0]["gesture"],events[0]["direction"],events[0]["grid"]),
                                     (3,direction,grid))
                    self.assertEqual(events[0]["char"],ord(letter))
                    self.assertTrue(events[0]["encoded"])
                    self.assertEqual(events[0]["reports"][-1],[0]*7)


if __name__ == "__main__":
    unittest.main()
