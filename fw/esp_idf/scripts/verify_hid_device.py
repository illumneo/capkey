#!/usr/bin/env python3
"""Verify CapKey USB reports using hidraw while its matching evdev is exclusively grabbed.

No GUI and no simulated input. Requires read access to the selected hidraw and
input event nodes, EVIOCGRAB permission, and read/write access to CDC. No HID
command or serial open occurs before the exclusive keyboard grab succeeds.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from dataclasses import asdict, dataclass
import fcntl
import errno
import json
import os
from pathlib import Path
import select
import stat
import struct
import sys
import time

from capture_protocol import StreamDecoder

VID, PID = 0x303A, 0x4004
EVIOCGRAB = 0x40044590
INPUT_EVENT = struct.Struct('@llHHi')
ZERO = bytes(8)


def ior(kind, number, size):
    return (2 << 30) | (size << 16) | (ord(kind) << 8) | number


def ioctl_bytes(fd, request, size):
    value = bytearray(size)
    fcntl.ioctl(fd, request, value, True)
    return bytes(value)


def pressed_keys(fd):
    bits = ioctl_bytes(fd, ior('E', 0x18, 96), 96)
    return [i for i in range(768) if bits[i // 8] & (1 << (i % 8))]


def usb_parent(path):
    for parent in (path, *path.parents):
        if (parent / 'idVendor').exists() and (parent / 'idProduct').exists():
            return parent
    raise RuntimeError(f'No physical USB parent for {path}')


def node_identity(node, kind, sys_root=Path('/sys')):
    node = Path(node).resolve(strict=True)
    link = sys_root / 'class' / kind / node.name
    device = (link / 'device').resolve(strict=True)
    usb = usb_parent(device)
    vendor = int((usb / 'idVendor').read_text().strip(), 16)
    product = int((usb / 'idProduct').read_text().strip(), 16)
    if (vendor, product) != (VID, PID):
        raise RuntimeError(f'{node} is not CapKey USB 303a:4004')
    serial_path = usb / 'serial'
    serial = serial_path.read_text().strip() if serial_path.exists() else ''
    if not serial:
        raise RuntimeError(f'{node} has no USB serial identity')
    hid = next((p for p in (device, *device.parents)
                if (p / 'uevent').exists() and
                'HID_ID=' in (p / 'uevent').read_text()), None)
    return {'path':str(node), 'class_path':str(link), 'usb_path':str(usb),
            'usb_serial':serial, 'hid_path':str(hid) if hid else None}


def discover(port=None, hidraw=None, evdev=None, sys_root=Path('/sys'), dev_root=Path('/dev')):
    def candidates(kind, pattern, explicit):
        if explicit:
            return [node_identity(explicit, kind, sys_root)]
        found = []
        for entry in sorted((sys_root / 'class' / kind).glob(pattern)):
            try:
                found.append(node_identity(dev_root / ('input' if kind == 'input' else '') / entry.name,
                                           kind, sys_root))
            except (OSError, RuntimeError, ValueError):
                continue
        return found
    ports = candidates('tty', 'ttyACM*', port)
    if len(ports) != 1:
        raise RuntimeError(f'Select one CapKey CDC with --port; found {[p["path"] for p in ports]}')
    cdc = ports[0]
    raw = [p for p in candidates('hidraw', 'hidraw*', hidraw)
           if (p['usb_path'], p['usb_serial']) == (cdc['usb_path'], cdc['usb_serial'])]
    if len(raw) != 1:
        raise RuntimeError(f'Select one matching keyboard --hidraw; found {[p["path"] for p in raw]}')
    events = [p for p in candidates('input', 'event*', evdev)
              if (p['usb_path'], p['usb_serial'], p['hid_path']) ==
              (cdc['usb_path'], cdc['usb_serial'], raw[0]['hid_path'])]
    if len(events) != 1 or not raw[0]['hid_path']:
        raise RuntimeError(f'Select one matching keyboard --evdev; found {[p["path"] for p in events]}')
    return {'cdc':cdc, 'hidraw':raw[0], 'evdev':events[0]}


class IsolatedKeyboard:
    def __init__(self, devices):
        self.devices = devices
        self.evdev = self.hidraw = None
        self.grabbed = False
        self.caps_lock = False

    @staticmethod
    def check_node(fd, identity):
        info = os.fstat(fd)
        expected = (Path(identity['class_path']) / 'dev').read_text().strip()
        if not stat.S_ISCHR(info.st_mode) or f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}' != expected:
            raise RuntimeError(f'Device identity changed while opening {identity["path"]}')

    def open(self):
        event_path = self.devices['evdev']['path']
        try:
            self.evdev = os.open(event_path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            self.check_node(self.evdev, self.devices['evdev'])
            bus, vendor, product, _ = struct.unpack('HHHH', ioctl_bytes(self.evdev, ior('E', 2, 8), 8))
            if (bus, vendor, product) != (3, VID, PID):
                raise RuntimeError('evdev ioctl identity does not match CapKey USB')
            fcntl.ioctl(self.evdev, EVIOCGRAB, 1)
            self.grabbed = True
        except (OSError, RuntimeError) as error:
            self.close()
            raise RuntimeError(f'Cannot open and EVIOCGRAB {event_path}: {error}. '
                               f'Read access and an exclusive grab on this exact input node are required; '
                               'no serial port was opened and no diagnostic keys were sent.') from error
        try:
            supported = ioctl_bytes(self.evdev, ior('E', 0x21, 96), 96)
            for key in (30, 44, 28, 57, 42):  # A, Z, Enter, Space, Left Shift.
                if not supported[key // 8] & (1 << (key % 8)):
                    raise RuntimeError(f'{event_path} is not a keyboard input interface')
            if pressed_keys(self.evdev):
                raise RuntimeError('Keyboard already has held keys; no diagnostic commands sent')
            self.caps_lock = bool(ioctl_bytes(self.evdev, ior('E', 0x19, 8), 8)[0] & 2)
            self.hidraw = os.open(self.devices['hidraw']['path'], os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            self.check_node(self.hidraw, self.devices['hidraw'])
            bus, vendor, product = struct.unpack('IHH', ioctl_bytes(self.hidraw, ior('H', 3, 8), 8))
            if (bus, vendor, product) != (3, VID, PID):
                raise RuntimeError('hidraw ioctl identity does not match CapKey USB')
            return self
        except Exception:
            self.close()
            raise

    def close(self):
        if self.hidraw is not None:
            os.close(self.hidraw)
            self.hidraw = None
        if self.evdev is not None:
            if self.grabbed:
                try:
                    fcntl.ioctl(self.evdev, EVIOCGRAB, 0)
                except OSError:
                    pass
            os.close(self.evdev)
            self.evdev = None
            self.grabbed = False


class Collector:
    def __init__(self, keyboard):
        self.keyboard = keyboard
        self.reports, self.events = [], []

    def poll(self, timeout=0):
        ready, _, _ = select.select([self.keyboard.hidraw, self.keyboard.evdev], [], [], timeout)
        for fd in ready:
            while True:
                try:
                    data = os.read(fd, 64 if fd == self.keyboard.hidraw else INPUT_EVENT.size * 64)
                except BlockingIOError:
                    break
                if not data:
                    raise RuntimeError('Keyboard disconnected during verification')
                if fd == self.keyboard.hidraw:
                    self.reports.append({'monotonic_ns':time.monotonic_ns(), 'hex':data.hex()})
                else:
                    if len(data) % INPUT_EVENT.size:
                        raise RuntimeError('Truncated evdev input record')
                    for offset in range(0, len(data), INPUT_EVENT.size):
                        sec, usec, kind, code, value = INPUT_EVENT.unpack_from(data, offset)
                        if kind == 0 and code == 3:
                            raise RuntimeError('evdev SYN_DROPPED: host input evidence lost')
                        if kind == 1:
                            self.events.append({'kernel_us':sec*1000000+usec, 'code':code, 'value':value})

    def quiet(self, seconds=.04):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.poll(min(.01, max(0, deadline-time.monotonic())))


PLAIN = '1234567890-=[]\\;\'`,./'
SHIFTED = '!@#$%^&*()_+{}|:"~<>?'
USAGES = list(range(0x1e, 0x28)) + [0x2d,0x2e,0x2f,0x30,0x31,0x33,0x34,0x35,0x36,0x37,0x38]
SPECIAL = {'Backspace':0x2a, 'Tab':0x2b, 'Enter':0x28, 'Escape':0x29,
           'ArrowUp':0x52, 'ArrowDown':0x51}
LINUX_LETTERS = [30,48,46,32,18,33,34,35,23,36,37,38,50,49,24,25,16,19,31,20,22,47,17,45,21,44]
LINUX_USAGE = dict(zip(range(4,30), LINUX_LETTERS))
LINUX_USAGE.update(dict(zip(range(0x1e,0x28), range(2,12))))
LINUX_USAGE.update(dict(zip(USAGES[10:], [12,13,26,27,43,39,40,41,51,52,53])))
LINUX_USAGE.update({0x28:28,0x29:1,0x2a:14,0x2b:15,0x2c:57,0x52:103,0x51:108})


def expected_press(key, caps_lock=False):
    shift = False
    if key in SPECIAL:
        usage = SPECIAL[key]
    elif len(key) == 1 and key.isascii() and key.isalpha():
        usage = 4 + ord(key.lower()) - ord('a')
        shift = key.isupper() != caps_lock
    elif key == ' ':
        usage = 0x2c
    elif key in PLAIN:
        usage = USAGES[PLAIN.index(key)]
    elif key in SHIFTED:
        usage = USAGES[SHIFTED.index(key)]
        shift = True
    else:
        raise ValueError(f'No US keyboard expectation for {key!r}')
    return bytes([2 if shift else 0, 0, usage, 0, 0, 0, 0, 0])


def validate_reports(reports, expected):
    actual = [bytes.fromhex(r['hex']) for r in reports]
    if any(len(r) != 8 or r[1] != 0 for r in actual):
        raise AssertionError('Expected 8-byte boot keyboard reports with zero reserved byte')
    wanted = [] if expected is None else [expected, ZERO]
    if actual != wanted:
        raise AssertionError(f'HID reports differ: actual={[r.hex() for r in actual]}, '
                             f'expected={[r.hex() for r in wanted]}')


def validate_events(events, expected):
    keys = [] if expected is None else [LINUX_USAGE[expected[2]]] + ([42] if expected[0] else [])
    wanted = Counter((key, value) for key in keys for value in (1,0))
    if Counter((e['code'],e['value']) for e in events) != wanted:
        raise AssertionError(f'Unexpected evdev presses/releases: {events}')
    held = set()
    for event in events:
        key, value = event['code'], event['value']
        if value == 1:
            if key in held:
                raise AssertionError('Duplicate press or repeat')
            held.add(key)
        elif value == 0:
            if key not in held:
                raise AssertionError('Release without matching press')
            held.remove(key)
        else:
            raise AssertionError('Unexpected keyboard autorepeat')
    if held:
        raise AssertionError('Keys or modifiers remain pressed')


@dataclass
class Case:
    command: str
    key: str | None
    label: str
    shift_pending: bool = False


def cases():
    out = [Case(f'HIDCHAR {{token}} {code}',chr(code),f'ASCII {code}') for code in range(32,127)]
    out += [Case(f'HIDCHAR {{token}} {code}',key,key)
            for code,key in ((8,'Backspace'),(9,'Tab'),(10,'Enter'),(27,'Escape'))]
    for grid,gesture,direction,key in ((5,1,0,'o'),(5,2,0,'O'),(5,4,2,'p'),(5,3,6,'g'),
                                      (5,5,3,'B'),(5,7,0,'5'),
                                      (11,1,0,'Backspace'),(12,1,0,' '),(15,1,0,'Enter'),
                                      (6,3,1,'ArrowUp'),(6,3,5,'ArrowDown')):
        out.append(Case(f'HID {{token}} {grid} {gesture} {direction}',key,'binding '+key))
    out += [Case(f'HID {{token}} {grid} 7 0',digit,'digit '+digit)
            for grid,digit in zip((0,1,2,4,5,6,8,9,10),'123456789')]
    out += [Case('HID {token} 3 1 0','0','zero tap'),
            Case('HID {token} 7 1 0',None,'arm Shift',True),
            Case('HIDCHAR {token} 97','A','one-shot Shift+A'),
            Case('HIDCHAR {token} 97','a','Shift consumed'),
            Case('HID {token} 7 1 0',None,'arm Shift for cancellation',True),
            Case('HID {token} 7 1 0',None,'cancel Shift'),
            Case('HIDCHAR {token} 97','a','Shift cancelled')]
    out += [Case('HIDCHAR {token} 97','a',f'repeated a {i}') for i in range(5)]
    return out


class Cdc:
    def __init__(self, connection, collector):
        self.connection, self.collector = connection, collector
        self.decoder, self.pending = StreamDecoder(), deque()
        self.sequence = 0

    def wait(self, predicate, seconds=3):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            self.collector.poll()
            if not self.pending:
                self.pending.extend(self.decoder.feed(self.connection.read(4096)))
            while self.pending:
                record = self.pending.popleft()
                if predicate(record):
                    return record
        raise RuntimeError('Timed out waiting for a fenced CDC response')

    def status(self):
        self.sequence += 1
        token = f'hidstatus-{self.sequence}'
        self.connection.write(f'MARK {token}\nSTATUS\n'.encode())
        self.wait(lambda r:r['type']=='marker' and r['token']==token)
        return self.wait(lambda r:r['type']=='metadata')


def run_tests(connection, collector, caps_lock, report):
    cdc = Cdc(connection, collector)
    report['decoder'] = cdc.decoder.counters  # Live counters also survive a failed case.
    report['initial_metadata'] = initial = cdc.status()
    if (initial.get('output_backend') != 'usb_hid' or initial.get('hid_layout') != 'US' or
            not initial.get('hid_mounted') or initial.get('hid_suspended') or
            initial.get('hid_shift_pending') or initial.get('hid_queue_depth') != 0):
        raise RuntimeError('Firmware is not an idle, mounted US HID keyboard with clear Shift state')
    collector.quiet()
    if any(bytes.fromhex(r['hex']) != ZERO for r in collector.reports) or collector.events:
        raise RuntimeError('Unexpected keyboard activity before test; no diagnostic HID command sent')
    report['startup_reports'] = list(collector.reports)
    consumed = (len(collector.reports),len(collector.events))
    for case in cases():
        before = cdc.status()
        collector.quiet()
        if consumed != (len(collector.reports),len(collector.events)):
            raise AssertionError('Unrequested keyboard activity between cases')
        if before['boot_id'] != initial['boot_id'] or pressed_keys(collector.keyboard.evdev):
            raise RuntimeError('Device restarted or keyboard not released before test')
        token = f'hidtest-{len(report["tests"])}'
        command = case.command.replace('{token}', token)
        expected = None if case.key is None else expected_press(case.key,caps_lock)
        attempt = dict(asdict(case), command=command, expected_reports=[] if expected is None else
                       [expected.hex(),ZERO.hex()], passed=False)
        report['tests'].append(attempt)
        report['diagnostic_commands_sent'] += 1
        connection.write((command+'\n').encode())
        ack = cdc.wait(lambda r:r['type']=='marker' and r['token']==token)
        if ack.get('hid_accepted') is not True:
            raise AssertionError(f'{case.label}: firmware rejected action')
        deadline = time.monotonic()+3
        counter = 'hid_state_actions' if case.key is None else 'hid_completed'
        while True:
            after = cdc.status()
            if after['boot_id'] != initial['boot_id']:
                raise RuntimeError('Device restarted during verification')
            if after[counter] == before[counter]+1:
                break
            if after[counter] > before[counter]+1 or time.monotonic() >= deadline:
                raise AssertionError(f'{case.label}: unexpected completion counter {after[counter]}')
        collector.quiet(.06)
        attempt.update(reports=collector.reports[consumed[0]:], events=collector.events[consumed[1]:],
                       metadata=after, acknowledgement=ack)
        validate_reports(attempt['reports'],expected)
        validate_events(attempt['events'],expected)
        if pressed_keys(collector.keyboard.evdev):
            raise AssertionError('Kernel reports held keys after release')
        for key in ('hid_failed','hid_queue_drops'):
            if after[key] != before[key]:
                raise AssertionError(f'{key} increased')
        other = 'hid_completed' if case.key is None else 'hid_state_actions'
        if (after['hid_enqueued'] != before['hid_enqueued']+1 or after[other] != before[other] or
                after['hid_shift_pending'] is not case.shift_pending or after['hid_queue_depth'] != 0):
            raise AssertionError('HID queue/modifier state did not match the action')
        attempt['passed'] = True
        consumed = (len(collector.reports),len(collector.events))
    report['final_metadata'] = cdc.status()
    collector.quiet()
    if consumed != (len(collector.reports),len(collector.events)):
        raise AssertionError('Unexpected trailing keyboard activity')
    report['decoder'] = cdc.decoder.status()
    report['passed'] = True



def await_release(keyboard, collector, report, snapshot):
    """Keep the grab through a failed test until kernel keys clear or USB leaves."""
    warned = False
    while True:
        try:
            keys = pressed_keys(keyboard.evdev)
            if not keys:
                report['release_confirmed'] = True
                report['waiting_for_release'] = False
                return
        except OSError as error:
            if error.errno in (errno.ENODEV, errno.ENXIO):
                report['device_disconnected_during_cleanup'] = True
                return
            keys = None
            report['release_check_error'] = str(error)
        except KeyboardInterrupt:
            continue
        if not warned:
            report['waiting_for_release'] = True
            report['held_keys_at_cleanup'] = keys
            snapshot()
            print(f'Keeping EVIOCGRAB on {keyboard.devices["evdev"]["path"]}: '
                  'release is not confirmed. Release the touch or disconnect CapKey; '
                  'no further keys are sent.', file=sys.stderr)
            warned = True
        try:
            collector.poll(.1)
        except (OSError,RuntimeError) as error:
            # A lost hidraw record does not establish that evdev keys released.
            report['cleanup_note'] = str(error)
            time.sleep(.05)
        except KeyboardInterrupt:
            continue


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', help='CapKey CDC node; autodetect only when unique')
    parser.add_argument('--hidraw', help='Matching /dev/hidrawN; autodetect when unique')
    parser.add_argument('--evdev', help='Matching /dev/input/eventN to EVIOCGRAB; autodetect when unique')
    parser.add_argument('--output', type=Path, required=True, help='New JSON results file, including preflight failures')
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    try:
        output = args.output.open('x')
    except FileExistsError:
        parser.error('Choose a new output path; existing evidence is never overwritten')
    report = {'passed':False,'method':'hidraw plus exclusive evdev grab','tests':[],
              'diagnostic_commands_sent':0,'permissions_required':'Read hidraw and evdev; EVIOCGRAB; read/write CDC'}
    keyboard = collector = connection = None
    try:
        report['devices'] = devices = discover(args.port,args.hidraw,args.evdev)
        keyboard = IsolatedKeyboard(devices).open()
        report['exclusive_grab_confirmed'] = True
        report['host_caps_lock'] = keyboard.caps_lock
        collector = Collector(keyboard)
        # Import/open CDC only after the matching evdev is successfully grabbed.
        import serial
        connection = serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=1)
        connection.dtr,connection.rts,connection.port = True,False,devices['cdc']['path']
        connection.open()
        run_tests(connection,collector,keyboard.caps_lock,report)
    except (Exception,KeyboardInterrupt) as error:
        report['error'] = f'{type(error).__name__}: {error}'
    finally:
        if connection:
            connection.close()
        if collector:
            report['all_hidraw_reports'] = collector.reports
            report['all_evdev_key_events'] = collector.events
        # On an unusual partial-press failure, keep isolation until the actual
        # release/disconnect; never send another key as a cleanup workaround.
        if keyboard and report['diagnostic_commands_sent']:
            def snapshot():
                output.seek(0);output.truncate();json.dump(report,output,indent=2);output.flush()
            await_release(keyboard,collector,report,snapshot)
        if keyboard:
            keyboard.close()
        output.seek(0);output.truncate();json.dump(report,output,indent=2);output.write('\n');output.close()
        print(json.dumps({'passed':report['passed'],'tests':len(report['tests']),
                          'diagnostic_commands_sent':report['diagnostic_commands_sent'],
                          'output':str(args.output),'error':report.get('error')}),flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
