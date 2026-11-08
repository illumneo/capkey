"""Recorder lifecycle tests: mocked devices only, no hardware reads or writes."""
from collections import deque
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import record_typing


class RecorderLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.session = self.root / 'session'
        self.executable = self.root / 'frozen-replay'
        self.executable.write_bytes(b'frozen executable')
        self.state = {
            'session_dir': None, 'capture_start_token': 'start-token',
            'latest_metadata': {'elf_sha256': 'installed-elf', 'recognizer_sha256': 'identity'},
            'running': False, 'errors': [], 'quality': {'clean': True, 'issues': []},
        }
        self.pending = deque()
        self.capture = Mock()
        self.capture.status.side_effect = lambda: dict(self.state)
        self.capture.start.side_effect = self.start
        self.capture.stop.side_effect = self.stop
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        def patched(name, **kwargs):
            return self.stack.enter_context(patch.object(record_typing, name, **kwargs))
        patched('CaptureSession', return_value=self.capture)
        self.identity = patched('source_identity', return_value='identity')
        self.build = patched('build_host', return_value=(self.executable, 'host-sha'))
        patched('discover', return_value={'hidraw': {'path': '/dev/fake-hid'}, 'cdc': {'path': '/dev/fake-cdc'}})
        self.open = self.stack.enter_context(patch.object(record_typing.os, 'open', return_value=42))
        self.close = self.stack.enter_context(patch.object(record_typing.os, 'close'))
        self.stack.enter_context(patch.object(record_typing.os, 'read', side_effect=lambda *_: self.pending.popleft()))
        self.stack.enter_context(patch.object(record_typing.select, 'select', side_effect=lambda *_: ([42] if self.pending else [], [], [])))
        self.replay = patched('replay', return_value={'device_parity': {'matched': True}})

    def start(self, port, path, metadata):
        self.assertEqual(port, '/dev/fake-cdc')
        path.mkdir()
        self.state.update(session_dir=str(path), running=True)
        (path / 'frames.jsonl').write_text('')
        (path / 'stop-request').write_text('stop')

    def stop(self):
        self.close.assert_not_called()
        self.state['running'] = False
        return dict(self.state)

    def run_main(self):
        with redirect_stdout(io.StringIO()):
            return record_typing.main(['--session-dir', str(self.session), '--duration', '1'])

    def report(self):
        return json.loads((self.session / 'typing-recording.json').read_text())

    def test_interrupted_handshake_saves_clean_capture_without_unbound_replay_state(self):
        self.capture.wait_for_marker.side_effect = KeyboardInterrupt
        self.assertEqual(self.run_main(), 0)
        report = self.report()
        self.assertEqual(report['stop_reason'], 'interrupted')
        self.assertIn('not established', report['replay_skipped'])
        self.replay.assert_not_called()
        self.capture.stop.assert_called_once()
        self.close.assert_called_once_with(42)
        self.assertEqual((self.session / 'hidraw.jsonl').read_text(), '')

    def test_hid_open_failure_never_starts_serial_or_stops_unstarted_capture(self):
        self.open.side_effect = PermissionError('HID permission denied')
        self.assertEqual(self.run_main(), 2)
        self.capture.start.assert_not_called()
        self.capture.stop.assert_not_called()
        self.close.assert_not_called()
        self.assertFalse(self.session.exists())

    def test_partial_start_and_shutdown_failures_preserve_original_error_and_close_hid(self):
        def partial_start(*args):
            self.start(*args)
            raise OSError('serial start failed')
        self.capture.start.side_effect = partial_start
        self.capture.stop.side_effect = RuntimeError('shutdown failed')
        self.assertEqual(self.run_main(), 2)
        report = self.report()
        self.assertIn('serial start failed', report['error'])
        self.assertIn('shutdown failed', report['error'])
        self.close.assert_called_once_with(42)
        self.replay.assert_not_called()

    def test_report_during_stop_is_drained_before_hid_close(self):
        reports = [bytes([0, 0, 4, 0, 0, 0, 0, 0]), bytes(8)]
        def final_reports():
            result = self.stop()
            self.pending.extend(reports)
            return result
        self.capture.stop.side_effect = final_reports
        self.assertEqual(self.run_main(), 0)
        captured = [json.loads(line) for line in (self.session / 'hidraw.jsonl').read_text().splitlines()]
        self.assertEqual([row['hex'] for row in captured], [row.hex() for row in reports])
        self.assertEqual(self.report()['hid_reports'], 2)
        self.close.assert_called_once_with(42)

    def test_source_changed_after_start_still_uses_frozen_executable(self):
        def change_source(*args):
            self.start(*args)
            self.identity.return_value = 'different-after-start'
        self.capture.start.side_effect = change_source
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.identity.call_count, 2)
        self.build.assert_called_once()
        args, kwargs = self.replay.call_args
        self.assertEqual(args[4:6], (self.executable, 'host-sha'))
        self.assertTrue(kwargs['verify_device'])
        self.assertTrue(self.report()['matching_replay_source'])
        self.assertIn('replay', self.report())

    def test_replay_failure_preserves_recording_and_explicit_failed_result(self):
        self.replay.side_effect = ValueError('device parity mismatch')
        self.assertEqual(self.run_main(), 2)
        self.assertIn('device parity mismatch', self.report()['error'])
        self.assertTrue((self.session / 'hidraw.jsonl').exists())
        self.assertTrue((self.session / 'input-context.json').exists())
        self.close.assert_called_once_with(42)

    def test_directory_race_does_not_write_another_sessions_report(self):
        def foreign_directory(*args):
            self.session.mkdir()
            (self.session / 'owner').write_text('other process')
            raise FileExistsError('session already created')
        self.capture.start.side_effect = foreign_directory
        self.assertEqual(self.run_main(), 2)
        self.assertEqual(sorted(p.name for p in self.session.iterdir()), ['owner'])
        self.close.assert_called_once_with(42)


if __name__ == '__main__':
    unittest.main()
