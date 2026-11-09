#!/usr/bin/env python3
"""Find possible corrections in a completed CapKey recording; never opens devices.

Character -> nearby Backspace -> different replacement is evidence of a possible
correction, not confirmed intent. No application focus, other keyboards, cursor
or selection state is captured, so this tool never creates training labels.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from capture_protocol import CaptureQuality
from replay_capture import capture_metadata, capture_phase, sample_deltas
from verify_hid_device import expected_press, PLAIN, SHIFTED

ZERO = bytes(8)
CONTROLS = {'\b':'Backspace','\n':'Enter','\r':'Enter','\t':'Tab','\x1b':'Escape','\x7f':'Delete'}
SPECIAL = {'<UP>':('ArrowUp',0x52),'<DOWN>':('ArrowDown',0x51),
           '<LEFT>':('ArrowLeft',0x50),'<RIGHT>':('ArrowRight',0x4f),
           '<HOME>':('Home',0x4a),'<END>':('End',0x4d),
           '<PAGEUP>':('PageUp',0x4b),'<PAGEDOWN>':('PageDown',0x4e),
           '<DELETE>':('Delete',0x4c),'<ENTER>':('Enter',0x28),
           '<TAB>':('Tab',0x2b),'<ESC>':('Escape',0x29),
           '<ESCAPE>':('Escape',0x29),'<BACKSPACE>':('Backspace',0x2a),
           '<SPACE>':(' ',0x2c)}
BAD_COUNTS = ('packet_gaps','packet_duplicates','packet_regressions','scan_gaps',
 'scan_duplicates','scan_regressions','timestamp_regressions','boot_changes',
 'device_dropped_scans','invalid_raw_samples','invalid_smooth_samples',
 'invalid_benchmark_samples','pad0_valid_samples','missing_required_pad_samples',
 'event_gaps','event_duplicates','event_regressions','event_timestamp_regressions',
 'telemetry_dropped_samples','telemetry_dropped_events','transport_failures',
 'telemetry_counter_regressions','dropped_counter_regressions')


def read_jsonl(path):
    data = path.read_bytes()
    if data and not data.endswith(b'\n'):
        raise ValueError(f'{path}: incomplete final line; use a completed capture')
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def shifted_character(ch):
    if ch.isascii() and ch.isalpha():
        return ch.upper()
    return SHIFTED[PLAIN.index(ch)] if ch in PLAIN else ch


def event_tokens(events, reports=None, initial_shift=False, caps_lock=False):
    """Associate reports exactly in queue order; reject missing/extra/modified keys.

    This mirrors only the existing US key/action mapping, reusing expected_press.
    A Shift-only action toggles state and consumes zero reports. Successful full
    ordered comparison supplies actual-report evidence for emitted key tokens.
    """
    pending = initial_shift
    tokens, expected = [], []
    for ordinal, event in enumerate(events, 1):
        base = dict(contact=ordinal, scan_seq=event.get('scan_seq'),
                    timestamp_us=event['timestamp_us'], boot_id=event.get('boot_id'),
                    features=event.get('features', {}))
        if event.get('event') == 'processing_reset':
            tokens.append(dict(base, kind='boundary', key='processing_reset'))
            pending = False
            continue
        action = event.get('action', {})
        kind = action.get('type')
        if kind in (None, 'none'):
            continue
        if event.get('output_backend') == 'usb_hid' and event.get('hid_queued') is not True:
            tokens.append(dict(base, kind='boundary', key='action_not_queued'))
            continue
        if kind == 'special' and action.get('label') == '<SHIFT>':
            pending = not pending
            tokens.append(dict(base, kind='shift', key='<SHIFT>', shift_pending=pending))
            continue
        if kind in ('char', 'string'):
            text = chr(action['char_code']) if kind == 'char' else action['label']
            actions = [(CONTROLS.get(ch,ch), None, ch) for ch in text]
        elif kind == 'backspace':
            actions = [('Backspace',0x2a,None)]
        elif kind == 'special' and action.get('label') in SPECIAL:
            key, usage = SPECIAL[action['label']]
            actions = [(key,usage,None)]
        else:
            raise ValueError(f'Unsupported action at scan {base["scan_seq"]}: {action}')
        for index, (key,usage,ch) in enumerate(actions):
            shifted = pending
            if usage is None:
                logical = shifted_character(ch) if pending else ch
                key = CONTROLS.get(logical,logical)
                press = (bytes([0,0,0x4c,0,0,0,0,0]) if key=='Delete' else expected_press(key, caps_lock))
                if (key in CONTROLS.values() or key==' ') and shifted:
                    press = bytes([2,*press[1:]])
            else:
                press = bytes([2 if pending else 0,0,usage,0,0,0,0,0])
            pending = False
            expected.extend([press,ZERO])
            token_kind = 'backspace' if key == 'Backspace' else 'char' if len(key)==1 else 'boundary'
            tokens.append(dict(base, kind=token_kind, key=key, character_index=index,
                               shift_applied=shifted, report_index=len(expected)-2))
    if reports is not None:
        actual = [bytes.fromhex(r['hex']) for r in reports]
        if any(len(r)!=8 or r[1]!=0 for r in actual):
            raise ValueError('hidraw contains a non-boot or malformed report')
        if actual != expected:
            mismatch = next((i for i,(a,b) in enumerate(zip(actual,expected)) if a!=b),
                            min(len(actual),len(expected)))
            raise ValueError(f'HID/action order mismatch at report {mismatch}: '
                             f'{len(actual)} observed, {len(expected)} expected; no correction inference')
    return tokens, dict(reports=len(expected), ordered_hid_match=reports is not None,
                        final_shift_pending=pending, caps_lock=caps_lock)


def infer_corrections(tokens, max_seconds=10.0, max_events=8):
    """Conservative local insertion model; deletion blocks never become pairs."""
    stack, deletion = [], []
    pairs, groups, ignored, invalidated = [], [], [], []
    last_boot = None
    def clear(reason):
        if deletion:
            invalidated.append(dict(reason=reason, deleted=deletion.copy()))
        stack.clear(); deletion.clear()
    for i, token in enumerate(tokens):
        token = dict(token, token_index=i)
        if last_boot is not None and token.get('boot_id') != last_boot:
            clear('boot_change')
        last_boot = token.get('boot_id')
        if token['kind'] == 'boundary':
            clear('navigation_or_edit_context:'+token['key'])
            continue
        if token['kind'] == 'shift':
            continue
        if token['kind'] == 'backspace':
            if token.get('shift_applied'):
                clear('modified_backspace')
                invalidated.append(dict(reason='modified_backspace',token=token))
                continue
            deleted = stack.pop() if stack else None
            deletion.append(dict(backspace=token, character=deleted))
            continue
        if token['kind'] != 'char':
            clear('unknown_token')
            continue
        if deletion:
            known = [item['character'] for item in deletion if item['character']]
            within = (len(known)==len(deletion) and all(
                0 <= token['timestamp_us']-char['timestamp_us'] <= max_seconds*1e6 and
                0 <= i-char['token_index'] <= max_events for char in known))
            if len(deletion)>1:
                groups.append(dict(kind='ambiguous_deletion_block', deleted_text=''.join(
                    x['character']['key'] if x['character'] else '?' for x in reversed(deletion)),
                    deletions=deletion.copy(), first_replacement=token,
                    within_window=within, inferred_intent=None,
                    reason='Multiple deletions: replacement alignment and intended text are unknown'))
            elif not within:
                invalidated.append(dict(reason='unknown_prior_text_or_outside_window',
                                        deleted=deletion.copy(), replacement=token))
            else:
                original=known[0]
                item=dict(original=original,backspace=deletion[0]['backspace'],replacement=token,
                          elapsed_ms=(token['timestamp_us']-original['timestamp_us'])/1000,
                          inferred_intent=token['key'],ground_truth=False,
                          evidence='possible_local_correction')
                if original['key']==token['key']:
                    ignored.append(dict(item,reason='same_character_replacement_is_not_threshold_evidence'))
                else:
                    pairs.append(item)
            deletion=[]
        stack.append(token)
    if deletion:
        invalidated.append(dict(reason='no_replacement_before_end',deleted=deletion))
    return dict(possible_corrections=pairs,ambiguous_deletion_blocks=groups,
                same_character_replacements_ignored=ignored,invalidated=invalidated)


def load_session(session):
    state=json.loads((session/'session.json').read_text())
    if state.get('running') is not False or not state.get('stopped_at'):
        raise ValueError('A completed session.json is required; live recordings are not analyzed')
    if state.get('errors'):
        raise ValueError('Capture errors must be resolved before correction inference')
    records=read_jsonl(session/'frames.jsonl')
    metadata=capture_metadata(session/'frames.jsonl')
    quality=CaptureQuality(); events=[]; onset=None; tracking=False; latest=None
    feature_by_scan={}
    for record in records:
        if capture_phase(record)=='startup':
            if quality.counts['samples']:
                raise ValueError('Startup records after active samples cannot hide a discontinuity')
            # The initial ACK intentionally excludes attach preamble continuity.
            quality.last_packet=None
            continue
        quality.observe(record)
        kind=record['type']
        if kind=='sample':
            deltas,_,reasons=sample_deltas(record)
            if reasons:raise ValueError('; '.join(reasons))
            config=metadata[record['boot_id']]['record']
            charge=config.get('acquisition',{}).get('charge_times',800)
            strength=sum(max(0,deltas[p]) for p in range(1,13))
            recognizer=config.get('recognizer',{})
            on=round(10*charge*recognizer.get('touch_threshold',1.3),3)
            off=round(10*charge*recognizer.get('release_threshold',.9),3)
            if tracking:
                if strength<off:
                    feature_by_scan[(record['boot_id'],record['scan_seq'])]=dict(
                        onset_scan_seq=onset['scan_seq'],onset_us=onset['timestamp_us'],
                        duration_ms=(record['timestamp_us']-onset['timestamp_us'])/1000)
                    tracking=False;onset=None
            elif strength>on:
                if onset is None:onset=record
                else:tracking=True
            else:onset=None
            latest=record
        elif kind=='device_event':
            if record['event']=='processing_reset':
                onset=None;tracking=False;events.append(record)
            elif record['event']=='gesture':
                if latest is None or any(record[k]!=latest[k] for k in ('boot_id','scan_seq','timestamp_us')):
                    raise ValueError('Gesture event does not follow its exact physical sample')
                event=dict(record)
                event['features']={k:record.get(k) for k in ('start_x','start_y','max_distance','grid_position','gesture_type','direction','z')}
                event['features'].update(feature_by_scan.pop((record['boot_id'],record['scan_seq']),{}))
                events.append(event)
    status=quality.status()
    problems={k:status[k] for k in BAD_COUNTS if status[k]}
    if problems:raise ValueError(f'Capture discontinuity/invalid data: {problems}')
    metas=[r for r in records if r['type']=='metadata' and r.get('boot_id') in quality.boot_ids]
    if not metas or metas[-1].get('streaming') is not False:
        raise ValueError('Completed STOP metadata is required')
    for key in ('hid_failed','hid_queue_drops'):
        if metas[-1].get(key,0)!=metas[0].get(key,0):
            raise ValueError(f'{key} changed; output context is uncertain')
    if metas[0].get('hid_queue_depth',0)!=0 or metas[-1].get('hid_queue_depth',0)!=0:
        raise ValueError('Capture boundaries must have a drained HID queue')
    if any(r.get('output_backend')=='usb_hid' and
           (r.get('hid_mounted') is not True or r.get('hid_suspended') is True) for r in metas):
        raise ValueError('HID disconnect/suspend invalidates output context; analyze a stable segment')
    return events,metas,status


def analyze(session, max_seconds=10.0, max_events=8):
    events,metas,quality=load_session(session)
    raw_path=session/'hidraw.jsonl'
    reports=read_jsonl(raw_path) if raw_path.exists() else None
    initial=metas[0].get('hid_shift_pending',False)
    attempts=[]
    for caps in (False,True):
        try:
            tokens,hid=event_tokens(events,reports,initial,caps)
            break
        except ValueError as exc:attempts.append(str(exc))
    else:raise ValueError('; '.join(attempts))
    hid['evidence_source']='ordered_actual_hidraw_reports' if reports is not None else 'saved_device_actions_only'
    if hid['final_shift_pending']!=metas[-1].get('hid_shift_pending',False):
        raise ValueError('Final one-shot Shift state disagrees with metadata')
    result=infer_corrections(tokens,max_seconds,max_events)
    result.update(schema_version=1,session=str(session.resolve()),
      input_context=json.loads((session/'input-context.json').read_text()) if (session/'input-context.json').exists() else {},
      parameters=dict(max_seconds=max_seconds,max_events=max_events),quality=quality,HID=hid,
      source_sha256={name:hashlib.sha256((session/name).read_bytes()).hexdigest()
        for name in ('frames.jsonl','session.json','hidraw.jsonl') if (session/name).exists()},
      token_count=len(tokens),gesture_events=sum(e.get('event')=='gesture' for e in events),
      limitations=['Inferred corrections are not confirmed desired outcomes or training labels.',
       'No host focus/window, selection, other keyboards or editor state was recorded; local insertion context is an explicit assumption.',
       'Navigation, Enter/Tab/Escape, modified Backspace, resets, unknown deletions and bounded time/event windows prevent automatic one-to-one inference across those boundaries.',
       'Same-character replacements are excluded as evidence of a recognition threshold error; multi-character deletion blocks remain ambiguous.',
       'HID mapping assumes one stable US-layout Caps Lock state over the capture; mismatched report order fails closed.'] )
    return result



def load_hid_log(path):
    """Require one complete query; an overwritten prefix is ordinary ring coverage."""
    from capture_protocol import _validate_hid_log
    from read_hid_log import validate_query
    records=read_jsonl(path)
    if not records or any(not isinstance(r,dict) or r.get('type')!='hid_log' for r in records):
        raise ValueError('Expected only HID completion-query records')
    for record in records:_validate_hid_log(record)
    summaries=[r for r in records if r['event']=='summary']
    if len(summaries)!=1 or records[-1] is not summaries[0]:
        raise ValueError('One final query summary is required; partial/mixed queries are refused')
    summary=summaries[0]
    if summary['error']:raise ValueError('HID log query refused: '+summary['error'])
    if any(r['token']!=summary['token'] or r['boot_id']!=summary['boot_id'] for r in records):
        raise ValueError('Query token or boot mismatch')
    validate_query(records,summary,summary['after_seq'])
    if summary['missing_during_query']:
        raise ValueError('Completion records went missing during query; retry a stable query')
    oldest,latest,retained=summary['oldest_seq'],summary['latest_seq'],summary['retained']
    if (summary['after_seq']>latest or
        (retained and retained!=latest-oldest+1) or
        (not retained and (oldest!=0 or latest!=0))):
        raise ValueError('Inconsistent retained query bounds')
    expected_lost=max(0,oldest-1-summary['after_seq']) if retained else 0
    if summary['lost_before_query']!=expected_lost:
        raise ValueError('Unaccounted overwritten query prefix')
    completions=records[:-1]
    if any(a['completed_us']>b['completed_us'] for a,b in zip(completions,completions[1:])):
        raise ValueError('Completion time regressed within a boot')
    warnings=[]
    if expected_lost:
        warnings.append(f'{expected_lost} earlier completions were overwritten; only the contiguous retained suffix is analyzed from empty context.')
    if summary['after_seq']:
        warnings.append('The query starts after a cursor; prior editing context is unknown and is not imported.')
    return completions,summary,warnings


def completion_tokens(completions, boundaries_before=None):
    """Decode committed US boot reports, with each completion's Caps Lock snapshot.

    This reads actual completed report plans, never re-runs gesture recognition.
    Successful completion promises each press had a matching zero release; these
    are device-side records, not an independent observation by the host/editor.
    """
    printable={}
    for code in range(32,127):
        ch=chr(code); report=expected_press(ch)
        printable[(report[2],bool(report[0]&0x22))]=ch
    controls={0x2a:'Backspace',0x28:'Enter',0x2b:'Tab',0x29:'Escape',0x4c:'Delete',
              0x4f:'ArrowRight',0x50:'ArrowLeft',0x51:'ArrowDown',0x52:'ArrowUp',
              0x4a:'Home',0x4d:'End',0x4b:'PageUp',0x4e:'PageDown'}
    tokens=[];previous=None;physical=0;press_count=0;boundary_counts=Counter()
    for ordinal,record in enumerate(completions,1):
        features={k:record[k] for k in ('start_x','start_y','end_x','end_y','peak_dx','peak_dy',
                    'max_distance','path_length','grid','gesture_type','direction','duration_us')}
        features['duration_ms']=record['duration_us']/1000
        base=dict(contact=ordinal,completion_seq=record['completion_seq'],
                  event_seq=record['event_seq'],processing_epoch=record['processing_epoch'],
                  scan_seq=record['scan_seq'],timestamp_us=record['timestamp_us'],
                  completed_us=record['completed_us'],boot_id=record['boot_id'],features=features)
        def boundary(reason):
            tokens.append(dict(base,kind='boundary',key=reason))
            boundary_counts[reason]+=1
        for reason in (boundaries_before or {}).get(ordinal-1,[]):boundary(reason)
        if previous is not None:
            for field in ('boot_id','usb_generation','processing_epoch','hid_failed','hid_queue_drops'):
                if record[field]!=previous[field]:boundary(field+'_change')
            if record['completion_seq']!=previous['completion_seq']+1:boundary('completion_sequence_gap')
            if record['shift_before']!=previous['shift_after']:boundary('shift_state_discontinuity')
        previous=record
        if record['source']!='physical':
            boundary('diagnostic_output')
            continue
        physical+=1
        if record['state_only']:
            if record['shift_before']==record['shift_after']:
                raise ValueError('State-only completion did not toggle one-shot Shift')
            tokens.append(dict(base,kind='shift',key='<SHIFT>',shift_pending=record['shift_after']))
            continue
        if record['shift_after']:
            raise ValueError('Completed key did not consume one-shot Shift')
        for index,press in enumerate(record['presses']):
            press_count+=1
            modifier,*usages=press
            active=[usage for usage in usages if usage]
            if modifier&~0x22 or len(active)!=1:
                boundary('modified_or_non_single_key_report')
                continue
            usage=active[0];shifted=bool(modifier&0x22)
            if 4<=usage<=29:
                key=chr(ord('a')+usage-4)
                if shifted != record['caps_lock']:key=key.upper()
            elif usage in controls:key=controls[usage]
            else:key=printable.get((usage,shifted))
            # Shift does not alter a space, but still makes Backspace modified.
            if usage==0x2c:key=' '
            if key is None:
                boundary('unsupported_key_usage')
                continue
            kind='backspace' if key=='Backspace' else 'char' if len(key)==1 else 'boundary'
            tokens.append(dict(base,kind=kind,key=key,character_index=index,
                               shift_applied=shifted,caps_lock=record['caps_lock'],
                               completed_press=press))
    return tokens,dict(physical_completions=physical,diagnostic_completions=len(completions)-physical,
                       completed_presses=press_count,context_boundaries=dict(boundary_counts))


def analyze_hid_log(path,max_seconds=10.0,max_events=8):
    completions,summary,warnings=load_hid_log(path)
    tokens,counts=completion_tokens(completions)
    if completions and any(summary[k]!=completions[-1][k] for k in ('hid_failed','hid_queue_drops')):
        warnings.append('Failure/drop counters changed after the newest retained completion; no context is inferred beyond that completion.')
        tokens.append(dict(tokens[-1] if tokens else {},kind='boundary',key='query_end_counters_changed',
                           timestamp_us=completions[-1]['completed_us'],boot_id=summary['boot_id']))
    result=infer_corrections(tokens,max_seconds,max_events)
    result.update(schema_version=1,hid_log=str(path.resolve()),
        input_context={'mode':'unprompted_typing','intended_text':None},
        parameters=dict(max_seconds=max_seconds,max_events=max_events),
        source_sha256={path.name:hashlib.sha256(path.read_bytes()).hexdigest()},
        coverage=dict(summary=summary,warnings=warnings,contiguous_retained_suffix=True,
                      starts_with_unknown_editing_context=True),
        token_count=len(tokens),gesture_events=counts['physical_completions'],
        HID=dict(counts,evidence_source='on_device_completed_HID_report_plans',
                 ordered_hid_match=None,host_observation=False,layout='US'),
        limitations=['Possible corrections are inferred intent, not confirmed outcomes or training labels.',
          'Device completion records prove successful press/release transfers; host focus, layout, editor state, other keyboards and accepted text remain unobserved.',
          'Each completion uses its recorded Caps Lock state. Diagnostic output, USB generation, processing epoch, failure/drop changes and unsupported modifiers reset editing context.',
          'The retained ring suffix starts from unknown prior text; navigation, modified Backspace, bounded windows and ambiguous deletion blocks prevent automatic pairing across uncertain context.'])
    return result



def analyze_history(directory,max_seconds=10.0,max_events=8):
    """Merge complete immutable snapshots in manifest order, never boot-ID order."""
    directory=directory.resolve()
    manifest_path=directory/'manifest.jsonl'
    manifest_data=manifest_path.read_bytes()
    warnings=[]
    if manifest_data and not manifest_data.endswith(b'\n'):
        manifest_data=manifest_data[:manifest_data.rfind(b'\n')+1]
        warnings.append('Incomplete final manifest line excluded; only fully archived queries are analyzed.')
    entries=[json.loads(line) for line in manifest_data.splitlines() if line.strip()]
    completions=[];seen={};snapshots=[];excluded=[];boundaries={};pending=[]
    sources={'manifest.jsonl':hashlib.sha256(manifest_data).hexdigest()}
    referenced=set();previous_query=None;previous_index=0;duplicates=0;boot_order=[]
    def fence(reason):
        if reason not in pending:pending.append(reason)
    def warn(message):
        warnings.append(message)
    for entry in entries:
        index=entry.get('query_index') if isinstance(entry,dict) else None
        if type(index) is not int or index<=previous_index:
            raise ValueError('History query indices must increase in manifest acquisition order')
        if index!=previous_index+1:warn(f'Manifest attempts missing before query {index}; completion continuity is checked independently.')
        previous_index=index
        status=entry.get('status')
        if status not in ('complete','incomplete','refused','error'):
            raise ValueError(f'Unknown query status at manifest index {index}')
        relative=entry.get('path')
        if not isinstance(relative,str) or not relative:
            raise ValueError(f'Query {index} needs a relative snapshot path')
        path=(directory/relative).resolve()
        if Path(relative).is_absolute() or not path.is_relative_to(directory):
            raise ValueError(f'Query {index} points outside its history directory')
        referenced.add(path)
        if status!='complete':
            excluded.append(dict(query_index=index,path=relative,status=status,reason=entry.get('error','')))
            warn(f'Query {index} excluded ({status}); later complete snapshots may recover its completion coverage.')
            continue
        try:
            records,summary,_=load_hid_log(path)
            for field in ('boot_id','recognizer_sha256','oldest_seq','latest_seq'):
                if field in entry and entry[field]!=summary[field]:
                    raise ValueError(f'Manifest {field} disagrees with the query summary')
        except (ValueError,KeyError,OSError,TypeError) as exc:
            excluded.append(dict(query_index=index,path=relative,status='invalid',reason=str(exc)))
            warn(f'Query {index} excluded (invalid complete snapshot): {exc}')
            continue
        sources[relative]=hashlib.sha256(path.read_bytes()).hexdigest()
        snapshot=dict(query_index=index,path=relative,summary=summary,new_completions=0)
        snapshots.append(snapshot)
        if previous_query is None or summary['boot_id']!=previous_query['boot_id']:
            boot_order.append(summary['boot_id'])
            if previous_query is not None:
                fence('history_boot_change')
                warn(f'Boot changed at query {index}; editing context reset in acquisition order.')
        elif summary['latest_seq']<previous_query['latest_seq']:
            raise ValueError(f'Completion snapshot regressed within boot at query {index}')
        if previous_query is not None and summary['recognizer_sha256']!=previous_query['recognizer_sha256']:
            fence('recognizer_source_change')
            warn(f'Recognizer source changed at query {index}; editing context reset.')
        previous_query=summary
        for record in records:
            identity=(record['boot_id'],record['completion_seq'])
            # These are query envelopes, not committed-event identity/content.
            stable={k:v for k,v in record.items() if k not in ('token','packet_seq')}
            if identity in seen:
                if stable!=seen[identity]:
                    raise ValueError(f'Conflicting duplicate completion {identity} at query {index}')
                duplicates+=1
                continue
            if completions:
                last=completions[-1]
                if record['boot_id']==last['boot_id']:
                    if record['completion_seq']<=last['completion_seq']:
                        raise ValueError(f'Previously unseen old completion cannot be ordered at query {index}')
                    if record['completion_seq']!=last['completion_seq']+1:
                        fence('history_unrecovered_sequence_gap')
                        warn(f'Unrecovered completion gap in boot {record["boot_id"]}: {last["completion_seq"]} to {record["completion_seq"]}; editing context reset.')
                    if record['completed_us']<last['completed_us'] or record['timestamp_us']<last['timestamp_us']:
                        fence('history_device_time_regression')
                        warn(f'Device time regressed at completion {identity}; editing context reset.')
            elif record['completion_seq']!=1:
                warn(f'History starts at completion {identity}; earlier editing context is unknown.')
            if pending:
                boundaries[len(completions)]=pending.copy()
                pending.clear()
            seen[identity]=stable
            completions.append(record)
            snapshot['new_completions']+=1
        if records and any(summary[k]!=records[-1][k] for k in ('hid_failed','hid_queue_drops')):
            fence('query_end_counters_changed')
            warn(f'Failure/drop counters changed after the newest completion in query {index}; following editing context is reset.')
    unreferenced=sorted(str(p.relative_to(directory)) for p in (directory/'queries').glob('*.jsonl')
                        if p.resolve() not in referenced)
    if unreferenced:warn(f'{len(unreferenced)} snapshot files have no complete manifest entry and were excluded.')
    if not snapshots:
        raise ValueError('No valid complete query snapshots in this history')
    tokens,counts=completion_tokens(completions,boundaries)
    last_summary=snapshots[-1]['summary']
    if completions and (pending or any(last_summary[k]!=completions[-1][k]
                                      for k in ('boot_id','hid_failed','hid_queue_drops'))):
        tokens.append(dict(kind='boundary',key='history_end_context_change',
                           boot_id=last_summary['boot_id'],timestamp_us=completions[-1]['completed_us']))
    result=infer_corrections(tokens,max_seconds,max_events)
    result.update(schema_version=1,history_dir=str(directory),
        input_context={'mode':'unprompted_typing','intended_text':None},
        parameters=dict(max_seconds=max_seconds,max_events=max_events),source_sha256=sources,
        coverage=dict(snapshots=snapshots,excluded_queries=excluded,warnings=warnings,
                      unreferenced_snapshot_files=unreferenced,boot_order=boot_order,
                      duplicate_completions_ignored=duplicates,
                      unique_completions=len(completions),starts_with_unknown_editing_context=True),
        token_count=len(tokens),gesture_events=counts['physical_completions'],
        HID=dict(counts,evidence_source='on_device_completed_HID_report_plans',
                 ordered_hid_match=None,host_observation=False,layout='US'),
        limitations=['Possible corrections are inferred intent, not confirmed outcomes or training labels.',
          'Only complete successful snapshots contribute data; overlap is deduplicated by boot and completion sequence. Failed polls may be recovered by later contiguous snapshots.',
          'Unrecovered gaps, boot/source/time changes, USB generation, processing epoch, failures/drops and diagnostic output reset editing context.',
          'Device completion logs do not observe host focus, application selection, other keyboards or accepted text. Recorded Caps Lock and US layout determine interpreted keys.'])
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    inputs=parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--session',type=Path)
    inputs.add_argument('--hid-log',type=Path,help='Completed HIDLOG JSONL query (retained suffix is sufficient)')
    inputs.add_argument('--history-dir',type=Path,help='watch_hid_log history directory with an ordered manifest')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-seconds',type=float,default=10)
    parser.add_argument('--max-events',type=int,default=8)
    args=parser.parse_args(argv)
    if not math.isfinite(args.max_seconds) or args.max_seconds<=0 or args.max_events<2:parser.error('windows must be finite and positive; --max-events >=2')
    try:
        result=(analyze(args.session,args.max_seconds,args.max_events) if args.session else
                analyze_hid_log(args.hid_log,args.max_seconds,args.max_events) if args.hid_log else
                analyze_history(args.history_dir,args.max_seconds,args.max_events))
    except (ValueError,KeyError,OSError,TypeError) as exc:parser.exit(2,f'Analysis refused: {exc}\n')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    counts=Counter((r['original']['key'],r['replacement']['key']) for r in result['possible_corrections'])
    print(f"{result['gesture_events']} gesture events; {len(result['possible_corrections'])} possible corrections; "
          f"{len(result['ambiguous_deletion_blocks'])} ambiguous deletion blocks; HID match={result['HID']['ordered_hid_match']}")
    for (old,new),count in sorted(counts.items()):print(f'{old!r} -> {new!r}: {count}')
    print(args.output)
    return 0

if __name__=='__main__':raise SystemExit(main())
