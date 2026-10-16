#!/usr/bin/env python3
"""Publish lossless partial-capture/eligibility sidecars, never a full reference."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil

import zstandard


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    encoded = (json.dumps(value, indent=2) + '\n').encode()
    if path.exists():
        assert path.read_bytes() == encoded, path
    else:
        path.write_bytes(encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    m = json.loads(args.manifest.read_text())
    assert m['status'] == 'partial' and m['launcher_exit'] == 0 and not m['reference_eligible']
    roots = dict(checkout=Path.cwd(), shared=Path(os.environ['EIDOLON_ROOT']), data=Path(os.environ['EIDOLON_DATA']))
    data = roots['data'] / 'reference' / m['run_id']
    for name, digest in m['evidence'].items():
        assert sha(roots['data'] / name) == digest, name
    events = [json.loads(line) for line in (data / 'backend.jsonl').read_text().splitlines()]
    get = lambda name: [e for e in events if e['event'] == name]
    stop, = get('planned_partial_stop')
    frames = get('pre_present')
    assert len(frames) == stop['frames'] == len(get('post_present'))
    assert [e['n'] for e in frames] == list(range(len(frames)))

    def binding(path, root):
        path = Path(path).absolute()
        return dict(root=root, path=str(path.relative_to(roots[root])), sha256=sha(path))

    def one(name):
        event, = get(name)
        return event

    pcm_names = ('synth_complete', 'readback_begin', 'readback_end', 'stability_check')
    pcm_events = {name: one(name) for name in pcm_names}
    audio = dict(path='pcm.f32le', sha256=sha(data / 'pcm.f32le'), sample_format='f32le',
                 sample_rate=44100, channels=['L', 'R'], layout='interleaved',
                 sample_frames=19964544, start_sample=0)
    assert (data / 'pcm.f32le').stat().st_size == 159716352
    assert audio['sha256'] == pcm_events['readback_end']['sha256'] == pcm_events['stability_check']['sha256']
    artifact_root = args.manifest.parent
    envelope_path = artifact_root / f"{m['run_id']}-pcm-observations.json"
    envelope = dict(kind='compatibility-modified-diagnostic-pcm-evidence', run_id=m['run_id'],
                    reference_eligible=False, run_manifest=binding(args.manifest, 'checkout'),
                    input=m['input'], dependency=m['dependency'], build_id=m['build']['build_id'],
                    backend=binding(data / 'backend.jsonl', 'data'),
                    observations=[e for e in events if e['event'] in (*pcm_names, 'synth_launch', 'synth_thread',
                                  'bootstrap_before_synth', 'wave_open', 'wave_prepare', 'wave_write', 'epoch',
                                  'failure', 'planned_partial_stop')])
    write(envelope_path, envelope)
    complete = pcm_events['synth_complete']
    pcm = dict(submitted_bytes=pcm_events['readback_begin']['bytes'], initial_tick=complete['initial_tick'],
               final_tick=complete['final_tick'],
               final_cursor_offset=int(complete['final_cursor'], 16) - int(pcm_events['readback_begin']['base'], 16),
               events={name: e['seq'] for name, e in pcm_events.items()},
               stable_sha256=pcm_events['stability_check']['sha256'],
               evidence=envelope_path.name, evidence_sha256=sha(envelope_path))
    checker = runpy.run_path('tools/verify/reference.py')
    checker['verify_pcm_completion'](pcm, audio, 159716352, artifact_root, True)
    index = []
    compressor = zstandard.ZstdCompressor(level=3)
    for e in frames:
        n = e['n']
        assert e['clock_tick'] == n and e['audio_position'] == n * 735
        row = dict(n=n, tick=n, clock_tick=n, audio_position=n*735,
                   audio_position_num=n*44100, audio_position_den=60, sha256=e['sha256'])
        raw = data / f'frame-{n:05d}.rgba'
        if raw.exists():
            assert sha(raw) == e['sha256']
            packed = data / f'frame-{n:05d}.raw.zst'
            if not packed.exists():
                packed.write_bytes(compressor.compress(raw.read_bytes()))
            checker['verify_raw'](packed, e['width']*e['height']*4, e['sha256'])
            row['raw_zst'] = packed.name
        index.append(row)
    index_path = artifact_root / f"{m['run_id']}-frames.jsonl"
    encoded = ''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in index)
    if index_path.exists():
        assert index_path.read_text() == encoded
    else:
        index_path.write_text(encoded)
    layout = frames[0]
    bundle = dict(schema='eidolon-small-real-capture-diagnostic-1', kind='compatibility-modified-diagnostic',
                  run_id=m['run_id'], reference_eligible=False, finalized=False,
                  run_manifest=binding(args.manifest, 'checkout'),
                  video=dict(width=layout['width'], height=layout['height'], row_stride=layout['width']*4,
                             pixel_format=layout['format'], row_order=layout['row_order'],
                             color_space=f"native attachment encoding GL_{layout['encoding']:04x}; sRGB enable {layout['sRGB_enabled']}",
                             frame_count=len(frames), index=index_path.name, index_sha256=sha(index_path), storage='reference'),
                  audio=audio, completion=dict(finalized=False, frames_observed=len(frames), frames_hashed=len(frames),
                                               audio_sample_frames=audio['sample_frames'], pcm=pcm),
                  actual_stop=stop, scene_boundaries_observed=False,
                  limits=['Partial acquisition only; full G1 ABI/canary gates, scene identity, controlled full endpoint and restoration acceptance remain open.'],
                  package_tool=binding(Path(__file__), 'checkout'))
    bundle_path = artifact_root / f"{m['run_id']}-small-capture.json"
    write(bundle_path, bundle)

    # The independent T10 ledger reports complete ordered arrays. Call PCs are
    # checked against the pinned original FF D0 instructions, not fabricated.
    image_path = roots['data'] / 'reverse/confirmed-debug/postfix-00400000.bin'
    assert sha(image_path) == 'da9cc65b64aa7d322807d93cb4361bc864a10f00ed47246f5df96fb5b9ecf504'
    image = image_path.read_bytes()
    calls = []
    for program in get('shader_program'):
        creation = program['creation']
        sources = [e for e in get('shader_source') if e['creation'] == creation]
        assert [e['index'] for e in sources] == list(range(len(sources)))
        ret = int(sources[0]['caller'], 16)
        assert image[ret-0x400002:ret-0x400000] == b'\xff\xd0'
        # Exactly one forward is established by the pinned wrapper's single
        # native call per invocation; older runs have no separate call counter.
        calls.append(dict(sequence=creation, stage=sources[0]['stage'], count=len(sources),
                          caller=f'0x{ret-2:08x}', **{'return': f'0x{ret:08x}'},
                          source_addresses=[f"0x{int(e['pointer'], 16):08x}" for e in sources],
                          input=[binding(data / f"shader-{creation:03d}-{e['index']:03d}-raw.glsl", 'data') for e in sources],
                          forwarded=[binding(data / f"shader-{creation:03d}-{e['index']:03d}-effective.glsl", 'data') for e in sources],
                          forward_calls=1, program=program['program']))
    exe = data / 'native-input.exe'
    if not exe.exists():
        shutil.copyfile(Path(m['stage']) / m['input']['exe'], exe)
    assert sha(exe) == m['input']['exe_sha256']
    build = m['build']
    directory = Path(build['build_directory'])
    inputs = {name: binding(directory / 'source-snapshot' / name, 'shared')
              for name in dict(build['original_sources'], **build['sources'])}
    for name in build['outputs']:
        if not name.startswith('source-snapshot/') and not name.endswith(('.dll', '.exe')):
            inputs[name] = binding(directory / name, 'shared')
    sidecar = dict(schema='eidolon-d9-eligibility-1', kind='compatibility-modified-diagnostic', decision='D9',
                   run_id=m['run_id'], reference_eligible=False, run_manifest=binding(args.manifest, 'checkout'),
                   inputs=dict(exe=binding(exe, 'data'), archive=binding(roots['shared'] / m['input']['archive'], 'shared'),
                               bank=binding(roots['data'] / 'reference/dependencies/gm.dls', 'data'),
                               launcher=binding(roots['checkout'] / 'tools/wine-headless', 'checkout')),
                   build=dict(inputs=inputs, outputs={name: binding(directory / name, 'shared') for name in
                                                      build['outputs'] if name.endswith(('.dll', '.exe'))},
                              compiler=build['compiler'], commands=build['commands']),
                   transformation=m['transformation'], calls=calls, fallback=None)
    sidecar_path = artifact_root / f"{m['run_id']}-eligibility.json"
    write(sidecar_path, sidecar)
    print(json.dumps(dict(status='DIAGNOSTIC_ONLY', bundle=str(bundle_path), sidecar=str(sidecar_path),
                          frames=len(frames), raw_zst=sum('raw_zst' in row for row in index),
                          pcm_bytes=159716352, reference_accepted=False)))


if __name__ == '__main__':
    main()
