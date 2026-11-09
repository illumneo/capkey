"""Portable HID encoder checks; no USB, serial device or desktop key injection."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HidActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        source = Path(cls.temp.name) / "hid_test.cpp"
        source.write_text(r'''
#include "hid_action.h"
#include <iostream>
#include <sstream>
#include <string>
int main() {
    HidActionEncoder encoder;
    std::string line;
    while (std::getline(std::cin,line)) {
        std::istringstream in(line);
        int commit=0; std::string kind,arg;
        in >> commit >> kind >> arg;
        if (kind=="caps") {encoder.setCapsLock(arg=="1");continue;}
        if (kind=="reset") {encoder.reset();continue;}
        if (kind=="bindings") {
            unsigned count=0,unsupported=0;
            for (unsigned grid=0;grid<16;++grid) for (unsigned type=1;type<=7;++type)
            for (unsigned direction=0;direction<=8;++direction) {
                auto binding=FindGestureBinding(grid,static_cast<GestureType>(type),static_cast<Direction>(direction));
                if (!binding || binding->action.type == KeyActionType::None) continue;
                ++count; HidActionPlan plan;
                if (!encoder.encode(binding->action,plan)) ++unsupported;
            }
            std::cout << "{\"count\":" << count << ",\"unsupported\":" << unsupported << "}\n";
            continue;
        }
        KeyAction action;
        std::string storage;
        if (kind=="char") action=MakeCharAction(static_cast<char>(std::stoi(arg)));
        else if (kind=="special") action=MakeSpecialAction(arg.c_str());
        else if (kind=="backspace") action=MakeBackspaceAction();
        else if (kind=="nullstring") action=MakeStringAction(nullptr);
        else if (kind=="nullspecial") action=MakeSpecialAction(nullptr);
        else if (kind=="invalid") action.type=static_cast<KeyActionType>(99);
        else if (kind=="string") {
            if (arg!="-") for(size_t i=0;i<arg.size();i+=2)
                storage.push_back(static_cast<char>(std::stoi(arg.substr(i,2),nullptr,16)));
            action=MakeStringAction(storage.c_str());
        }
        const bool before=encoder.shiftPending();
        HidActionPlan plan;
        const bool ok=encoder.encode(action,plan);
        if (ok && commit) encoder.commit(plan);
        std::cout << "{\"ok\":" << ok << ",\"before\":" << before
                  << ",\"after\":" << encoder.shiftPending()
                  << ",\"next\":" << plan.next_shift_pending << ",\"reports\":[";
        for (unsigned i=0;i<plan.report_count;++i) {
            if(i) std::cout << ',';
            std::cout << '[' << unsigned(plan.reports[i].modifier);
            for(auto key:plan.reports[i].keycodes) std::cout << ',' << unsigned(key);
            std::cout << ']';
        }
        std::cout << "]}\n";
    }
}
''')
        cls.host = source.with_suffix("")
        subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-O2",
                        "-I", str(ROOT / "main"), "-I", str(ROOT / "tools/include"),
                        str(source), str(ROOT / "main/hid_action.cpp"),
                        str(ROOT / "main/keyMap.cpp"), "-o", str(cls.host)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_actions(self, *commands):
        output=subprocess.run([str(self.host)],input="\n".join(commands)+"\n",
                              text=True,capture_output=True,check=True).stdout
        return [json.loads(line) for line in output.splitlines()]

    def assert_key(self, result, usage, shift=False):
        self.assertTrue(result["ok"])
        self.assertEqual(result["reports"], [[2 if shift else 0,usage,0,0,0,0,0],[0]*7])

    def test_every_printable_us_ascii_has_correct_usage_and_release(self):
        # Standard US key pairs; all95 printable ASCII characters are exercised.
        expected={" ":(0x2c,False)}
        for i in range(26):
            expected[chr(ord('a')+i)]=(4+i,False)
            expected[chr(ord('A')+i)]=(4+i,True)
        pairs=[("1!",0x1e),("2@",0x1f),("3#",0x20),("4$",0x21),("5%",0x22),
               ("6^",0x23),("7&",0x24),("8*",0x25),("9(",0x26),("0)",0x27),
               ("-_",0x2d),("=+",0x2e),("[{",0x2f),("]}",0x30),("\\|",0x31),
               (";:",0x33),("'\"",0x34),("`~",0x35),(",<",0x36),(".>",0x37),("/?",0x38)]
        for (plain,shifted),usage in pairs:
            expected[plain]=(usage,False);expected[shifted]=(usage,True)
        self.assertEqual(set(map(ord,expected)),set(range(32,127)))
        results=self.run_actions(*(f"1 char {code}" for code in range(32,127)))
        for code,result in zip(range(32,127),results):
            with self.subTest(char=chr(code)):
                self.assert_key(result,*expected[chr(code)])

    def test_controls_and_navigation(self):
        controls={8:0x2a,9:0x2b,10:0x28,13:0x28,27:0x29,127:0x4c}
        for ch,usage in controls.items():
            self.assert_key(self.run_actions(f"1 char {ch}")[0],usage)
        specials={"<UP>":0x52,"<DOWN>":0x51,"<LEFT>":0x50,"<RIGHT>":0x4f,
                  "<ENTER>":0x28,"<TAB>":0x2b,"<BACKSPACE>":0x2a,"<DELETE>":0x4c,
                  "<HOME>":0x4a,"<END>":0x4d,"<PAGEUP>":0x4b,"<PAGEDOWN>":0x4e,
                  "<CAPSLOCK>":0x39,"<ESCAPE>":0x29,"<SPACE>":0x2c}
        for label,usage in specials.items():
            self.assert_key(self.run_actions(f"1 special {label}")[0],usage)
        self.assert_key(self.run_actions("1 backspace")[0],0x2a)

    def test_shift_is_armed_only_after_commit_and_consumed_after_release(self):
        preview,plain,armed,shifted,next_plain=self.run_actions(
            "0 special <SHIFT>","1 char 97","1 special <SHIFT>","1 char 97","1 char 97")
        self.assertFalse(preview["after"]);self.assertTrue(preview["next"])
        self.assertEqual(preview["reports"],[])
        self.assert_key(plain,4)
        self.assertTrue(armed["after"]);self.assertEqual(armed["reports"],[])
        self.assert_key(shifted,4,True);self.assertFalse(shifted["after"])
        self.assert_key(next_plain,4)

    def test_shift_applies_once_to_string_and_control_combination(self):
        results=self.run_actions("1 special <SHIFT>","1 string 61614121", "1 special <SHIFT>",
                                 "1 special <UP>","1 special <UP>")
        self.assertEqual(results[1]["reports"],[[2,4,0,0,0,0,0],[0]*7,
                         [0,4,0,0,0,0,0],[0]*7,[2,4,0,0,0,0,0],[0]*7,
                         [2,0x1e,0,0,0,0,0],[0]*7])
        self.assert_key(results[3],0x52,True);self.assert_key(results[4],0x52)
        self.assert_key(self.run_actions("1 special <SHIFT>","1 char 49")[-1],0x1e,True)

    def test_caps_led_preserves_literal_case_and_one_shot_uppercase(self):
        results=self.run_actions("0 caps 1","1 char 97","1 char 65", "1 char 33",
                                 "1 special <SHIFT>","1 char 97","0 caps 0","1 char 97")
        self.assert_key(results[0],4,True);self.assert_key(results[1],4)
        self.assert_key(results[2],0x1e,True);self.assert_key(results[4],4)
        self.assert_key(results[5],4)

    def test_aborted_send_keeps_shift_until_reset_or_success(self):
        results=self.run_actions("1 special <SHIFT>","0 char 97","1 char 97","1 char 97",
                                 "1 special <SHIFT>","0 caps 1","0 reset","1 char 97")
        self.assertTrue(results[1]["after"])
        self.assert_key(results[1],4,True);self.assert_key(results[2],4,True)
        self.assert_key(results[3],4);self.assert_key(results[-1],4)

    def test_invalid_and_oversized_inputs_are_atomic_and_preserve_pending_shift(self):
        bad_commands=["none","invalid","char 0","char 1","char 128","char 255",
                      "special <UNSUPPORTED>","nullstring","nullspecial","string -",
                      "string 610162", "string "+"61"*32]
        for command in bad_commands:
            with self.subTest(command=command):
                _,bad,good=self.run_actions("1 special <SHIFT>","1 "+command,"1 char 97")
                self.assertFalse(bad["ok"]);self.assertEqual(bad["reports"],[])
                self.assertTrue(bad["after"]);self.assert_key(good,4,True)

    def test_maximum_string_releases_between_identical_keys(self):
        result=self.run_actions("1 string "+"61"*31)[0]
        self.assertTrue(result["ok"])
        self.assertEqual(result["reports"],[[0,4,0,0,0,0,0],[0]*7]*31)

    def test_second_shift_cancels_without_holding_a_physical_modifier(self):
        results=self.run_actions("1 special <SHIFT>","1 special <SHIFT>","1 char 97")
        self.assertEqual(results[0]["reports"],[]);self.assertTrue(results[0]["after"])
        self.assertEqual(results[1]["reports"],[]);self.assertFalse(results[1]["after"])
        self.assert_key(results[2],4);self.assertFalse(results[2]["after"])

    def test_every_current_typing_binding_can_be_encoded(self):
        result=self.run_actions("0 bindings")[0]
        self.assertGreater(result["count"],80)
        self.assertEqual(result["unsupported"],0)


if __name__ == "__main__":
    unittest.main()
