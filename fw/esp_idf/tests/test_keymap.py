"""Typing coverage of the real gesture binding table, independent of HID transport."""
from pathlib import Path
import string
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class KeyMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        source = Path(cls.temp.name) / "keymap.cpp"
        source.write_text(r'''
#include "gestureLayout.h"
#include <iostream>
int main() {
    for (unsigned grid=0; grid<16; ++grid) {
        for (unsigned gesture=1; gesture<=7; ++gesture) {
            for (unsigned direction=0; direction<=8; ++direction) {
                const auto *binding=FindGestureBinding(grid,
                    static_cast<GestureType>(gesture),static_cast<Direction>(direction));
                if (binding) {
                    const auto &action=binding->action;
                    std::cout << grid << ' ' << gesture << ' ' << direction << ' '
                              << unsigned(action.type) << ' '
                              << unsigned(static_cast<unsigned char>(action.ch)) << ' '
                              << (action.str ? action.str : "-") << '\n';
                }
            }
        }
    }
}
''')
        host = source.with_suffix("")
        subprocess.run(["c++", "-std=c++17", "-O2", "-I", str(ROOT / "main"),
                        "-I", str(ROOT / "tools/include"), str(source),
                        str(ROOT / "main/keyMap.cpp"), "-o", str(host)], check=True)
        result = subprocess.run([str(host)], capture_output=True, text=True, check=True)
        cls.bindings = {}
        for line in result.stdout.splitlines():
            grid, gesture, direction, action, code, label = line.split()
            cls.bindings[int(grid), int(gesture), int(direction)] = (int(action), int(code), label)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_approved_counterclockwise_digit_order_and_zero_tap(self):
        for grid, digit in zip((0,1,2,4,5,6,8,9,10), "123456789"):
            with self.subTest(grid=grid):
                self.assertEqual(self.bindings[grid,7,0], (1,ord(digit),"-"))
        self.assertEqual(self.bindings[3,1,0], (1,ord("0"),"-"))
        # Adding zero must not make the formerly empty cell a swipe fallback.
        self.assertEqual([key for key in self.bindings if key[0] == 3], [(3,1,0)])

    def test_complete_basic_typing_character_coverage(self):
        chars = {chr(code) for action, code, _ in self.bindings.values() if action == 1}
        required = set(string.ascii_lowercase + string.digits + string.punctuation + " \n\t")
        self.assertEqual(required - chars, set())
        # Uppercase of every letter is available through the one-shot Shift
        # action plus the corresponding lowercase binding; USB behavior is
        # verified separately, not inferred from this table test.
        self.assertEqual(self.bindings[7,1,0], (4,0,"<SHIFT>"))

    def test_existing_taps_editing_and_o_gestures_are_preserved(self):
        for grid, letter in zip((0,1,2,4,5,6,8,9,10), "anihortes"):
            with self.subTest(grid=grid):
                self.assertEqual(self.bindings[grid,1,0], (1,ord(letter),"-"))
        self.assertEqual(self.bindings[11,1,0], (3,0,"-"))
        for grid in (12,13,14):
            self.assertEqual(self.bindings[grid,1,0], (1,32,"-"))
        self.assertEqual(self.bindings[15,1,0], (1,10,"-"))
        for grid, letter in zip((0,1,2,4,5,6,8,9,10), "anihortes"):
            self.assertEqual(self.bindings[grid,2,0], (1,ord(letter.upper()),"-"))
            # Consume valid clockwise loops before any uppercase return can
            # claim them. Counterclockwise digit bindings remain independent.
            self.assertEqual(self.bindings[grid,6,0], (0,0,"-"))
        self.assertEqual(self.bindings[5,5,3], (1,ord("B"),"-"))
        self.assertEqual(self.bindings[6,3,1], (4,0,"<UP>"))
        self.assertEqual(self.bindings[6,3,5], (4,0,"<DOWN>"))

    def test_every_directional_letter_has_exactly_its_uppercase_return(self):
        letters = {(grid,direction): code
                   for (grid,gesture,direction),(kind,code,_) in self.bindings.items()
                   if gesture == 3 and kind == 1 and ord('a') <= code <= ord('z')}
        returns = {(grid,direction): action
                   for (grid,gesture,direction),action in self.bindings.items() if gesture == 5}
        self.assertEqual(len(letters), 17)
        # Equality also forbids returns for punctuation, editing commands,
        # navigation controls, and otherwise unbound directions.
        self.assertEqual(set(returns), set(letters))
        for key, code in letters.items():
            with self.subTest(grid=key[0], direction=key[1]):
                self.assertEqual(returns[key], (1,ord(chr(code).upper()),"-"))

    def test_clockwise_suppression_is_limited_to_the_nine_letter_cells(self):
        clockwise = {grid:action for (grid,gesture,direction),action in self.bindings.items()
                     if gesture == 6 and direction == 0}
        self.assertEqual(clockwise, {grid:(0,0,"-") for grid in (0,1,2,4,5,6,8,9,10)})


if __name__ == "__main__":
    unittest.main()
