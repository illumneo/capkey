"""Offline correction evidence tests; no serial/input devices or GUI."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from analyze_corrections import event_tokens,infer_corrections,load_session,read_jsonl,analyze_hid_log,completion_tokens,analyze_history
from verify_hid_device import expected_press


def token(key, i, *, kind=None, seconds=None, boot=1):
    return dict(key=key,kind=kind or ('backspace' if key=='Backspace' else 'char'),
                timestamp_us=int((i if seconds is None else seconds)*1e6),
                scan_seq=10+i,contact=i+1,boot_id=boot,features={'max_distance':.2})


def event(action, i):
    return dict(event='gesture',action=action,scan_seq=i,timestamp_us=i*1000000,
                boot_id=1,output_backend='usb_hid',hid_queued=True,
                features={'duration_ms':200,'start_x':1,'start_y':0})


def reports(*presses):
    return [{'hex':value.hex()} for press in presses for value in (press,bytes(8))]


class CorrectionInferenceTests(unittest.TestCase):
    def test_single_correction_keeps_evidence_and_is_not_ground_truth(self):
        result=infer_corrections([token('^',0),token('Backspace',1),token('n',2)])
        pair=result['possible_corrections'][0]
        self.assertEqual((pair['original']['key'],pair['replacement']['key']),('^','n'))
        self.assertEqual(pair['original']['scan_seq'],10)
        self.assertEqual(pair['original']['features']['max_distance'],.2)
        self.assertFalse(pair['ground_truth'])
        self.assertEqual(pair['inferred_intent'],'n')

    def test_same_character_retry_is_not_error_threshold_evidence(self):
        result=infer_corrections([token('o',0),token('Backspace',1),token('o',2),
                                  token('Backspace',3),token('d',4)])
        self.assertEqual(len(result['same_character_replacements_ignored']),1)
        self.assertEqual(len(result['possible_corrections']),1)
        self.assertEqual(result['possible_corrections'][0]['original']['contact'],3)

    def test_deletion_block_cannot_become_false_one_to_one_pair(self):
        result=infer_corrections([token('a',0),token('b',1),token('c',2),
                                  token('Backspace',3),token('Backspace',4),token('n',5)])
        self.assertEqual(result['possible_corrections'],[])
        group=result['ambiguous_deletion_blocks'][0]
        self.assertEqual(group['deleted_text'],'bc')
        self.assertIsNone(group['inferred_intent'])

    def test_navigation_enter_boot_change_and_unknown_prior_text_invalidate(self):
        for boundary in ('ArrowLeft','Enter','Tab','processing_reset'):
            with self.subTest(boundary=boundary):
                result=infer_corrections([token('^',0),token(boundary,1,kind='boundary'),
                                          token('Backspace',2),token('n',3)])
                self.assertEqual(result['possible_corrections'],[])
        result=infer_corrections([token('^',0),token('Backspace',1,boot=2),token('n',2,boot=2)])
        self.assertEqual(result['possible_corrections'],[])
        self.assertEqual(infer_corrections([token('Backspace',0),token('n',1)])['possible_corrections'],[])

    def test_time_and_event_windows_reject_stale_evidence(self):
        self.assertEqual(infer_corrections([token('x',0),token('Backspace',1),
                                            token('y',2,seconds=11)])['possible_corrections'],[])
        stream=[token('x',0)]+[token('<SHIFT>',i,kind='shift',seconds=i/10) for i in range(1,10)]
        stream += [token('Backspace',10,seconds=1),token('y',11,seconds=1.1)]
        self.assertEqual(infer_corrections(stream)['possible_corrections'],[])

    def test_backspace_without_replacement_stays_unresolved(self):
        result=infer_corrections([token('x',0),token('Backspace',1)])
        self.assertEqual(result['possible_corrections'],[])
        self.assertEqual(result['invalidated'][0]['reason'],'no_replacement_before_end')

    def test_shift_consumes_no_report_and_is_consumed_by_backspace(self):
        events=[event({'type':'char','char_code':111},0),
                event({'type':'special','label':'<SHIFT>'},1),
                event({'type':'backspace'},2),event({'type':'char','char_code':100},3)]
        bs=bytes([2,0,0x2a,0,0,0,0,0])
        tokens,validation=event_tokens(events,reports(expected_press('o'),bs,expected_press('d')))
        self.assertTrue(validation['ordered_hid_match'])
        self.assertFalse(validation['final_shift_pending'])
        result=infer_corrections(tokens)
        self.assertEqual(result['possible_corrections'],[])
        self.assertTrue(next(t for t in tokens if t['kind']=='backspace')['shift_applied'])
        self.assertIn('modified_backspace',[r['reason'] for r in result['invalidated']])

    def test_shifted_letter_and_symbol_use_actual_report_order(self):
        events=[event({'type':'special','label':'<SHIFT>'},0),
                event({'type':'char','char_code':97},1),
                event({'type':'special','label':'<SHIFT>'},2),
                event({'type':'char','char_code':49},3)]
        tokens,_=event_tokens(events,reports(expected_press('A'),expected_press('!')))
        self.assertEqual([t['key'] for t in tokens if t['kind']=='char'],['A','!'])

    def test_missing_extra_or_modified_reports_fail_before_inference(self):
        events=[event({'type':'char','char_code':97},0)]
        correct=reports(expected_press('a'))
        for observed in (correct[:-1],correct+correct,
                         [{'hex':'0100040000000000'},correct[-1]],
                         [{'hex':'000004000000000000'},correct[-1]]):
            with self.subTest(observed=observed):
                with self.assertRaises(ValueError):event_tokens(events,observed)

    def test_caps_lock_is_compensated_and_absent_hid_is_explicit(self):
        events=[event({'type':'char','char_code':97},0)]
        tokens,check=event_tokens(events,reports(expected_press('a',True)),caps_lock=True)
        self.assertEqual(tokens[0]['key'],'a')
        self.assertTrue(check['ordered_hid_match'])
        self.assertFalse(event_tokens(events)[1]['ordered_hid_match'])

    def test_live_capture_and_truncated_jsonl_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'session.json').write_text(json.dumps({'running':True}))
            with self.assertRaisesRegex(ValueError,'completed'):load_session(path)
            (path/'frames.jsonl').write_text('{"type":"sample"}')
            with self.assertRaisesRegex(ValueError,'incomplete'):read_jsonl(path/'frames.jsonl')

    def test_sample_gap_is_rejected_even_with_stopped_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'session.json').write_text(json.dumps({'running':False,'stopped_at':'done'}))
            meta={'type':'metadata','boot_id':1,'packet_seq':1,'protocol_version':1,
                  'capture_decimation':1,'pad_ids':list(range(15)),'streaming':False,
                  'acquisition':{'charge_times':200}}
            rows=[meta]
            for packet,scan in [(2,1),(3,3)]:
                rows.append(dict(type='sample',boot_id=1,packet_seq=packet,scan_seq=scan,
                    timestamp_us=scan*1000,dropped_scans=0,registered_mask=0x1ffe,
                    raw_valid_mask=0x1ffe,smooth_valid_mask=0x1ffe,benchmark_valid_mask=0x1ffe,
                    raw=[0]*15,smooth=[0]*15,benchmark=[0]*15))
            (path/'frames.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            with self.assertRaisesRegex(ValueError,'scan_gaps'):load_session(path)

    def test_startup_annotation_cannot_hide_a_midstream_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'session.json').write_text(json.dumps({'running':False,'stopped_at':'done'}))
            meta={'type':'metadata','boot_id':1,'packet_seq':1,'protocol_version':1,
                  'capture_decimation':1,'pad_ids':list(range(15)),'streaming':False,
                  'acquisition':{'charge_times':200}}
            sample=dict(type='sample',boot_id=1,packet_seq=2,scan_seq=1,
                timestamp_us=1000,dropped_scans=0,registered_mask=0x1ffe,
                raw_valid_mask=0x1ffe,smooth_valid_mask=0x1ffe,benchmark_valid_mask=0x1ffe,
                raw=[0]*15,smooth=[0]*15,benchmark=[0]*15)
            rows=[meta,sample,dict(sample,packet_seq=9,capture_phase='startup')]
            (path/'frames.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            with self.assertRaisesRegex(ValueError,'Startup records'):load_session(path)


def completion(key, seq, *, caps=False, **overrides):
    press=expected_press(key,caps)
    record=dict(type='hid_log',event='completion',token='query',boot_id=1,
        completion_seq=seq,completed_us=seq*1000000+1000,timestamp_us=seq*1000000,
        usb_generation=1,processing_epoch=1,event_seq=seq,scan_seq=seq*10,diagnostic_id=0,
        duration_us=200000,hid_failed=0,hid_queue_drops=0,grid=5,gesture_type=1,direction=0,
        source='physical',start_x=1,start_y=1,end_x=1.1,end_y=1.1,peak_dx=.1,peak_dy=.1,
        max_distance=.14,path_length=.2,caps_lock=caps,shift_before=False,shift_after=False,
        state_only=False,presses=[[press[0],*press[2:]]])
    record.update(overrides)
    return record


def query_summary(records, **overrides):
    oldest=records[0]['completion_seq'] if records else 0
    latest=records[-1]['completion_seq'] if records else 0
    result=dict(type='hid_log',event='summary',token='query',boot_id=1,
        after_seq=0,oldest_seq=oldest,latest_seq=latest,overwritten=max(0,oldest-1),
        overwritten_at_end=max(0,oldest-1),retained=len(records),returned=len(records),
        lost_before_query=max(0,oldest-1),missing_during_query=0,
        hid_failed=records[-1]['hid_failed'] if records else 0,
        hid_queue_drops=records[-1]['hid_queue_drops'] if records else 0,
        error='',hid_layout='US',recognizer_sha256='a'*64,
        coherent_swipe_min_distance=.32,coherent_swipe_min_efficiency=.75,
        coherent_swipe_min_end_ratio=.8,coherent_efficiency_basis='peak/path',edge_swipe_min_distance=.12)
    result.update(overrides)
    return result


class CompletedHidLogTests(unittest.TestCase):
    def analyze_records(self, records, summary=None):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'hid-log.jsonl'
            rows=records+[summary if summary is not None else query_summary(records)]
            path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            return analyze_hid_log(path)

    def test_overwritten_prefix_analyzes_only_retained_contiguous_suffix(self):
        records=[completion('Enter',i) for i in range(100,129)]
        records += [completion('^',129),completion('Backspace',130),completion('n',131)]
        result=self.analyze_records(records)
        self.assertEqual(len(result['possible_corrections']),1)
        pair=result['possible_corrections'][0]
        self.assertEqual((pair['original']['key'],pair['replacement']['key']),('^','n'))
        self.assertEqual(pair['original']['completion_seq'],129)
        self.assertEqual(pair['original']['features']['duration_ms'],200)
        self.assertFalse(pair['ground_truth'])
        self.assertIn('99 earlier',result['coverage']['warnings'][0])
        self.assertFalse(result['HID']['host_observation'])

    def test_caps_snapshot_and_shift_state_decode_actual_completed_keys(self):
        records=[completion('^',1,caps=True),completion('Backspace',2,caps=True),
                 completion('n',3,caps=True)]
        result=self.analyze_records(records)
        self.assertEqual(result['possible_corrections'][0]['replacement']['key'],'n')
        shift=completion('a',4,state_only=True,presses=[],shift_after=True)
        shifted=completion('A',5,shift_before=True)
        space=completion(' ',6,presses=[[2,0x2c,0,0,0,0,0]],shift_before=True)
        tokens,_=completion_tokens([shift,shifted,space])
        self.assertEqual([t['key'] for t in tokens if t['kind']=='char'],['A',' '])

    def test_modified_backspace_is_never_simple_deletion(self):
        records=[completion('o',1),completion('a',2,state_only=True,presses=[],shift_after=True),
                 completion('Backspace',3,shift_before=True,presses=[[2,0x2a,0,0,0,0,0]]),
                 completion('d',4)]
        result=self.analyze_records(records)
        self.assertEqual(result['possible_corrections'],[])
        self.assertIn('modified_backspace',[v['reason'] for v in result['invalidated']])

    def test_counter_generation_epoch_diagnostic_and_modifier_boundaries_invalidate(self):
        for field in ('usb_generation','processing_epoch','hid_failed','hid_queue_drops'):
            with self.subTest(field=field):
                records=[completion('^',1),completion('Backspace',2),completion('n',3)]
                records[1][field]+=1;records[2][field]+=1
                self.assertEqual(self.analyze_records(records)['possible_corrections'],[])
        for extra in (completion('a',2,source='diagnostic',event_seq=0,diagnostic_id=1),
                      completion('a',2,presses=[[1,4,0,0,0,0,0]]),completion('Enter',2)):
            records=[completion('^',1),extra,completion('Backspace',3),completion('n',4)]
            self.assertEqual(self.analyze_records(records)['possible_corrections'],[])

    def test_partial_mixed_malformed_and_unreported_gap_queries_are_refused(self):
        records=[completion('^',1),completion('Backspace',2),completion('n',3)]
        cases=[]
        bad=[dict(r) for r in records];bad[1]['token']='other';cases.append((bad,query_summary(records)))
        bad=[dict(r) for r in records];bad[1]['caps_lock']=1;cases.append((bad,query_summary(records)))
        cases.append(([records[0],records[2]],query_summary(records,returned=2)))
        cases.append(([records[0],records[2]],query_summary(records,returned=2,missing_during_query=1)))
        cases.append((records,query_summary(records,error='recording_active')))
        cases.append((records,query_summary(records,lost_before_query=1)))
        for rows,summary in cases:
            with self.subTest(rows=rows,summary=summary):
                with self.assertRaises(ValueError):self.analyze_records(rows,summary)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'partial.jsonl'
            path.write_text(json.dumps(records[0])+'\n')
            with self.assertRaisesRegex(ValueError,'final query summary'):analyze_hid_log(path)

    def test_same_character_and_multiple_deletions_keep_existing_conservative_policy(self):
        records=[completion(key,i) for i,key in enumerate(
            ['o','Backspace','o','a','b','Backspace','Backspace','d'],1)]
        result=self.analyze_records(records)
        self.assertEqual(result['possible_corrections'],[])
        self.assertEqual(len(result['same_character_replacements_ignored']),1)
        self.assertEqual(len(result['ambiguous_deletion_blocks']),1)

    def test_empty_query_is_valid_without_inventing_context(self):
        result=self.analyze_records([])
        self.assertEqual(result['possible_corrections'],[])
        self.assertEqual(result['gesture_events'],0)



class CompletionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)
        (self.path/'queries').mkdir()
        self.entries=[]

    def snapshot(self,records,*,status='complete',summary=None,index=None,raw=None):
        index=index or len(self.entries)+1
        relative=f'queries/{index:06}.jsonl'
        rows=[dict(r,token=f'query{index}',packet_seq=index*100+i) for i,r in enumerate(records)]
        summary=dict(summary or query_summary(records),token=f'query{index}',packet_seq=index*100+len(rows))
        entry=dict(query_index=index,path=relative,status=status)
        if status=='complete':entry.update(boot_id=summary['boot_id'],recognizer_sha256=summary['recognizer_sha256'])
        (self.path/relative).write_text(raw if raw is not None else ''.join(json.dumps(r)+'\n' for r in rows+[summary]))
        self.entries.append(entry)
        (self.path/'manifest.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in self.entries))

    def test_correction_across_adjacent_overlapping_snapshots_is_not_duplicated(self):
        records=[completion('^',1),completion('Backspace',2),completion('n',3)]
        self.snapshot(records[:2]);self.snapshot(records);self.snapshot(records)
        result=analyze_history(self.path)
        self.assertEqual(len(result['possible_corrections']),1)
        self.assertEqual(result['possible_corrections'][0]['replacement']['key'],'n')
        self.assertEqual(result['gesture_events'],3)
        self.assertEqual(result['coverage']['duplicate_completions_ignored'],5)

    def test_failed_poll_is_recovered_by_later_complete_contiguous_snapshot(self):
        records=[completion('o',1),completion('Backspace',2),completion('d',3)]
        self.snapshot(records[:1])
        self.snapshot([],status='error',raw='')
        self.snapshot(records)
        result=analyze_history(self.path)
        self.assertEqual(len(result['possible_corrections']),1)
        self.assertEqual(len(result['coverage']['excluded_queries']),1)
        self.assertTrue(result['coverage']['warnings'])

    def test_unrecovered_gap_cuts_correction_context(self):
        self.snapshot([completion('o',1)])
        self.snapshot([completion('Backspace',4),completion('d',5)])
        result=analyze_history(self.path)
        self.assertEqual(result['possible_corrections'],[])
        self.assertTrue(any('Unrecovered completion gap' in w for w in result['coverage']['warnings']))

    def test_boots_keep_manifest_order_and_cannot_share_editing_context(self):
        a=[completion('^',1,boot_id=900),completion('Backspace',2,boot_id=900)]
        b=[completion('n',1,boot_id=2)]
        self.snapshot(a,summary=query_summary(a,boot_id=900))
        self.snapshot(b,summary=query_summary(b,boot_id=2))
        result=analyze_history(self.path)
        self.assertEqual(result['coverage']['boot_order'],[900,2])
        self.assertEqual(result['possible_corrections'],[])
        self.assertEqual(result['gesture_events'],3)

    def test_conflicting_duplicate_payload_fails_even_when_query_envelopes_differ(self):
        first=completion('o',1)
        self.snapshot([first]);self.snapshot([dict(first,peak_dx=.9)])
        with self.assertRaisesRegex(ValueError,'Conflicting duplicate'):analyze_history(self.path)

    def test_source_device_state_and_query_end_failure_boundaries_are_preserved(self):
        records=[completion('^',1),completion('Backspace',2),completion('n',3)]
        self.snapshot(records[:2]);self.snapshot(records,summary=query_summary(records,recognizer_sha256='b'*64))
        self.assertEqual(analyze_history(self.path)['possible_corrections'],[])
        # A failure reported between snapshots must fence even if a later
        # completion's counter contradictorily has the older value.
        self.entries=[]
        self.snapshot(records[:2],summary=query_summary(records[:2],hid_failed=1))
        self.snapshot(records)
        self.assertEqual(analyze_history(self.path)['possible_corrections'],[])
        for field in ('processing_epoch','usb_generation','hid_failed','hid_queue_drops'):
            with self.subTest(field=field):
                self.entries=[]
                self.snapshot(records[:2])
                changed=dict(records[2]);changed[field]+=1
                self.snapshot(records[:2]+[changed])
                self.assertEqual(analyze_history(self.path)['possible_corrections'],[])

    def test_invalid_incomplete_and_unmanifested_snapshots_are_excluded_with_warnings(self):
        records=[completion('~',1),completion('Backspace',2),completion('t',3)]
        self.snapshot(records[:1])
        self.snapshot(records,status='complete',raw=json.dumps(records[0])+'\n')
        self.snapshot([],status='refused',raw='')
        self.snapshot(records)
        (self.path/'queries/unreferenced.jsonl').write_text('partial')
        with (self.path/'manifest.jsonl').open('a') as out:out.write('{"query_index":')
        result=analyze_history(self.path)
        self.assertEqual(len(result['possible_corrections']),1)
        self.assertEqual(len(result['coverage']['excluded_queries']),2)
        self.assertEqual(result['coverage']['unreferenced_snapshot_files'],['queries/unreferenced.jsonl'])
        self.assertTrue(any('Incomplete final manifest' in w for w in result['coverage']['warnings']))

    def test_time_regression_resets_context_and_snapshot_regression_is_refused(self):
        a=[completion('^',1),completion('Backspace',2)]
        self.snapshot(a)
        b=completion('n',3,timestamp_us=1500000,completed_us=1501000)
        self.snapshot([b])
        result=analyze_history(self.path)
        self.assertEqual(result['possible_corrections'],[])
        self.assertTrue(any('time regressed' in w for w in result['coverage']['warnings']))
        self.snapshot(a)
        with self.assertRaisesRegex(ValueError,'snapshot regressed'):analyze_history(self.path)


class EncoderAgreementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse the existing portable C++ harness; it has no USB/serial I/O.
        import runpy
        cls.encoder=runpy.run_path(str(Path(__file__).with_name('test_hid_action.py')))['HidActionTests']
        cls.encoder.setUpClass()

    @classmethod
    def tearDownClass(cls):
        cls.encoder.tearDownClass()

    def test_all_printable_ascii_and_controls_match_cpp_with_shift_and_caps(self):
        codes=list(range(32,127))+[8,9,10,13,27,127]
        for caps in (False,True):
            for shifted in (False,True):
                events=[];commands=[f'0 caps {int(caps)}']
                for code in codes:
                    if shifted:
                        events.append(event({'type':'special','label':'<SHIFT>'},len(events)))
                        commands.append('1 special <SHIFT>')
                    events.append(event({'type':'char','char_code':code},len(events)))
                    commands.append(f'1 char {code}')
                plans=self.encoder().run_actions(*commands)
                observed=[{'hex':bytes([p[0],0,*p[1:]]).hex()}
                          for plan in plans for p in plan['reports']]
                with self.subTest(caps=caps,shifted=shifted):
                    tokens,check=event_tokens(events,observed,caps_lock=caps)
                    self.assertTrue(check['ordered_hid_match'])
                    self.assertEqual(check['reports'],2*len(codes))
                    self.assertFalse(check['final_shift_pending'])
                    completed=[completion('a',i+1,caps=caps,
                        presses=plan['reports'][::2],state_only=not plan['reports'],
                        shift_before=bool(plan['before']),shift_after=bool(plan['after']))
                        for i,plan in enumerate(plans)]
                    decoded,_=completion_tokens(completed)
                    self.assertEqual([(t['kind'],t['key']) for t in decoded],
                                     [(t['kind'],t['key']) for t in tokens])

if __name__=='__main__':unittest.main()
