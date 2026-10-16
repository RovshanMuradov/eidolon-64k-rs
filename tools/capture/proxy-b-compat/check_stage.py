#!/usr/bin/env python3
"""Producer consistency check; DIAGNOSTIC_ONLY, never substitutes for T13 review."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(path):
    m = json.loads(path.read_text())
    data = Path(os.environ['EIDOLON_DATA']) / 'reference' / m['run_id']
    assert m['status'] == 'partial' and m['launcher_exit'] == 0
    assert not m['reference_eligible'] and not m['finalized'] and not m['supervisor_timeout']
    assert any('WINE_EXIT=0 ' in line for line in m['runner_terminal'])
    for name, digest in m['evidence'].items():
        assert sha(Path(os.environ['EIDOLON_DATA']) / name) == digest, name
    build = Path(m['build']['build_directory'])
    for name, digest in m['build']['outputs'].items():
        assert sha(build / name) == digest, name
    assert sha(m['prefix_baseline']['inventory']) == m['prefix_baseline']['inventory_sha256']
    if 'host_runner' in m:
        assert sha(m['host_runner']['path']) == m['host_runner']['sha256']
    assert m['environment']['settings']['WINEPREFIX'] == '/tmp/opencode/eidolon/T11/prefix'
    assert m['environment']['settings']['WINEARCH'] == 'win64'
    assert m['resources']['prefix_processes_released'] and m['resources']['private_sink_unloaded']
    events = [json.loads(line) for line in (data / 'backend.jsonl').read_text().splitlines()]
    get = lambda name: [e for e in events if e['event'] == name]
    sequences = [e['seq'] for e in events if 'seq' in e]
    assert sequences == list(range(1,len(sequences)+1))
    assert not get('failure') and not get('fault_injected')
    stop, = get('planned_partial_stop')
    n = stop['frames']
    frames = get('pre_present')
    assert len(frames) == n
    for name in ('pre_present','post_present','frame_state','scene_state','clock_routes_checked'):
        assert [e['n'] for e in get(name)] == list(range(n)), name
    for frame,state in zip(frames,get('frame_state')):
        assert frame['n'] == frame['clock_tick'] and frame['audio_position'] == frame['n']*735
        assert state['before'] == state['after']
        for key in ('before','after'):
            digest = hashlib.sha256(struct.pack('<18i',*state[key])).hexdigest()
            assert frame[key+'_state_sha256'] == digest
        assert state['before'][0:2] == [0,0]
        assert state['before'][12:17] == [8,8,8,8,0]
        assert frame['component'] == 0x8c17
        raw = data / f"frame-{frame['n']:05d}.rgba"
        required = frame['n'] < 3 or frame['n'] % 60 == 0 or frame['n'] >= 1438
        assert raw.exists() == required
        if required:
            assert raw.stat().st_size == 8294400 and sha(raw) == frame['sha256']
    for clock in get('clock_routes_checked'):
        assert clock['sample_cursor'] == clock['n']*735 and clock['repeats'] == 2
        assert clock['milliseconds'] == clock['epoch_ms']+clock['n']*1000//60
        assert clock['qpc'] == clock['epoch_ms']*60000+clock['n']*1000000
        assert clock['qpf'] == 60000000
    counters = {e['api']: e['returned_calls'] for e in get('abi_summary')}
    for api in (1,2,3):
        assert counters[api] == 2*n
    assert counters[4] == n and counters[12] == 31 and counters[15] == counters[16] == 1
    assert counters[13] == len(get('program_use'))
    for e in get('abi_canary'):
        prefix = f"abi-{e['api']:02d}-{e['ordinal']}"
        before = struct.unpack('<9I',(data / f'{prefix}-before-gpr.bin').read_bytes())
        after = struct.unpack('<9I',(data / f'{prefix}-after-gpr.bin').read_bytes())
        assert all(a == b for i,(a,b) in enumerate(zip(before,after)) if i not in (3,7))
        assert before[3]+4 == e['entry_esp'] and after[3]+8 == e['return_esp']
        assert e['return_esp'] == e['entry_esp']+4+e['argbytes']
        assert after[7] == e['observed_eax'] == e['expected_eax'] and e['equal']
        a,b = [data / f'{prefix}-{side}-fx.bin' for side in ('before','after')]
        assert a.read_bytes() == b.read_bytes() and a.stat().st_size == 512
        assert sha(a) == e['before_fx_sha256'] and sha(b) == e['after_fx_sha256']
    assert (data/'bootstrap-context-before.bin').read_bytes() == (data/'bootstrap-context-after.bin').read_bytes()
    before,after = [(data/f'completion-context-{side}.bin').read_bytes() for side in ('before','after')]
    assert len(before) == len(after) == 716
    assert before[:184] == after[:184] and before[188:] == after[188:]
    assert struct.unpack_from('<I',after,184)[0] == 0x401765
    loaded = {e['role']:e for e in get('loaded_module_bytes')}
    for name in ('opengl32','winmm'):
        assert loaded[name+'-shim']['file_sha256'] == m['build']['outputs'][name+'.dll']
        assert loaded[name+'-backend']['file_sha256'] == m['build']['backends'][name]['sha256']
    atlas, = get('noise_atlas'); volume, = get('volume_upload')
    assert sha(data/'noise-atlas.rgba32f') == atlas['sha256'] == volume['source_sha256']
    assert volume['dimensions'] == [128,128,128] and volume['internal_format'] == 0x8814
    assert volume['unpack'][1:] == [0]*8
    passes = get('scene_pass')
    assert set(e['n'] for e in passes) == set(range(n))
    clouds = [e for e in passes if e['cloud_location'] >= 0]
    assert all(e['cloud_texture'] == volume['texture'] for e in clouds)
    for e in get('shader_program'):
        assert e['link_status'] == 1 and e['api_error'] == 0 and e['forward_calls'] == 1
    assert len(get('shader_program')) == 31
    pcm = data/'pcm.f32le'
    assert pcm.stat().st_size == 159716352
    stable, = get('stability_check')
    assert sha(pcm) == stable['sha256']
    completion, = get('synth_complete')
    assert completion['final_tick']-completion['initial_tick'] == 19964544
    scenes = get('scene_state')
    changes = [e for i,e in enumerate(scenes) if not i or e['scene_token'] != scenes[i-1]['scene_token']]
    throughput, = get('throughput')
    summary = dict(run_id=m['run_id'],frames=n,abi_returned_calls=sum(counters.values()),
                   unobserved_wrapper_ids=[key for key,value in counters.items() if key < 17 and not value],
                   cloud_draws=len(clouds),scene_changes=changes,
                   seconds_per_frame=throughput['wall_ticks']/throughput['frequency']/n,
                   reference_accepted=False)
    print(json.dumps(summary))
    return m,events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifests',nargs='+',type=Path)
    args = parser.parse_args()
    results = [inspect(path) for path in args.manifests]
    if len(results) == 2:
        (a,ae),(b,be) = results
        assert a['run_id'] != b['run_id']
        assert a['prefix_baseline'] == b['prefix_baseline']
        assert {k:v for k,v in a['input'].items() if k!='executed_copy'} == {k:v for k,v in b['input'].items() if k!='executed_copy'}
        assert a['dependency'] == b['dependency']
        for key in ('os','wine','packages','gpu','display'):
            assert a['environment'][key] == b['environment'][key], key
        assert all(a['build']['outputs'][name] == b['build']['outputs'][name] for name in ('opengl32.dll','winmm.dll'))
        for event in ('initial_resources','epoch','frame_state','scene_state','scene_pass','clock_routes_checked'):
            left,right = [[{k:v for k,v in e.items() if k not in ('pid','tid','seq','hdc','hglrc')} for e in es if e['event']==event]
                          for es in (ae,be)]
            assert left == right,event
        af,bf = [[e for e in es if e['event']=='pre_present'] for es in (ae,be)]
        assert [(e['n'],e['sha256']) for e in af] == [(e['n'],e['sha256']) for e in bf]
        directories = [Path(os.environ['EIDOLON_DATA'])/'reference'/m['run_id'] for m in (a,b)]
        names = ['pcm.f32le','noise-atlas.rgba32f']+[p.name for p in directories[0].glob('frame-*.rgba')]
        initial = [(d/'bootstrap-context-before.bin').read_bytes() for d in directories]
        # Win32 x86 CONTEXT.ExtendedRegisters starts at 204; FXSAVE control
        # word/status/tag and MXCSR are actual initial observations, not defaults.
        assert initial[0][204:210] == initial[1][204:210]
        assert initial[0][228:232] == initial[1][228:232]
        for name in names:
            with (directories[0]/name).open('rb') as left,(directories[1]/name).open('rb') as right:
                while True:
                    x,y = left.read(1048576),right.read(1048576)
                    assert x == y,name
                    if not x: break
        print(json.dumps(dict(status='DIAGNOSTIC_ONLY',all_frame_hashes_equal=len(af),
                              bytewise_equal_files=len(names),reference_accepted=False)))


if __name__ == '__main__':
    main()
