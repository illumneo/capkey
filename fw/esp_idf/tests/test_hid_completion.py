"""Portable completion history and additive wire protocol; no hardware access."""
from pathlib import Path
import copy
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from capture_protocol import StreamDecoder, encode_packet


class HidCompletionTests(unittest.TestCase):
    def test_success_provenance_shift_report_data_and_bounded_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "test.cpp"
            source.write_text(r'''
#include "hid_completion.h"
#include <cassert>
#include <iostream>
int main() {
    HidCompletionLog log;
    assert(log.status().retained==0 && log.status().oldest_seq==0);
    HidOrigin origin;
    origin.source=HidOrigin::Source::Physical; origin.boot_id=11;
    origin.event_seq=9; origin.scan_seq=999; origin.processing_epoch=2;
    origin.timestamp_us=12345678901ULL; origin.duration_us=501000;
    origin.start_x=.3f; origin.end_x=.7f; origin.peak_dx=.45f; origin.path_length=.52f;
    HidActionEncoder encoder; HidActionPlan plan; HidCompletion result;
    assert(encoder.encode(MakeCharAction('a'),plan));
    assert(!log.recordCompleted(false,origin,plan,12345679901ULL,3,false,false));
    assert(log.status().latest_seq==0); // Failure/partial transfer cannot become completion.
    auto malformed=plan; malformed.reports[1].keycodes[0]=4;
    assert(!log.recordCompleted(true,origin,malformed,12345679901ULL,3,false,false));
    malformed=plan; malformed.report_count=1;
    assert(!log.recordCompleted(true,origin,malformed,12345679901ULL,3,false,false));
    assert(log.recordCompleted(true,origin,plan,12345679901ULL,3,false,false));
    origin.event_seq=9999; // Log and queue provenance are values, not dangling references.
    assert(log.get(1,result));
    assert(result.origin.event_seq==9 && result.origin.boot_id==11 && result.origin.scan_seq==999);
    assert(result.origin.processing_epoch==2 && result.origin.duration_us==501000);
    assert(result.origin.timestamp_us==12345678901ULL && result.completed_us==12345679901ULL);
    assert(result.origin.start_x==.3f && result.origin.end_x==.7f);
    assert(result.origin.peak_dx==.45f && result.origin.path_length==.52f);
    assert(result.press_count==1 && result.presses[0].modifier==0 && result.presses[0].keycodes[0]==4);
    assert(encoder.encode(MakeSpecialAction("<SHIFT>"),plan)); encoder.commit(plan);
    assert(log.recordCompleted(true,origin,plan,12345679902ULL,3,false,false));
    assert(log.get(2,result) && result.press_count==0 && !result.shift_before && result.shift_after);
    encoder.setCapsLock(true);
    assert(encoder.encode(MakeCharAction('a'),plan));
    assert(log.recordCompleted(true,origin,plan,12345679903ULL,3,true,true)); encoder.commit(plan);
    assert(log.get(3,result) && result.caps_lock && result.shift_before && !result.shift_after);
    assert(result.presses[0].modifier==0 && result.presses[0].keycodes[0]==4); // Caps supplies uppercase.
    assert(encoder.encode(MakeStringAction("aA!"),plan));
    assert(log.recordCompleted(true,origin,plan,12345679904ULL,3,true,false));
    assert(log.get(4,result) && result.press_count==3);
    assert(result.presses[0].modifier==2 && result.presses[1].modifier==0 && result.presses[2].modifier==2);
    origin.source=HidOrigin::Source::Diagnostic; origin.event_seq=0; origin.diagnostic_id=42;
    for(int i=0;i<40;++i) assert(log.recordCompleted(true,origin,plan,12345680000ULL+i,4,true,false));
    const auto status=log.status();
    assert(status.latest_seq==44 && status.oldest_seq==13 && status.retained==32 && status.overwritten==12);
    assert(!log.get(1,result) && !log.get(12,result) && !log.get(45,result));
    for(uint64_t seq=13;seq<=44;++seq) {
        assert(log.get(seq,result) && result.completion_seq==seq);
        assert(result.origin.source==HidOrigin::Source::Diagnostic && result.origin.diagnostic_id==42);
        assert(result.usb_generation==4);
    }
    // Queries are nondestructive; history spans USB generations within a boot.
    assert(log.status().latest_seq==44 && log.status().retained==32);
    std::cout << sizeof(HidCompletionLog) << '\n';
}
''')
            host = source.with_suffix("")
            subprocess.run(["c++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                            "-I", str(ROOT / "main"), str(source), str(ROOT / "main/hid_action.cpp"),
                            str(ROOT / "main/hid_completion.cpp"), "-o", str(host)], check=True)
            result = subprocess.run([str(host)], check=True, capture_output=True, text=True)
            self.assertLess(int(result.stdout), 12000)

    @staticmethod
    def completion():
        return dict(event="completion", token="query", boot_id=1, completion_seq=7,
                    completed_us=220000, timestamp_us=200000, usb_generation=2,
                    source="physical", processing_epoch=0, event_seq=9, scan_seq=12,
                    hid_failed=0, hid_queue_drops=0,
                    diagnostic_id=0, duration_us=150000, grid=0, gesture_type=1, direction=0,
                    start_x=0., start_y=0., end_x=.1, end_y=.1, peak_dx=.1, peak_dy=.1,
                    max_distance=.14, path_length=.2, caps_lock=False, shift_before=True,
                    shift_after=False, state_only=False, presses=[[2,4,0,0,0,0,0]])

    def test_packet_five_preserves_origin_and_full_press_without_changing_metadata(self):
        decoder = StreamDecoder(); item = self.completion()
        wire = encode_packet(1, {"project":"swipe"}, 4) + encode_packet(5, item, 5)
        records=[]
        for i in range(0,len(wire),7): records.extend(decoder.feed(wire[i:i+7]))
        self.assertEqual(records[0]["type"],"metadata")
        self.assertEqual(records[1],dict(item,type="hid_log",packet_seq=5))
        self.assertEqual(decoder.counters["unknown_types"],0)

    def test_malformed_completion_is_counted_as_payload_error(self):
        changes = ({"event_seq":0},{"source":"injected"},{"state_only":True},
                   {"presses":[[2,4]]},{"completed_us":1},{"caps_lock":1},
                   {"presses":[[0]*7]*32},{"path_length":float("inf")})
        for change in changes:
            with self.subTest(change=change):
                item=self.completion();item.update(change)
                # Explicit JSON Infinity must be rejected by the receiver as well.
                payload=json.dumps(item).encode()
                decoder=StreamDecoder();self.assertEqual(decoder.feed(encode_packet(5,payload)),[])
                self.assertEqual(decoder.counters["payload_errors"],1)

    def test_diagnostic_state_commit_and_loss_summary(self):
        item=self.completion();item.update(source="diagnostic",event_seq=0,diagnostic_id=42,
                                          presses=[],state_only=True,shift_before=False,shift_after=True)
        summary=dict(event="summary",token="query",boot_id=1,after_seq=0,oldest_seq=5,latest_seq=36,
                     overwritten=4,overwritten_at_end=5,retained=32,returned=31,lost_before_query=4,
                     missing_during_query=1,hid_failed=1,hid_queue_drops=2,error="",hid_layout="US",
                     recognizer_sha256="0"*64,coherent_swipe_min_distance=.32,
                     coherent_swipe_min_efficiency=.75,coherent_swipe_min_end_ratio=.8,
                     coherent_efficiency_basis="peak/path",edge_swipe_min_distance=.2)
        records=StreamDecoder().feed(encode_packet(5,item)+encode_packet(5,summary,1))
        self.assertEqual(len(records),2)
        self.assertEqual(records[1]["lost_before_query"],4)
        self.assertEqual(records[1]["missing_during_query"],1)

if __name__ == "__main__": unittest.main()
