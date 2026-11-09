"""Small-circle and question-mark controls using the real detector/map/HID.

All paths here are synthetic geometry, not additional physical validation.
"""
import math
import random
import unittest

import test_return_capitals as typing_helpers


class PunctuationDigitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        typing_helpers.ReturnCapitalTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        typing_helpers.ReturnCapitalTests.tearDownClass.__func__(cls)

    events = typing_helpers.ReturnCapitalTests.events
    assert_character = typing_helpers.ReturnCapitalTests.assert_character
    assert_reports = typing_helpers.ReturnCapitalTests.assert_reports

    @staticmethod
    def contact(xy, step_us=17000):
        return [(*xy[0],2,0)] + [
            (x,y,2,(i+1)*step_us) for i,(x,y) in enumerate(xy)
        ] + [(0,0,0,(len(xy)+1)*step_us)]

    @staticmethod
    def loop(grid, radius, steps, sense=-1, arc=2*math.pi,
             aspect=1, noise=0, seed=0):
        rng = random.Random(seed)
        cx,cy = grid%4+.2,grid//4+.2
        return [(cx+radius*math.cos(sense*arc*i/steps)+rng.uniform(-noise,noise),
                 cy+radius*aspect*math.sin(sense*arc*i/steps)+rng.uniform(-noise,noise))
                for i in range(steps+1)]

    @staticmethod
    def stroke(grid, direction, distance):
        x,y = grid%4+.2,grid//4+.3
        angle = math.radians((90,45,0,-45,-90,-135,180,135)[direction-1])
        dx,dy = distance*math.cos(angle),-distance*math.sin(angle)
        return [(x+dx*i/12,y+dy*i/12) for i in range(13)]

    def test_small_fast_circles_on_all_nine_letter_cells(self):
        for (grid,_),digit in zip(typing_helpers.LETTER_CELLS,"123456789"):
            for radius in (.055,.08):
                for steps in (12,16,24,28,48):
                    for sense,gesture in ((-1,7),(1,6)):
                        with self.subTest(grid=grid,radius=radius,steps=steps,sense=sense):
                            contact = self.contact(self.loop(grid,radius,steps,sense))
                            self.assertEqual(self.events(contact[:-1]),[])
                            events = self.events(contact)
                            self.assertEqual(len(events),1)
                            self.assertEqual((events[0]["gesture"],events[0]["grid"]),
                                             (gesture,grid))
                            if gesture == 7:
                                self.assert_character(events[0],digit)
                            else:
                                self.assertEqual(events[0]["action"],0)
                                self.assertEqual(events[0]["reports"],[])

    def test_small_circles_with_controlled_coordinate_noise(self):
        # Uniform bounded jitter of at most .001 cells; same ideal loops.
        for grid,_ in typing_helpers.LETTER_CELLS:
            for radius in (.055,.08):
                for steps in (12,24,48):
                    for seed in (1,7,19):
                        with self.subTest(grid=grid,radius=radius,steps=steps,seed=seed):
                            points = self.loop(grid,radius,steps,noise=.001,seed=seed)
                            events = self.events(self.contact(points))
                            self.assertEqual(len(events),1)
                            self.assertEqual(events[0]["gesture"],7)

    def test_three_quarter_arcs_are_not_circles(self):
        for radius in (.055,.08,.2):
            for steps in (12,24,48):
                for sense in (-1,1):
                    with self.subTest(radius=radius,steps=steps,sense=sense):
                        events = self.events(self.contact(self.loop(
                            5,radius,steps,sense,arc=1.5*math.pi)))
                        self.assertEqual(len(events),1)
                        self.assertNotIn(events[0]["gesture"],(6,7))

    def test_open_three_hundred_degree_loops_can_pass_shape_and_closure(self):
        # At 300 degrees the circular endpoint/start gap is half the peak span.
        # Mildly elliptical paths also qualify; both still need coherent area
        # and sufficient net turn, not only a permissive closure threshold.
        for aspect in (1,.9):
            for sense,gesture in ((-1,7),(1,6)):
                with self.subTest(aspect=aspect,sense=sense):
                    events = self.events(self.contact(self.loop(
                        5,.2,48,sense,arc=5*math.pi/3,aspect=aspect)))
                    self.assertEqual(len(events),1)
                    self.assertEqual(events[0]["gesture"],gesture)

    def test_returns_jitter_figure_eights_and_thin_loops_are_not_circles(self):
        controls = {}
        for distance in (.12,.3,.65):
            xy = [(1+distance*i/24,1) for i in range(25)]
            xy += [(1+distance*(1-i/24),1) for i in range(1,25)]
            controls[f'straight_return_{distance}'] = xy
        rng = random.Random(72)
        controls['stationary_jitter'] = [(1+rng.uniform(-.02,.02),1+rng.uniform(-.02,.02))
                                          for _ in range(100)]
        controls['figure_eight'] = [(1+.15*math.sin(2*math.pi*i/96),
                                     1+.1*math.sin(4*math.pi*i/96)) for i in range(97)]
        for turns in (1,4):
            for rotation in (0,45,90):
                angle = math.radians(rotation)
                xy = []
                for i in range(96*turns+1):
                    phase = 2*math.pi*i/96
                    x,y = .15*math.cos(phase),.012*math.sin(phase)
                    xy.append((1+x*math.cos(angle)-y*math.sin(angle),
                               1+x*math.sin(angle)+y*math.cos(angle)))
                controls[f'thin_loop_{turns}_{rotation}'] = xy
        for label,xy in controls.items():
            with self.subTest(control=label):
                events = self.events(self.contact(xy))
                self.assertEqual(len(events),1)
                self.assertNotIn(events[0]["gesture"],(6,7))

    def test_question_mark_short_left_and_upper_left_and_minimum_motion(self):
        for direction in (7,8):
            for distance in (.26,.29):
                with self.subTest(direction=direction,distance=distance):
                    events = self.events(self.contact(self.stroke(2,direction,distance)))
                    self.assertEqual(len(events),1)
                    if distance == .26:
                        self.assertEqual(events[0]["gesture"],1)
                        self.assert_character(events[0],'i')
                    else:
                        self.assertEqual(events[0]["gesture"],3)
                        self.assertEqual(events[0]["char"],ord('?'))
                        self.assertEqual(events[0]["reports"],[[2,0x38,0,0,0,0,0],[0]*7])

    def test_i_tap_hold_and_southwest_x_are_preserved(self):
        for duration,gesture,letter in ((100000,1,'i'),(600000,2,'I')):
            event = self.events(typing_helpers.ReturnCapitalTests.tap(2,duration))[0]
            self.assertEqual(event["gesture"],gesture)
            self.assert_character(event,letter)
        for returning,letter in ((False,'x'),(True,'X')):
            event = self.events(typing_helpers.ReturnCapitalTests.swipe(2,6,returning))[0]
            self.assert_character(event,letter)

    def test_question_mark_edge_alias_does_not_bypass_path_quality(self):
        # Net NW travel is enough for '?', but the wandering path is not a
        # coherent stroke. The top-edge helper must not bypass that check.
        points = typing_helpers.ReturnCapitalTests.synthetic_waypoints(
            [(2.2,.3),(2.15,.2),(2.22,.25),(1.995,.095)],duration=300000)
        events = self.events(points)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]["gesture"],1)
        self.assert_character(events[0],'i')

    def test_other_directional_letters_keep_their_coherent_minimum(self):
        primary = dict(typing_helpers.LETTER_CELLS)
        for grid,direction,letter in typing_helpers.DIRECTIONAL_LETTERS:
            for distance in (.29,.34):
                with self.subTest(grid=grid,direction=direction,distance=distance):
                    event = self.events(self.contact(self.stroke(grid,direction,distance)))[0]
                    self.assertEqual(event["gesture"],1 if distance==.29 else 3)
                    self.assert_character(event,primary[grid] if distance==.29 else letter)


if __name__ == "__main__":
    unittest.main()
