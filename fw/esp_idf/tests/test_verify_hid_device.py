"""No hardware access: fail-closed isolation and exact physical-report expectations."""
import errno
import importlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
v = importlib.import_module('verify_hid_device')


class HidVerifierTests(unittest.TestCase):
    def test_ascii_reports_and_caps_lock_are_explicit(self):
        for key,hex_report in [('a','0000040000000000'),('A','0200040000000000'),
                               ('!','02001e0000000000'),('0','0000270000000000'),
                               ('\\','0000310000000000'),('~','0200350000000000'),
                               ('Enter','0000280000000000'),('ArrowUp','0000520000000000')]:
            self.assertEqual(v.expected_press(key).hex(),hex_report)
        self.assertEqual(v.expected_press('a',True)[0],2)
        self.assertEqual(v.expected_press('A',True)[0],0)
        for code in range(32,127):
            report=v.expected_press(chr(code))
            self.assertEqual(len(report),8)
            self.assertIn(report[0],(0,2))
            self.assertEqual(report[1],0)
            self.assertEqual(report[3:],bytes(5))

    def test_exact_press_release_rejects_missing_extra_modified_or_report_id(self):
        press=v.expected_press('A')
        records=lambda seq:[{'hex':r.hex()} for r in seq]
        v.validate_reports(records([press,v.ZERO]),press)
        v.validate_reports([],None)
        for bad in ([press],[v.ZERO,press],[press,v.ZERO,v.ZERO],
                    [bytes([3])+press[1:],v.ZERO],[b'\x01'+press,v.ZERO],
                    [press[:1]+b'\x01'+press[2:],v.ZERO]):
            with self.subTest(bad=bad),self.assertRaises(AssertionError):
                v.validate_reports(records(bad),press)
        with self.assertRaises(AssertionError):v.validate_reports(records([v.ZERO]),None)

    def test_evdev_modifiers_release_and_no_repeat(self):
        event=lambda code,value:{'code':code,'value':value}
        valid=[event(42,1),event(30,1),event(30,0),event(42,0)]
        v.validate_events(valid,v.expected_press('A'))
        for bad in (valid[:-1],valid+[event(30,2)],valid+[event(125,1),event(125,0)],
                    [event(30,0),event(30,1)]):
            with self.assertRaises(AssertionError):v.validate_events(bad,v.expected_press('A'))

    def test_grab_failure_never_opens_hidraw(self):
        devices={'evdev':{'path':'/dev/input/event17'},'hidraw':{'path':'/dev/hidraw3'}}
        keyboard=v.IsolatedKeyboard(devices)
        with patch.object(v.os,'open',return_value=41) as opened,patch.object(v.os,'close') as closed,\
             patch.object(v.IsolatedKeyboard,'check_node'),\
             patch.object(v,'ioctl_bytes',return_value=struct.pack('HHHH',3,v.VID,v.PID,1)),\
             patch.object(v.fcntl,'ioctl',side_effect=PermissionError(errno.EPERM,'not permitted')):
            with self.assertRaisesRegex(RuntimeError,'event17.*no serial port was opened'):
                keyboard.open()
            self.assertEqual(opened.call_count,1)
            self.assertEqual(opened.call_args.args[0],'/dev/input/event17')
            closed.assert_called_once_with(41)

    def test_preflight_failure_artifact_and_zero_serial_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'results.json';serial=Mock()
            with patch.object(v,'discover',return_value={}),\
                 patch.object(v.IsolatedKeyboard,'open',side_effect=RuntimeError('EVIOCGRAB /dev/input/event17 denied')),\
                 patch.dict(sys.modules,{'serial':serial}):
                self.assertEqual(v.main(['--output',str(output)]),1)
            serial.Serial.assert_not_called()
            report=json.loads(output.read_text())
            self.assertEqual(report['diagnostic_commands_sent'],0)
            self.assertFalse(report['passed'])
            self.assertIn('/dev/input/event17',report['error'])

    def test_release_guard_keeps_grab_after_lost_report_until_keys_clear(self):
        keyboard=Mock(evdev=41,devices={'evdev':{'path':'/dev/input/event17'}})
        collector=Mock();collector.poll.side_effect=[RuntimeError('lost raw report'),None]
        report={};snapshot=Mock()
        with patch.object(v,'pressed_keys',side_effect=[[42],[42],[]]) as query,patch.object(v.time,'sleep'):
            v.await_release(keyboard,collector,report,snapshot)
        self.assertEqual(query.call_count,3)
        keyboard.close.assert_not_called()
        self.assertTrue(report['release_confirmed'])
        self.assertFalse(report['waiting_for_release'])
        snapshot.assert_called_once()

    def test_status_fence_preserves_same_read_records(self):
        from capture_protocol import encode_packet
        data=(encode_packet(1,{'boot_id':1,'hid_completed':1},1)+
              encode_packet(3,{'token':'hidstatus-1','device_us':2,'scan_seq':2,'boot_id':1},2)+
              encode_packet(1,{'boot_id':1,'hid_completed':2},3)+
              encode_packet(3,{'token':'next','device_us':3,'scan_seq':3,'boot_id':1},4))
        connection=Mock();connection.read.side_effect=[data]
        cdc=v.Cdc(connection,Mock())
        self.assertEqual(cdc.status()['hid_completed'],2)
        self.assertEqual(cdc.wait(lambda r:r.get('token')=='next')['token'],'next')
        connection.write.assert_called_once_with(b'MARK hidstatus-1\nSTATUS\n')

    def test_case_plan_covers_ascii_digits_modifier_cancel_and_repeats(self):
        cases=v.cases()
        self.assertEqual([c.key for c in cases[:95]],[chr(c) for c in range(32,127)])
        self.assertEqual(len([c for c in cases if c.label.startswith('digit ')]),9)
        self.assertIn('zero tap',[c.label for c in cases])
        self.assertIn('cancel Shift',[c.label for c in cases])
        self.assertEqual(len([c for c in cases if c.label.startswith('repeated a ')]),5)

    def test_topology_rejects_same_vid_pid_on_another_physical_device(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);sysroot=root/'sys';dev=root/'dev'
            def add_node(kind,name,device):
                node=dev/('input' if kind=='input' else '')/name;node.parent.mkdir(parents=True,exist_ok=True);node.touch()
                klass=sysroot/'class'/kind/name;klass.mkdir(parents=True);(klass/'device').symlink_to(device)
                return str(node)
            def board(name,serial):
                usb=sysroot/'devices'/name;usb.mkdir(parents=True)
                for key,value in [('idVendor','303a'),('idProduct','4004'),('serial',serial)]:
                    (usb/key).write_text(value)
                hid=usb/'interface-hid'/'0003:303A:4004.0001';hid.mkdir(parents=True);(hid/'uevent').write_text('HID_ID=0003:0000303A:00004004\n')
                return usb,hid
            usb,hid=board('usb-one','ABC');usb2,hid2=board('usb-two','DEF')
            port=add_node('tty','ttyACM0',usb)
            raw=add_node('hidraw','hidraw3',hid);ev=add_node('input','event17',hid)
            other=add_node('hidraw','hidraw4',hid2)
            result=v.discover(port,raw,ev,sysroot,dev)
            self.assertEqual(result['cdc']['usb_serial'],'ABC')
            with self.assertRaisesRegex(RuntimeError,'matching keyboard --hidraw'):
                v.discover(port,other,ev,sysroot,dev)


if __name__=='__main__':unittest.main()
