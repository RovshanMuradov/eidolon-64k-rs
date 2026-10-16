#!/usr/bin/env python3
"""Expose completed payloads from an interrupted run without hiding its failed stop."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy

import zstandard


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    encoded = (json.dumps(value, indent=2) + '\n').encode()
    if path.exists():
        assert path.read_bytes() == encoded
    else:
        path.write_bytes(encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    m = json.loads(args.manifest.read_text())
    assert m['status'] == 'failed' and m['launcher_exit'] is None and not m['reference_eligible']
    assert m['resources']['runner_log_handles_closed']
    root = Path(os.environ['EIDOLON_DATA'])
    data = root / 'reference' / m['run_id']
    for name, digest in m['evidence'].items():
        assert sha(root / name) == digest
    events = [json.loads(line) for line in (data / 'backend.jsonl').read_text().splitlines()]
    frames = [e for e in events if e['event'] == 'pre_present']
    post = [e for e in events if e['event'] == 'post_present']
    assert [e['n'] for e in frames] == [e['n'] for e in post] == list(range(len(frames)))
    index = []
    verifier = runpy.run_path('tools/verify/reference.py')
    for e in frames:
        n = e['n']
        assert e['clock_tick'] == n and e['audio_position'] == n*735
        row = dict(n=n, tick=n, clock_tick=n, audio_position=n*735, audio_position_num=n*44100,
                   audio_position_den=60, sha256=e['sha256'])
        raw = data / f'frame-{n:05d}.rgba'
        if raw.exists():
            assert sha(raw) == e['sha256']
            packed = data / f'frame-{n:05d}.raw.zst'
            if not packed.exists():
                packed.write_bytes(zstandard.ZstdCompressor(level=3).compress(raw.read_bytes()))
            verifier['verify_raw'](packed, e['width']*e['height']*4, e['sha256'])
            row['raw_zst'] = packed.name
        index.append(row)
    artifact_root = args.manifest.parent
    index_path = artifact_root / f"{m['run_id']}-frames.jsonl"
    index_text = ''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in index)
    if index_path.exists():
        assert index_path.read_text() == index_text
    else:
        index_path.write_text(index_text)
    names = ('synth_complete', 'readback_begin', 'readback_end', 'stability_check')
    pcm_events = {name: next(e for e in events if e['event'] == name) for name in names}
    evidence_path = artifact_root / f"{m['run_id']}-pcm-observations.json"
    write(evidence_path, dict(run_id=m['run_id'], reference_eligible=False, status='failed',
                             input=m['input'], dependency=m['dependency'], build_id=m['build']['build_id'],
                             run_manifest=args.manifest.name, run_manifest_sha256=sha(args.manifest),
                             backend_sha256=sha(data / 'backend.jsonl'), actual_stop=m['first_failed_check'],
                             observations=[e for e in events if e['event'] in (*names, 'synth_launch', 'synth_thread', 'wave_write')]))
    audio = dict(path='pcm.f32le', sha256=sha(data / 'pcm.f32le'), sample_format='f32le', sample_rate=44100,
                 channels=['L', 'R'], layout='interleaved', sample_frames=19964544, start_sample=0)
    complete = pcm_events['synth_complete']
    proof = dict(submitted_bytes=pcm_events['readback_begin']['bytes'], initial_tick=complete['initial_tick'],
                 final_tick=complete['final_tick'],
                 final_cursor_offset=int(complete['final_cursor'], 16)-int(pcm_events['readback_begin']['base'], 16),
                 events={k: e['seq'] for k, e in pcm_events.items()}, stable_sha256=pcm_events['stability_check']['sha256'],
                 evidence=evidence_path.name, evidence_sha256=sha(evidence_path))
    assert (data / 'pcm.f32le').stat().st_size == 159716352
    verifier['verify_pcm_completion'](proof, audio, 159716352, artifact_root, True)
    layout = frames[0]
    output = artifact_root / f"{m['run_id']}-small-capture.json"
    write(output, dict(schema='eidolon-small-real-capture-diagnostic-1', kind='compatibility-modified-diagnostic',
                       run_id=m['run_id'], reference_eligible=False, finalized=False, status='failed',
                       run_manifest=args.manifest.name, run_manifest_sha256=sha(args.manifest),
                       video=dict(width=layout['width'], height=layout['height'], row_stride=layout['width']*4,
                                  pixel_format=layout['format'], row_order=layout['row_order'],
                                  color_space='native GL_LINEAR attachment; framebuffer sRGB disabled',
                                  frame_count=len(frames), index=index_path.name, index_sha256=sha(index_path), storage='reference'),
                       audio=audio, completion=dict(finalized=False, frames_observed=len(frames), frames_hashed=len(frames),
                                                    audio_sample_frames=19964544, pcm=proof),
                       actual_stop=m['first_failed_check'], scene_boundaries_observed=False,
                       limits=['Interrupted run, native exit unknown, next frame incomplete; no scene-boundary/G1/G4/G5/reference acceptance.'],
                       package_tool=dict(path=str(Path(__file__).relative_to(Path.cwd())), sha256=sha(__file__))))
    print(json.dumps(dict(bundle=str(output), status='FAILED_DIAGNOSTIC_PAYLOADS_ONLY', frames=len(frames),
                          raw_zst=sum('raw_zst' in r for r in index), reference_accepted=False)))


if __name__ == '__main__':
    main()
