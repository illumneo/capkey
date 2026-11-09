#!/usr/bin/env python3
"""Passively record CapKey touches and real HID reports during ordinary typing.

No keyboard grab, injected keystrokes, browser, or prescribed text. The recording
stops after a bounded duration, Ctrl-C, or creation of SESSION/stop-request.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import select
import time

from capture_session import CaptureSession
from replay_capture import build_host, replay
from verify_hid_device import discover

ROOT = Path(__file__).resolve().parents[1]


def source_identity():
    """Use the same file list and hash construction as the firmware build."""
    cmake = (ROOT / 'main/CMakeLists.txt').read_text()
    match = re.search(r'foreach\(SWIPE_SOURCE (.*?)\)', cmake, re.S)
    if match is None:
        raise ValueError('Firmware source identity list is missing')
    text = ''.join(f'{name}:{hashlib.sha256((ROOT/"main"/name).read_bytes()).hexdigest()}\n'
                   for name in match.group(1).split())
    return hashlib.sha256(text.encode()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=600, help='Maximum seconds (default: 600)')
    parser.add_argument('--session-dir', type=Path, help='New output directory; existing paths are refused')
    parser.add_argument('--port', help='Select a CapKey CDC port when needed')
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or not 0 < args.duration <= 86400:
        parser.error('--duration must be finite and between 0 and 86400 seconds')
    path = (args.session_dir or ROOT / '.calibration/sessions' / datetime.now().strftime('typing-%Y%m%d-%H%M%S')).expanduser().resolve()
    if path.exists():
        parser.error(f'Session already exists: {path}')
    # Freeze the executable before recording. Later source edits must not
    # silently change the model used to verify this session on completion.
    identity = source_identity()
    executable, host_sha = build_host()
    source_stable = source_identity() == identity
    devices = discover(port=args.port)
    capture = CaptureSession()
    descriptor = None
    output = None
    capture_attempted = False
    matching_source = False
    replay_skip_reason = 'Source compatibility was not established before recording stopped.'
    report_count = 0
    report = {'purpose':'physical_typing_to_real_USB_HID', 'mode':'free_typing',
              'intended_text':None, 'device_identity':devices, 'exclusive_grab':False,
              'diagnostic_HID_commands_sent':0, 'maximum_duration_seconds':args.duration,
              'replay_source_sha256':host_sha, 'replay_recognizer_sha256':identity,
              'replay_executable':str(executable),
              'replay_executable_sha256':hashlib.sha256(executable.read_bytes()).hexdigest()}
    def error(message):
        report.setdefault('errors', []).append(message)
        report['error'] = '; '.join(report['errors'])

    def consume_hid(timeout):
        nonlocal report_count
        if not select.select([descriptor], [], [], timeout)[0]:
            return False
        try:
            data = os.read(descriptor, 64)
        except BlockingIOError:
            return False
        if not data:
            raise RuntimeError('CapKey disconnected')
        output.write(json.dumps({'host_monotonic_ns':time.monotonic_ns(), 'hex':data.hex()})+'\n')
        output.flush()
        report_count += 1
        return True

    try:
        descriptor = os.open(devices['hidraw']['path'], os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        capture_attempted = True
        capture.start(devices['cdc']['path'], path, report)
        # Keep the file and HID descriptor alive through capture.stop(): its
        # bounded STOP drain may still archive gestures whose USB release is queued.
        output = (path/'hidraw.jsonl').open('x')
        (path/'input-context.json').write_text(json.dumps({
            'mode':'free_typing', 'intended_text':None,
            'instruction':'Use CapKey normally; no prescribed test phrase.',
            'note':'Only CapKey input is recorded. Normal keyboard output remains active.'}, indent=2)+'\n')
        capture.wait_for_marker(capture.status()['capture_start_token'], 5)
        initial = capture.status()['latest_metadata']
        report['installed_elf_sha256'] = initial['elf_sha256']
        report['installed_recognizer_sha256'] = initial['recognizer_sha256']
        matching_source = source_stable and initial['recognizer_sha256'] == identity
        replay_skip_reason = 'Installed recognizer differs from source frozen at recording start.'
        report['matching_replay_source'] = matching_source
        (path/'installed-metadata.json').write_text(json.dumps(initial, indent=2)+'\n')
        print(json.dumps({'recording':str(path), 'normal_HID_output_active':True,
                          'installed_elf_sha256':initial['elf_sha256'],
                          'matching_replay_source':matching_source}), flush=True)
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline and not (path/'stop-request').exists():
            status = capture.status()
            if not status['running']:
                raise RuntimeError(status['errors'])
            consume_hid(.05)
        report['stop_reason'] = 'stop_requested' if (path/'stop-request').exists() else 'duration_limit'
    except KeyboardInterrupt:
        report['stop_reason'] = 'interrupted'
    except Exception as exc:
        error(f'{type(exc).__name__}: {exc}')
    finally:
        # CaptureSession.stop is safe after partial start; avoid touching it at
        # all when opening HID failed before a serial start was attempted.
        try:
            report['capture'] = capture.stop() if capture_attempted else capture.status()
        except (Exception, KeyboardInterrupt) as exc:
            error(f'Capture shutdown failed: {type(exc).__name__}: {exc}')
            report['capture'] = capture.status()
        try:
            if descriptor is not None and output is not None:
                # Collect buffered presses/releases, including those delivered
                # during STOP. Require a short quiet interval, with a hard bound.
                deadline = time.monotonic() + .25
                while consume_hid(.05):
                    if time.monotonic() >= deadline:
                        error('HID remained active after capture stop; report boundary is unsettled')
                        break
        except (Exception, KeyboardInterrupt) as exc:
            error(f'Final HID drain failed: {type(exc).__name__}: {exc}')
        finally:
            if output is not None:
                try:
                    output.close()
                except OSError as exc:
                    error(f'Closing HID log failed: {exc}')
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError as exc:
                    error(f'Closing HID descriptor failed: {exc}')
        report['hid_reports'] = report_count

    # A path that appeared concurrently may belong to another recorder. Only
    # write the directory that CaptureSession confirms it actually created.
    owns_session = report['capture'].get('session_dir') == str(path)
    def persist_report():
        if owns_session:
            (path/'typing-recording.json').write_text(json.dumps(report, indent=2)+'\n')
    persist_report()
    if report.get('error') or not report['capture']['quality']['clean']:
        print(json.dumps({'session':str(path), 'error':report.get('error'),
                          'quality':report['capture']['quality']}), flush=True)
        return 2
    if not matching_source:
        report['replay_skipped'] = replay_skip_reason
        persist_report()
        print(json.dumps({'session':str(path), 'saved':True,
                          'replay_skipped':replay_skip_reason}), flush=True)
        return 0
    try:
        with (path/'verified-replay.jsonl').open('x') as replay_output:
            summary = replay(path/'frames.jsonl', 'pcb', 'error',
                             lambda row: replay_output.write(json.dumps(row,separators=(',',':'))+'\n'),
                             executable, host_sha, verify_device=True)
        (path/'replay-result.json').write_text(json.dumps(summary, indent=2)+'\n')
        report['replay'] = summary
    except (Exception, KeyboardInterrupt) as exc:
        error(f'Replay verification failed: {type(exc).__name__}: {exc}')
        persist_report()
        print(json.dumps({'session':str(path), 'saved':True, 'error':report['error']}), flush=True)
        return 2
    persist_report()
    print(json.dumps({'session':str(path), 'quality_clean':True,
                      'reports':report_count, 'replay':summary}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
