#!/usr/bin/env python3
"""Recheck D9 bytes, runtime observations and boundaries without executing Wine."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked(path, expected):
    data = Path(path).read_bytes()
    assert digest(data) == expected, str(path)
    return data


def audit(path):
    manifest = json.loads(path.read_text())
    assert manifest['kind'] == 'proxy-B-D9-compatibility-diagnostic'
    assert not manifest['reference_eligible'] and not manifest['finalized']
    root = Path(os.environ['EIDOLON_DATA'])
    data = root / 'reference' / manifest['run_id']
    for name, expected in manifest['evidence'].items():
        checked(root / name, expected)
    build = manifest['build']
    for name, expected in build['outputs'].items():
        checked(Path(build['build_directory']) / name, expected)
    for name, expected in dict(build['original_sources'], **build['sources']).items():
        checked(Path(build['build_directory']) / 'source-snapshot' / name, expected)
    for backend in build['backends'].values():
        checked(backend['path'], backend['sha256'])
    checked(Path(manifest['stage']) / manifest['input']['exe'], manifest['input']['exe_sha256'])
    checked(Path(os.environ['EIDOLON_ROOT']) / manifest['input']['archive'], manifest['input']['archive_sha256'])
    checked(manifest['prefix_baseline']['inventory'], manifest['prefix_baseline']['inventory_sha256'])
    events = [json.loads(line) for line in (data / 'backend.jsonl').read_bytes().splitlines()]
    sequenced = [e for e in events if 'seq' in e]
    assert [e['seq'] for e in sequenced] == list(range(1, len(sequenced) + 1))
    source_events = [e for e in events if e['event'] == 'shader_source']
    assert source_events == manifest['source_provenance']
    transformed = 0
    for event in source_events:
        prefix = f"shader-{event['creation']:03d}-{event['index']:03d}"
        raw = checked(data / f'{prefix}-raw.glsl', event['raw_sha256'])
        effective = checked(data / f'{prefix}-effective.glsl', event['effective_sha256'])
        assert len(raw) == event['raw_bytes'] and len(effective) == event['effective_bytes']
        if event['transformed']:
            assert manifest['transformation'] == '450-compatibility'
            assert event['caller'] == '0x00406dce' and event['stage'] == 0x8b30 and event['count'] == 1
            assert event['raw_sha256'] == '57cdc43590d369b0744da71530cf879b6099cc6d80797809b59abd0fa5cc2182'
            assert raw.startswith(b'#version 450\n')
            assert effective == b'#version 450 compatibility\n' + raw[13:]
            transformed += 1
        else:
            assert raw == effective
    assert transformed == manifest['substitutions'] <= 1
    programs = [e for e in events if e['event'] == 'shader_program']
    logs = []
    for event in programs:
        log = checked(data / f"shader-{event['creation']:03d}-program-{event['program']}-link.log", event['log_sha256'])
        assert len(log) == event['log_bytes']
        if log:
            logs.append(dict(creation=event['creation'], program=event['program'], text=log.decode()))
    summaries = dict(manifest=str(path), manifest_sha256=digest(path.read_bytes()),
                     status=manifest['status'], first_failed_check=manifest['first_failed_check'],
                     substitutions=transformed, shader_sources=len(source_events), programs=len(programs),
                     failed_links=[e['program'] for e in programs if not e['link_status']], compiler_logs=logs,
                     target_program_uses=[e for e in events if e['event'] == 'program_use' and e['program'] == 2],
                     context=[e for e in events if e['event'] == 'compat_context'],
                     reference_accepted=False)
    atlases = [e for e in events if e['event'] == 'noise_atlas']
    if atlases:
        assert len(atlases) == 1
        event = atlases[0]
        raw = checked(data / 'noise-atlas.rgba32f', event['sha256'])
        assert len(raw) == event['bytes'] == 16384 * 128 * 16
        pixels = np.frombuffer(raw, dtype='<f4').reshape(-1, 4)
        summaries['atlas'] = dict(sha256=event['sha256'], finite=bool(np.isfinite(pixels).all()),
                                 alpha_zero=bool((pixels[:, 3] == 0).all()),
                                 rgb_min=float(pixels[:, :3].min()), rgb_max=float(pixels[:, :3].max()),
                                 unique_rgb=len(np.unique(pixels[:, :3], axis=0)))
    frames = [e for e in events if e['event'] == 'pre_present']
    post = [e for e in events if e['event'] == 'post_present']
    for n, event in enumerate(frames):
        assert event['n'] == event['clock_tick'] == n and event['audio_position'] == n * 735
        path = data / f'frame-{n:05d}.rgba'
        if path.exists():
            raw = checked(path, event['sha256'])
            assert len(raw) == event['width'] * event['height'] * 4
        else:
            assert any(e['event'] == 'boundary_probe' for e in events)
            assert n >= 3 and n % 60 and n not in (1439, 1440)
    assert [e['n'] for e in post] == list(range(len(post)))
    summaries['pre_present_frames'] = len(frames)
    summaries['successful_presents'] = len(post)
    pcm_events = {e['event']: e for e in events if e['event'] in ('synth_complete', 'readback_begin', 'readback_end', 'stability_check')}
    if 'stability_check' in pcm_events:
        assert list(pcm_events) == ['synth_complete', 'readback_begin', 'readback_end', 'stability_check']
        complete, begin, end, stable = pcm_events.values()
        raw = checked(data / 'pcm.f32le', end['sha256'])
        assert len(raw) == begin['bytes'] == stable['bytes'] == 159716352
        assert end['sha256'] == stable['sha256']
        assert complete['final_tick'] - complete['initial_tick'] == 19964544
        assert int(complete['final_cursor'], 16) - int(begin['base'], 16) == len(raw)
        assert complete['seq'] < begin['seq'] < end['seq'] < stable['seq']
        summaries['pcm'] = dict(bytes=len(raw), sha256=end['sha256'], source_memory_stability_observed=True)
    print(json.dumps(summaries, indent=2))
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifests', nargs='+', type=Path)
    args = parser.parse_args()
    summaries = [audit(path) for path in args.manifests]
    if len(summaries) == 2 and all('atlas' in s and 'pcm' in s for s in summaries):
        manifests = [json.loads(path.read_text()) for path in args.manifests]
        assert manifests[0]['run_id'] != manifests[1]['run_id']
        assert manifests[0]['prefix_baseline'] == manifests[1]['prefix_baseline']
        for name in ('opengl32.dll', 'winmm.dll'):
            assert manifests[0]['build']['outputs'][name] == manifests[1]['build']['outputs'][name], name
        directories = [Path(os.environ['EIDOLON_DATA']) / 'reference' / m['run_id'] for m in manifests]
        observations = [[json.loads(line) for line in (d / 'backend.jsonl').read_bytes().splitlines()] for d in directories]
        frames = [[e for e in events if e['event'] == 'pre_present'] for events in observations]
        assert len(frames[0]) == len(frames[1])
        files = ['noise-atlas.rgba32f', 'pcm.f32le']
        for a, b in zip(*frames):
            assert {k: v for k, v in a.items() if k not in ('seq', 'pid', 'tid')} == {k: v for k, v in b.items() if k not in ('seq', 'pid', 'tid')}
            name = f"frame-{a['n']:05d}.rgba"
            if (directories[0] / name).exists() and (directories[1] / name).exists():
                files.append(name)
        for name in files:
            with (directories[0] / name).open('rb') as left, (directories[1] / name).open('rb') as right:
                while True:
                    a, b = left.read(1048576), right.read(1048576)
                    assert a == b, name
                    if not a:
                        break
        print(json.dumps(dict(pair_atlas_equal=True, pair_pcm_equal=True,
                              frame_records_equal=len(frames[0]), complete_files_compared_bytewise=len(files),
                              same_shim_and_prefix_baseline=True, reference_accepted=False)))


if __name__ == '__main__':
    main()
