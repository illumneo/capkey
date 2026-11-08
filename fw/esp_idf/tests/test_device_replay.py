"""Device parity checks use fabricated protocol events, not physical accuracy claims."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import replay_capture as replay
from test_replay import metadata, sample


def event(kind, scan, timestamp, sequence, epoch=0, **fields):
    return dict(type='device_event', event=kind, boot_id=123, scan_seq=scan,
                timestamp_us=timestamp, event_seq=sequence, processing_epoch=epoch, **fields)


def checkpoint(scan=0, timestamp=0, sequence=0):
    return event('idle_checkpoint', scan, timestamp, sequence)


def tap(sequence=1, **changes):
    result = event('gesture', 3, 60000, sequence, model='pcb', x=0, y=0, z=0,
                   start_x=0, start_y=0, max_distance=0, gesture_type=1, direction=0,
                   grid_position=0, action={'type': 'char', 'char_code': 97, 'label': 'a'},
                   output_backend='log_only', hid_sent=False)
    result.update(changes)
    return result


class DeviceReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.host, cls.digest = replay.build_host(Path(cls.temp.name) / 'host')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_records(self, records, verify=True, policy='error'):
        path = Path(self.temp.name) / 'frames.jsonl'
        path.write_text(''.join(json.dumps(dict(record, packet_seq=i)) + '\n'
                                for i, record in enumerate(records)))
        self.results = []
        return replay.replay(path, 'pcb', policy, self.results.append,
                             self.host, self.digest, verify_device=verify)

    def trace(self):
        return [metadata(), sample(0, 0), checkpoint(),
                sample(20000, 1, {11: 6000, 1: 6000}),
                sample(40000, 2, {11: 6000, 1: 6000}), sample(60000, 3), tap(),
                sample(80000, 4)]

    def test_matching_decisions(self):
        result = self.run_records(self.trace())
        self.assertEqual(result['device_parity'], dict(synchronized_segments=1, compared_gestures=1,
            matched_gestures=1, mismatches=0, ignored_before_sync=0, samples_after_sync=4, verified=True))
        self.assertEqual(result['detector_resets'], 0)
        self.assertEqual(sum(r['type'] == 'device_event' for r in self.results), 2)

    def test_mismatch_is_reported_and_fails_verification(self):
        for change in ({'gesture_type': 3}, {'start_x': .1}, {'grid_position': 1},
                       {'action': {'type': 'char', 'char_code': 98, 'label': 'b'}}):
            with self.subTest(change=change):
                records = self.trace()
                records[-2].update(change)
                with self.assertRaisesRegex(replay.ReplayError, 'verification failed'):
                    self.run_records(records)
                self.assertEqual(self.results[-1]['device_parity']['mismatches'], 1)

    def test_missing_event_detected_even_when_capture_ends_on_release(self):
        with self.assertRaisesRegex(replay.ReplayError, 'verification failed'):
            self.run_records(self.trace()[:-2])
        self.assertEqual(self.results[-1]['device_parity']['mismatches'], 1)
        self.assertEqual(self.results[-2]['reason'], 'missing_device_gesture')

    def test_duplicate_event_is_not_paired_with_a_later_gesture(self):
        records = self.trace()
        records.insert(-1, tap(sequence=2))
        with self.assertRaisesRegex(replay.ReplayError, 'verification failed'):
            self.run_records(records)
        self.assertTrue(any(r.get('reason') == 'unexpected_device_gesture' for r in self.results))

    def test_no_checkpoint_cannot_claim_verification(self):
        records = [r for r in self.trace() if r.get('event') != 'idle_checkpoint']
        with self.assertRaisesRegex(replay.ReplayError, 'verification failed'):
            self.run_records(records)
        parity = self.results[-1]['device_parity']
        self.assertEqual(parity['ignored_before_sync'], 1)
        self.assertEqual(parity['compared_gestures'], 0)

    def test_ordinary_experimental_replay_preserves_device_events_without_forcing_parity(self):
        records = self.trace()
        records[-2]['gesture_type'] = 99
        result = self.run_records(records, verify=False)
        self.assertNotIn('device_parity', result)
        self.assertEqual(sum(r['type'] == 'device_event' for r in self.results), 2)

    def test_midcontact_start_waits_for_checkpoint_then_verifies_next_contact(self):
        records = [metadata(), sample(20000, 1, {11: 6000, 1: 6000}), sample(60000, 2),
                   tap(scan_seq=2), checkpoint(2, 60000, 2),
                   sample(80000, 3, {11: 6000, 1: 6000}),
                   sample(100000, 4, {11: 6000, 1: 6000}), sample(120000, 5),
                   tap(sequence=3, scan_seq=5, timestamp_us=120000)]
        result = self.run_records(records)
        self.assertEqual(result['device_parity']['ignored_before_sync'], 1)
        self.assertEqual(result['device_parity']['matched_gestures'], 1)

    def test_checkpoint_must_reference_the_preceding_sample(self):
        with self.assertRaisesRegex(replay.ReplayError, 'checkpoint does not follow'):
            self.run_records([metadata(), sample(0, 0), checkpoint(1, 20000)])

    def test_processing_reset_is_an_explicit_discontinuity(self):
        records = [metadata(), sample(0, 0), checkpoint(),
                   event('processing_reset', 0, 0, 1, epoch=1, reason='invalid_mask')]
        with self.assertRaisesRegex(replay.ReplayError, 'device processing reset'):
            self.run_records(records)
        result = self.run_records(records, verify=False, policy='reset')
        self.assertFalse(result['continuous'])
        self.assertEqual(result['detector_resets'], 1)

    def test_event_sequence_loss_is_visible_even_with_contiguous_packet_numbers(self):
        records = self.trace()
        records[-2]['event_seq'] = 3
        with self.assertRaisesRegex(replay.ReplayError, 'verification failed'):
            self.run_records(records)
        self.assertTrue(any(r.get('reason') == 'device_event_sequence_gap' for r in self.results))

    def test_lost_tail_bundle_is_detected_by_counters_without_a_later_scan(self):
        for counter in ('telemetry_dropped_samples', 'telemetry_dropped_events', 'transport_failures'):
            with self.subTest(counter=counter):
                records = self.trace()
                records[2][counter] = 10
                final = metadata()
                final[counter] = 11
                records.append(final)
                with self.assertRaisesRegex(replay.ReplayError, counter + ' changed'):
                    self.run_records(records)

    def test_drops_before_capture_are_baselined(self):
        records = self.trace()
        records[2]['telemetry_dropped_samples'] = 10
        records[-2]['telemetry_dropped_samples'] = 10
        self.assertTrue(self.run_records(records)['device_parity']['verified'])

    def test_checkpoint_cannot_discard_an_active_onset(self):
        with self.assertRaisesRegex(replay.ReplayError, 'above the release threshold'):
            self.run_records([metadata(), sample(0, 0, {11: 6000, 1: 6000}), checkpoint()])

    def test_boolean_gesture_enum_is_not_an_integer(self):
        records = self.trace()
        records[-2]['gesture_type'] = True
        with self.assertRaisesRegex(replay.ReplayError, 'gesture_type must be an integer'):
            self.run_records(records)

    def test_checkpoint_at_eof_has_no_verified_sample_coverage(self):
        with self.assertRaisesRegex(replay.ReplayError, 'verification failed'):
            self.run_records([metadata(), sample(0, 0), checkpoint()])
        self.assertEqual(self.results[-1]['device_parity']['samples_after_sync'], 0)

    def test_idle_only_verification_reports_zero_compared_gestures(self):
        result = self.run_records([metadata(), sample(0, 0), checkpoint(), sample(20000, 1)])
        self.assertTrue(result['device_parity']['verified'])
        self.assertEqual(result['device_parity']['compared_gestures'], 0)


if __name__ == '__main__':
    unittest.main()
