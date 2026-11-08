"""Exercise the actual firmware query formatter with a host-only USB/log shim."""
from pathlib import Path
import copy
import json
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from capture_protocol import decode_payload
from read_hid_log import validate_query


class HidLogQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        source=Path(cls.temp.name)/'query.cpp'
        firmware=(ROOT/'main/capture.cpp').read_text()
        formatter=firmware[firmware.index('void writeHidLog('):firmware.index('void command(')]
        source.write_text(r'''
#include "hid_completion.h"
#include "gestureConfig.h"
#define SWIPE_RECOGNIZER_SHA256 "0000000000000000000000000000000000000000000000000000000000000000"
#include <algorithm>
#include <atomic>
#include <cinttypes>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <string>
HidCompletionLog logbook;
HidOrigin source_origin;
HidActionPlan source_plan;
struct {std::atomic<bool> streaming{false}; uint32_t boot_id=77;} runtime;
bool racing=false;
int packets=0;
namespace usb {
struct Status {uint32_t failed=0,dropped=0;};
Status status(){return {};}
HidLogStatus completion_log_status(){return logbook.status();}
bool completion_log_get(uint64_t seq,HidCompletion& record){return logbook.get(seq,record);}
}
bool writePacket(uint8_t type,const void* data,uint16_t length) {
    if(type!=5) return false;
    std::cout << std::string(static_cast<const char*>(data),length) << '\n';
    if(racing && ++packets==1) {
        for(int i=0;i<10;++i) logbook.recordCompleted(true,source_origin,source_plan,1000+i,1,false,false);
    }
    return true;
}
'''+formatter+r'''
int main(int argc,char** argv) {
    source_origin.source=HidOrigin::Source::Physical;
    source_origin.boot_id=77;source_origin.event_seq=1;source_origin.timestamp_us=100;
    source_origin.duration_us=10;source_origin.path_length=.4f;
    HidActionEncoder encoder;
    if(!encoder.encode(MakeStringAction("abcdefghijklmnopqrstuvwxyz12345"),source_plan)) return 2;
    for(int i=0;i<35;++i) logbook.recordCompleted(true,source_origin,source_plan,200+i,1,false,false);
    const std::string mode=argc>1?argv[1]:"normal";
    runtime.streaming=mode=="streaming";
    racing=mode=="racing";
    writeHidLog("query",mode=="ahead"?100:0);
}
''')
        cls.host=source.with_suffix('')
        subprocess.run(['c++','-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(ROOT/'main'),
                        str(source),str(ROOT/'main/hid_action.cpp'),str(ROOT/'main/hid_completion.cpp'),
                        '-o',str(cls.host)],check=True)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def query(self,mode):
        result=subprocess.run([str(self.host),mode],capture_output=True,text=True,check=True)
        return [decode_payload(5,line.encode(),i) for i,line in enumerate(result.stdout.splitlines())]

    def test_real_formatter_maximum_press_count_and_overwrite_summary(self):
        records=self.query('normal');summary=records[-1]
        self.assertEqual(summary['returned'],32)
        self.assertEqual(summary['lost_before_query'],3)
        self.assertEqual([r['completion_seq'] for r in records[:-1]],list(range(4,36)))
        self.assertTrue(all(len(r['presses'])==31 for r in records[:-1]))
        validate_query(records,summary,0)

    def test_query_refuses_active_recording_without_completion_insertion(self):
        records=self.query('streaming')
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['error'],'recording_active')
        self.assertEqual(records[0]['returned'],0)

    def test_cursor_ahead_is_explicit_and_does_not_clear_history(self):
        records=self.query('ahead')
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['error'],'cursor_ahead')
        self.assertEqual(records[0]['retained'],32)

    def test_concurrent_overwrite_reports_missing_records_with_finite_snapshot(self):
        records=self.query('racing');summary=records[-1]
        self.assertEqual(summary['latest_seq'],35)
        self.assertEqual(summary['overwritten_at_end'],13)
        self.assertGreater(summary['missing_during_query'],0)
        self.assertEqual(summary['returned']+summary['missing_during_query'],32)
        validate_query(records,summary,0)

    def test_reader_rejects_duplicate_out_of_range_and_unreported_gap(self):
        records=self.query('normal')
        for kind in ('duplicate','range','gap','boot'):
            broken=copy.deepcopy(records)
            if kind=='duplicate': broken[1]['completion_seq']=broken[0]['completion_seq']
            elif kind=='range': broken[0]['completion_seq']=1
            elif kind=='gap': broken.pop(1);broken[-1]['returned']-=1
            else: broken[0]['boot_id']=78
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                validate_query(broken,broken[-1],0)

if __name__=='__main__':unittest.main()
