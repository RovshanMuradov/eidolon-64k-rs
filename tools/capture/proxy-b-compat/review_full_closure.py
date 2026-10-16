#!/usr/bin/env python3
"""Reconcile a closed job's original preflight, native exit and publication."""
import argparse
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import subprocess

from observations import events, sha
from package_d12 import write
from probe import quiet_prefix, tree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_id')
    args = parser.parse_args()
    assert args.run_id and all(c.isalnum() or c in '-_' for c in args.run_id)
    shared = Path(os.environ['EIDOLON_ROOT'])
    root = Path(os.environ['EIDOLON_DATA'])
    data = root / 'reference' / args.run_id
    job = root / 'reference/jobs' / args.run_id
    artifacts = Path('artifacts/reference')
    acquisition = artifacts / f'{args.run_id}-acquisition.json'
    reference = artifacts / f'{args.run_id}-reference.json'
    m = json.loads(acquisition.read_text())
    r = json.loads(reference.read_text())
    pre = json.loads((data / 'preflight.json').read_text())
    returned = json.loads((data / 'native-return.json').read_text())
    state = json.loads((job / 'state.json').read_text())
    request = json.loads((job / 'request.json').read_text())
    pid = json.loads((job / 'pid.json').read_text())
    assert state['phase'] == 'complete' and state['exit_code'] == 0
    assert state['pid'] == pid['pid'] == state['sid']
    assert not Path(f'/proc/{state["pid"]}').exists(), 'completed job PID still present; reconcile before reuse'
    for name, checksum in request['inputs'].items():
        assert sha(name) == checksum, name
    assert m['status'] == 'complete' and m['full_run'] and not m['first_failed_check']
    assert m['launcher_exit'] == returned['launcher_exit'] == 0
    assert m['supervisor_timeout'] is returned['supervisor_timeout'] is False
    for key in ('run_id', 'started_utc', 'command', 'build', 'host_runner', 'environment', 'supervision', 'dependency'):
        assert pre[key] == m[key], key
    original = json.loads((artifacts / 'proxy-b-g1-20261016.json').read_text())
    # preflight.input retains the original archive envelope; command names the
    # freshly extracted executable whose actual hash was checked before launch.
    assert pre['input'] == original['input']
    assert m['input'] == dict(pre['input'], executed_copy=pre['command'][-1])
    assert returned['run_id'] == m['run_id'] == r['run_id'] == args.run_id
    assert pre['arguments']['full'] and pre['arguments']['mode'] == '450-compatibility'
    assert pre['arguments']['storage'] == m['storage'] == r['video']['storage']
    assert pre['arguments']['reference_variant'] == m['reference_variant'] == r['source']['kind'] == 'D9-restored-native'
    assert pre['arguments']['fault'] is None
    assert pre['launcher_sha256'] == sha('tools/wine-headless') == r['source']['inputs']['launcher']
    assert pre['fresh_tree_equal'] is m['prefix_baseline']['fresh_tree_equal'] is True
    inventory = Path(m['prefix_baseline']['inventory'])
    assert pre['prefix_inventory_sha256'] == m['prefix_baseline']['inventory_sha256'] == sha(inventory)
    assert tree(Path(m['prefix_baseline']['directory'])) == json.loads(inventory.read_text())
    identity = m['executed_file_observation']
    assert identity['path'] == pre['command'][-1]
    assert pre['exe_before_sha256'] == identity['before_sha256'] == returned['exe_after_sha256'] == identity['after_sha256'] == r['source']['exe_sha256']
    assert sha(identity['path']) == r['source']['exe_sha256']
    assert sha(pre['host_runner']['path']) == pre['host_runner']['sha256'] == r['source']['inputs']['host_runner']
    for key in ('prefix_processes_released', 'private_sink_unloaded'):
        assert returned[key] is m['resources'][key] is True
    assert not returned['errors'] and not m['resources']['errors']
    with (shared / '.tools/capture/T16-gpu.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        quiet_prefix(Path('/tmp/opencode/eidolon/T16/prefix'))
        assert 'eidolon_T16_compat' not in subprocess.check_output(['pactl', 'list', 'short', 'sinks'], text=True)
    for name, checksum in m['evidence'].items():
        assert sha(root / name) == checksum, name
    for name, checksum in m['build']['outputs'].items():
        assert sha(Path(m['build']['build_directory']) / name) == checksum, name
    counts = Counter()
    observed = {}
    sequence = presents = positions = hashed = 0
    backend = data / m['ordered_stream']['path']
    assert sha(backend) == m['ordered_stream']['sha256']
    for e in events(backend):
        if 'seq' not in e:
            assert e['event'] == 'backend_probe' and e['result'] == 'distinct_backend' and e['error'] == 0
            counts['out_of_band_backend_probe'] += 1
            continue
        assert e['seq'] == sequence + 1
        sequence = e['seq']
        name = e['event']
        counts[name] += 1
        if name == 'pre_present':
            assert e['n'] == e['clock_tick'] == hashed and e['audio_position'] == hashed * 735 and e['state_equal']
            hashed += 1
        elif name == 'post_present':
            assert e['n'] == presents and e['result']
            presents += 1
        elif name == 'clock' and e['api'] == 'waveOutGetPosition':
            assert e['n'] == positions and e['value'] == positions * 735 and e['wType'] == 2
            positions += 1
        elif name in ('native_endpoint', 'native_exit_forward', 'full_run'):
            assert name not in observed
            observed[name] = e
    assert dict(counts) == m['ordered_stream']['event_counts'] and sequence == m['ordered_stream']['events']
    assert not any(counts[k] for k in ('failure', 'fault_injected', 'planned_partial_stop'))
    assert presents == hashed == r['video']['frame_count'] == 27000 and positions == 27001
    end = observed['native_endpoint']
    assert end['exit_call'] == 0x408618 and end['exit_code'] == 0 and end['sample_cursor'] == 19845000
    assert end['last_present'] == 26999 and end['frames'] == 27000 and end['queries'] == 27001
    assert end['eax'] == 0xffffffff and end['edi'] == 0 and end['seconds_f32_bits'] == 0x43e10000 and end['beat_f32_bits'] == 0x44160000
    assert not end['errors'] and end['dropped_frames'] == end['dropped_audio_sample_frames'] == 0
    assert observed['native_exit_forward']['registers_fp_equal'] and observed['native_exit_forward']['tail_jump_original_slot']
    assert observed['full_run']['wrapper_stop_enabled'] is False
    for kind in ('gpr', 'fx'):
        assert (data / f'native-exit-before-{kind}.bin').read_bytes() == (data / f'native-exit-after-{kind}.bin').read_bytes()
    terminal = [s.strip() for s in (data / 'runner.log').open(errors='replace') if s.startswith(('WINE_EXIT=', 'TIMEOUT'))]
    assert terminal == m['runner_terminal'] and len(terminal) == 1 and terminal[0].startswith('WINE_EXIT=0 ')
    result = dict(status='CLOSED_PROVENANCE_RECONCILED', run_id=args.run_id, reference_accepted=False,
                  reference=dict(path=str(reference), sha256=sha(reference)), acquisition=dict(path=str(acquisition), sha256=sha(acquisition)),
                  preflight_sha256=sha(data / 'preflight.json'), native_return_sha256=sha(data / 'native-return.json'),
                  request_sha256=sha(job / 'request.json'), final_job_state_sha256=sha(job / 'state.json'),
                  ordered_stream=m['ordered_stream'], endpoint=end, presents=presents, queries=positions,
                  runner_terminal=terminal, resources_released=True, reviewer_sha256=sha(__file__))
    output = artifacts / f'{args.run_id}-closure-review.json'
    write(output, result)
    print(json.dumps(dict(status=result['status'], review=str(output), presents=presents, queries=positions)))


if __name__ == '__main__':
    main()
