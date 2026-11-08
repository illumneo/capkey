"""Passive collector lifecycle with fake serial; never touches a device."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from capture_protocol import encode_packet
from read_hid_log import QueryResult, query_hid_log
from watch_hid_log import collect, find_capkey
import test_hid_completion as completion_fixtures

TEST_SERIAL = "CAPKEY-TEST-001"


class Clock:
    def __init__(self): self.now = 0.
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds


def snapshot(first=1, last=2, boot=1):
    records = []
    for seq in range(first, last + 1):
        item = completion_fixtures.HidCompletionTests.completion()
        item.update(completion_seq=seq, boot_id=boot)
        records.append(item)
    summary = dict(event="summary", token="query", boot_id=boot, after_seq=0,
                   oldest_seq=first, latest_seq=last, overwritten=first-1,
                   overwritten_at_end=first-1, retained=last-first+1,
                   returned=len(records), lost_before_query=first-1, missing_during_query=0,
                   hid_failed=0, hid_queue_drops=0, error="", hid_layout="US",
                   recognizer_sha256="0"*64, coherent_swipe_min_distance=.32,
                   coherent_swipe_min_efficiency=.75, coherent_swipe_min_end_ratio=.8,
                   coherent_efficiency_basis="peak/path", edge_swipe_min_distance=.2)
    return QueryResult(records=records+[summary], summary=summary, status="complete")


def identity(device="/dev/ttyACM0"):
    return dict(vid=0x303a, pid=0x4004, serial_number=TEST_SERIAL, device=device, location="1-1")


def serial_port(device, serial_number, vid=0x303a, pid=0x4004):
    return SimpleNamespace(vid=vid, pid=pid, serial_number=serial_number,
                           device=device, location="1-1")


class CollectorTests(unittest.TestCase):
    def run_collection(self, folder, responses, **kwargs):
        clock = Clock(); calls = []; sources = iter(responses)
        def query(port, **args):
            calls.append((port,args["after"]))
            result = next(sources)
            if isinstance(result, Exception): raise result
            return result
        status = collect(folder, duration=len(responses), interval=1, query=query,
                         discover=lambda *a: identity(), clock=clock, sleep=clock.sleep, **kwargs)
        manifest = [json.loads(line) for line in (folder/"manifest.jsonl").read_text().splitlines()]
        self.assertTrue(all((folder/e["path"]).is_file() for e in manifest))
        self.assertEqual(calls, [("/dev/ttyACM0",0)]*len(responses))
        return status, manifest

    def test_overlap_busy_recovery_and_reboot_with_higher_sequence(self):
        with tempfile.TemporaryDirectory() as temp:
            status, manifest = self.run_collection(Path(temp)/"history", [
                snapshot(1,2), OSError("busy"), snapshot(2,4), snapshot(100,131,boot=2)])
            self.assertEqual([e["status"] for e in manifest], ["complete","error","complete","complete"])
            self.assertEqual(status["unique_completions"],36)
            self.assertEqual(status["missing_since_previous_poll"],0)
            self.assertEqual(status["unavailable_before_first_poll"],99)
            self.assertEqual(status["boot_changes"],1)
            self.assertEqual(manifest[2]["duplicate_records"],1)
            self.assertEqual(status["stop_reason"],"duration")

    def test_actual_unrecovered_gap_is_reported_once(self):
        with tempfile.TemporaryDirectory() as temp:
            status, _ = self.run_collection(Path(temp)/"history", [snapshot(1,2),snapshot(5,6),snapshot(5,7)])
            self.assertEqual(status["missing_since_previous_poll"],2)
            self.assertEqual(status["unique_completions"],5)

    def test_recording_refusal_does_not_lose_recovered_context(self):
        refused = snapshot(); refused.status="refused"; refused.error="recording_active"
        refused.summary.update(error="recording_active",returned=0)
        refused.records=[refused.summary]
        with tempfile.TemporaryDirectory() as temp:
            status, _ = self.run_collection(Path(temp)/"history", [snapshot(1,2),refused,snapshot(1,4)])
            self.assertEqual(status["refused_queries"],1)
            self.assertEqual(status["unique_completions"],4)
            self.assertEqual(status["missing_since_previous_poll"],0)

    def test_stop_file_and_keyboard_interrupt_leave_final_status(self):
        for reason in ("stop_request","keyboard_interrupt"):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temp:
                folder=Path(temp)/"history"; clock=Clock()
                def query(*a,**k):
                    if reason=="keyboard_interrupt": raise KeyboardInterrupt
                    (folder/"stop-request").touch()
                    return snapshot()
                status=collect(folder,duration=100,query=query,discover=lambda *a:identity(),
                               clock=clock,sleep=clock.sleep)
                self.assertEqual(status["queries"],1)
                self.assertEqual(status["stop_reason"],reason)
                self.assertEqual(json.loads((folder/"status.json").read_text())["state"],"stopped")

    def test_deadline_during_discovery_sends_no_query(self):
        clock=Clock()
        def discover(*a): clock.sleep(2); return identity()
        with tempfile.TemporaryDirectory() as temp:
            status=collect(Path(temp)/"history",duration=1,discover=discover,clock=clock,sleep=clock.sleep,
                           query=lambda *a,**k:self.fail("deadline must stop before opening serial"))
            self.assertEqual(status["stop_reason"],"duration")

    def test_existing_directory_and_invalid_bounds_do_not_open_serial(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileExistsError): collect(temp)
            for duration,interval in ((float("inf"),1),(0,1),(1,0),(1,float("nan"))):
                with self.subTest(duration=duration,interval=interval),self.assertRaises(ValueError):
                    collect(Path(temp)/"new",duration=duration,interval=interval)
            self.assertFalse((Path(temp)/"new").exists())

    def test_device_identity_tracks_same_serial_across_tty_reuse(self):
        first=find_capkey("/dev/ttyACM0",None,ports=[serial_port("/dev/ttyACM0",TEST_SERIAL)])
        second=find_capkey("/dev/ttyACM0",first["serial_number"],ports=[
            serial_port("/dev/ttyACM0","OTHER"),serial_port("/dev/ttyACM1",TEST_SERIAL)])
        self.assertEqual(second["device"],"/dev/ttyACM1")
        with self.assertRaises(RuntimeError):
            find_capkey(expected_serial=first["serial_number"],
                        ports=[serial_port("/dev/ttyACM0","OTHER")])

    def test_autodiscovery_selects_the_only_identified_capkey(self):
        device=find_capkey(ports=[
            serial_port("/dev/ttyACM0","unrelated",vid=0x1234),
            serial_port("/dev/ttyACM1",None),
            serial_port("/dev/ttyACM2",TEST_SERIAL),
        ])
        self.assertEqual(device["device"],"/dev/ttyACM2")
        self.assertEqual(device["serial_number"],TEST_SERIAL)

    def test_multiple_boards_require_an_explicit_selection(self):
        ports=[serial_port("/dev/ttyACM0","OTHER"),serial_port("/dev/ttyACM1",TEST_SERIAL)]
        with self.assertRaisesRegex(RuntimeError,"found 2"):
            find_capkey(ports=ports)
        self.assertEqual(find_capkey("/dev/ttyACM0",ports=ports)["serial_number"],"OTHER")
        self.assertEqual(find_capkey(expected_serial=TEST_SERIAL.lower(),ports=ports)["device"],
                         "/dev/ttyACM1")

    def test_autodiscovered_board_is_pinned_before_following_a_reconnection(self):
        clock=Clock(); discoveries=[]; queries=[]
        def discover(port, expected_serial):
            discoveries.append((port,expected_serial))
            ports=([serial_port("/dev/ttyACM0",TEST_SERIAL)] if len(discoveries)==1 else
                   [serial_port("/dev/ttyACM0","OTHER"),serial_port("/dev/ttyACM1",TEST_SERIAL)])
            return find_capkey(port,expected_serial,ports=ports)
        def query(port, **kwargs):
            queries.append(port)
            return snapshot()
        with tempfile.TemporaryDirectory() as temp:
            status=collect(Path(temp)/"history",duration=2,interval=1,query=query,
                           discover=discover,clock=clock,sleep=clock.sleep)
        self.assertEqual(discoveries,[(None,None),(None,TEST_SERIAL)])
        self.assertEqual(queries,["/dev/ttyACM0","/dev/ttyACM1"])
        self.assertEqual(status["device_identity"]["serial_number"],TEST_SERIAL)


class QueryTests(unittest.TestCase):
    def fake_serial(self, clock, mode="complete"):
        outer=self
        class Port:
            def __init__(self, **kwargs):
                outer.assertIsNone(kwargs["port"]);outer.assertTrue(kwargs["exclusive"])
                self.closed=False;self.writes=[];self.buffer=b"";self.read_once=False
            def open(self):
                outer.assertTrue(self.dtr);outer.assertFalse(self.rts)
                if mode=="busy": raise OSError("busy")
            def write(self,data):
                self.writes.append(data); command,token,after=data.decode().split()
                outer.assertEqual(command,"HIDLOG");outer.assertEqual(after,"0")
                result=snapshot(1,1)
                for record in result.records: record["token"]=token
                records=result.records if mode=="complete" else result.records[:1]
                self.buffer=b"".join(encode_packet(5,r,i) for i,r in enumerate(records))
                return len(data)
            @property
            def in_waiting(self): return len(self.buffer)
            def read(self,n):
                clock.sleep(.05)
                if mode=="disconnect" and self.read_once: raise OSError("disconnected")
                self.read_once=True;data,self.buffer=self.buffer[:n],self.buffer[n:];return data
            def close(self): self.closed=True
        ports=[]
        def factory(**kwargs):
            result=Port(**kwargs);ports.append(result);return result
        return factory,ports

    def test_only_hidlog_command_safe_open_and_close_after_success(self):
        clock=Clock();factory,ports=self.fake_serial(clock)
        result=query_hid_log("fake",timeout=.3,serial_factory=factory,clock=clock)
        self.assertEqual(result.status,"complete")
        self.assertEqual(len(result.records),2)
        self.assertEqual(len(ports[0].writes),1)
        self.assertTrue(ports[0].closed)

    def test_busy_disconnect_and_timeout_retain_honest_artifacts_and_close(self):
        for mode,status,count in (("busy","error",0),("disconnect","incomplete",1),("timeout","incomplete",1)):
            with self.subTest(mode=mode):
                clock=Clock();factory,ports=self.fake_serial(clock,mode)
                result=query_hid_log("fake",timeout=.2,serial_factory=factory,clock=clock)
                self.assertEqual(result.status,status)
                self.assertEqual(len(result.records),count)
                self.assertTrue(ports[0].closed)
                self.assertIsNotNone(result.error)


if __name__ == "__main__": unittest.main()
