#!/usr/bin/env python3
"""Audit durable full-run bytes without synthesizing missing acquisition provenance."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path

from observations import events, sha
from package_d12 import write
from timeline import retention


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_id')
    args = parser.parse_args()
    assert args.run_id and all(c.isalnum() or c in '-_' for c in args.run_id)
    shared = Path(os.environ['EIDOLON_ROOT'])
    data = Path(os.environ['EIDOLON_DATA']) / 'reference' / args.run_id
    stage = Path('/tmp/opencode/eidolon/T16') / args.run_id
    counts = Counter()
    selected = []
    frames = []
    positions = []
    presents = []
    last = 0
    for e in events(data / 'backend.jsonl'):
        if 'seq' not in e:
            assert e['event'] == 'backend_probe' and e['result'] == 'distinct_backend' and e['error'] == 0
            counts['out_of_band_backend_probe'] += 1
            continue
        assert e['seq'] == last + 1
        last = e['seq']
        counts[e['event']] += 1
        if e['event'] == 'pre_present':
            assert e['n'] == len(frames) and e['clock_tick'] == e['n']
            assert e['audio_position'] == 735 * e['n'] and e['state_equal']
            frames.append(e)
        elif e['event'] == 'post_present':
            assert e['n'] == len(presents) and e['result']
            presents.append(e['n'])
        elif e['event'] == 'clock' and e['api'] == 'waveOutGetPosition':
            assert e['n'] == len(positions) and e['value'] == 735 * e['n'] and e['wType'] == 2
            positions.append(e['n'])
        elif e['event'] in ('native_endpoint', 'native_exit_forward', 'full_run', 'loaded_module_bytes',
                            'synth_complete', 'readback_begin', 'readback_end', 'stability_check', 'throughput'):
            selected.append(e)
    def one(name):
        item, = [e for e in selected if e['event'] == name]
        return item
    assert len(frames) == len(presents) == 27000 and len(positions) == 27001
    assert not any(counts[k] for k in ('failure', 'fault_injected', 'planned_partial_stop'))
    endpoint = one('native_endpoint')
    assert endpoint['frames'] == 27000 and endpoint['queries'] == 27001
    assert endpoint['last_present'] == 26999 and endpoint['sample_cursor'] == 19845000
    assert endpoint['exit_call'] == 0x408618 and endpoint['caller'] == 0x40861e
    assert endpoint['exit_code'] == 0 and endpoint['eax'] == 0xffffffff and endpoint['edi'] == 0
    assert endpoint['seconds_f32_bits'] == 0x43e10000 and endpoint['beat_f32_bits'] == 0x44160000
    assert not endpoint['errors'] and endpoint['dropped_frames'] == endpoint['dropped_audio_sample_frames'] == 0
    assert one('native_exit_forward')['registers_fp_equal'] and one('native_exit_forward')['tail_jump_original_slot']
    assert one('full_run')['wrapper_stop_enabled'] is False
    for kind in ('gpr', 'fx'):
        assert (data / f'native-exit-before-{kind}.bin').read_bytes() == (data / f'native-exit-after-{kind}.bin').read_bytes()
    terminal = [line.strip() for line in (data / 'runner.log').open(errors='replace') if line.startswith(('WINE_EXIT=', 'TIMEOUT'))]
    assert len(terminal) == 1 and terminal[0].startswith('WINE_EXIT=0 ')
    _, retained = retention(27000, full=True)
    assert [int(n) for n in (data / 'retention.txt').read_text().split()] == retained
    assert sorted(int(p.stem.split('-')[1]) for p in data.glob('frame-*.rgba')) == retained
    for n in retained:
        raw = data / f'frame-{n:05d}.rgba'
        assert raw.stat().st_size == 8294400 and sha(raw) == frames[n]['sha256']
    pcm = data / 'pcm.f32le'
    assert pcm.stat().st_size == 159716352
    assert sha(pcm) == one('readback_end')['sha256'] == one('stability_check')['sha256']
    complete, begin = one('synth_complete'), one('readback_begin')
    assert complete['initial_tick'] == 1 and complete['final_tick'] == 19964545
    assert int(complete['final_cursor'], 16) - int(begin['base'], 16) == begin['bytes'] == 159716352
    assert complete['seq'] < begin['seq'] < one('readback_end')['seq'] < one('stability_check')['seq']
    shims = {name: sha(stage / name) for name in ('opengl32.dll', 'winmm.dll')}
    matches = [json.loads(p.read_text()) for p in (shared / '.tools/capture/B-compat').glob('*/build.json')]
    build, = [b for b in matches if all(b['outputs'][name] == checksum for name, checksum in shims.items())]
    for name, checksum in build['outputs'].items():
        assert sha(Path(build['build_directory']) / name) == checksum
    loaded = {e['role']: e['file_sha256'] for e in selected if e['event'] == 'loaded_module_bytes'}
    assert all(loaded[name.removesuffix('.dll') + '-shim'] == checksum for name, checksum in shims.items())
    acquisition = Path('artifacts/reference') / f'{args.run_id}-acquisition.json'
    assert not acquisition.exists() and not (data / 'preflight.json').exists()
    result = dict(run_id=args.run_id, status='PRESERVED_NATIVE_COMPLETE_PROVENANCE_INCOMPLETE',
                  reference_eligible=False, recovery_allowed=False, build=build,
                  missing=['original durable prelaunch environment and fresh-prefix verification record',
                           'original executed-EXE before/after observation envelope',
                           'original acquisition manifest; host-runner binding is not recorded per run'],
                  decision='D15: preserve all bytes; acquire a fresh reference and two hash/full-PCM repeats',
                  runner_terminal=terminal, ordered_events=last, event_counts=dict(counts), observations=selected,
                  verified_frames=len(frames), verified_raws=len(retained), pcm_bytes=pcm.stat().st_size,
                  evidence={p.name: dict(bytes=p.stat().st_size, sha256=sha(p)) for p in sorted(data.iterdir()) if p.is_file()},
                  reviewer_sha256=sha(__file__))
    destination = Path('artifacts/reference') / f'{args.run_id}-recovery-review.json'
    write(destination, result)
    print(json.dumps(dict(status=result['status'], review=str(destination), frames=len(frames), raws=len(retained))))


if __name__ == '__main__':
    main()
