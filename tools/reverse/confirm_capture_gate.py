#!/usr/bin/env python3
"""Read-only T14 native/table/saved-observation reconciliation; never runs target/GL.

Default inputs are T11's two staged manifests. --timeline prints the independently
derived row/beat/token/frame map and retention set. --static-only needs only the
pinned Reverse dumps. Neither mode grants live-probe or reference acceptance.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked(path, digest):
    data = path.read_bytes()
    assert sha(data) == digest, str(path)
    return data


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def bits(value):
    return struct.unpack('<I', struct.pack('<f', value))[0]


def disassemble(path, start, end):
    text = subprocess.check_output([
        'objdump', '-D', '-b', 'binary', '-m', 'i386', '-Mintel',
        '--adjust-vma=0x400000', f'--start-address={start}',
        f'--stop-address={end}', str(path)], text=True)
    pattern = r'\s*([0-9a-f]+):\s+(?:[0-9a-f]{2} )+\s*(\w+)\s+(.*)'
    return [(int(m[1], 16), m[2], m[3]) for line in text.splitlines()
            if (m := re.fullmatch(pattern, line))]


def shader_arrays(path, words):
    # Native 0x4064e7..0x406dac constructs a stack pointer array, NOT a
    # contiguous slice of 0x4361f0. Fail on anything beyond these MOV forms.
    registers, stack = {}, {}
    for pc, op, operands in disassemble(path, 0x4064e7, 0x406dad):
        assert op == 'mov', (hex(pc), op)
        dst, src = operands.replace('DWORD PTR ', '').split(',')
        if src.startswith('ds:0x'):
            value = words(int(src[3:], 16), 1)[0]
        elif src in registers:
            value = registers[src]
        else:
            value = int(src, 16)
        if dst.startswith('[ebp-'):
            stack[-int(dst[5:-1], 16)] = value
        else:
            registers[dst] = value
    result = []
    for index in range(30):
        count, offset = words(0x4357e0 + 8 * index, 2)
        result.append([stack[-0x408 + 4 * (offset + j)] for j in range(count)])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifests', nargs='*', type=Path)
    parser.add_argument('--timeline', action='store_true')
    parser.add_argument('--static-only', action='store_true',
                        help='derive the native map without reading capture bundles')
    args = parser.parse_args()
    if args.static_only and args.manifests:
        parser.error('--static-only cannot reconcile supplied manifests')
    root, data = Path(os.environ['EIDOLON_ROOT']), Path(os.environ['EIDOLON_DATA'])
    provenance = json.loads(Path('reports/evidence/reverse/manifest.json').read_text())
    identity = provenance['runtime_diagnostic']['files']['postfix']
    path = data / identity['path']
    image = checked(path, identity['sha256'])
    at = lambda address, size: image[address - 0x400000:address - 0x400000 + size]
    words = lambda address, count: struct.unpack('<' + 'I' * count, at(address, count * 4))
    scalar = lambda address: struct.unpack('<f', at(address, 4))[0]
    string = lambda address: image[address - 0x400000:image.index(0, address - 0x400000)]
    # Pins accompany the reviewed instruction ranges, not a claimed emulator.
    pins = {
        0x407bf7: '0f2fc17710',  # strictly greater end beat, never >=
        0x407c0f: 'f30f5c2cc550fc4200',
        0x407c20: '0f84f1090000',
        0x4082c4: '8b38897dd4',  # pre-present -0x2c is a pass index
        0x4082d0: '83ee01',  # framebuffer selectors are one-based
        0x408617: '57ff1530904000',
        0x401041: '660f38280530b8160b',
        0x401115: '0f290510b8160b',
        0x405437: '0f298690010000',
        0x405650: '0f290510b8160b0f298e90010000',
        0x405730: '0f290510b8160b0f298e90010000',
        0x401665: '0fae542414',  # synth interior MXCSR observation follows at 0x40166a
        0x407a2b: '68f0bf170b68061400006808190000',
    }
    for address, encoding in pins.items():
        assert at(address, len(bytes.fromhex(encoding))) == bytes.fromhex(encoding), hex(address)
    rows = [struct.unpack('<ff', at(0x42fc50 + 8 * i, 8)) for i in range(50)]
    tokens = words(0x42fde0, 50)
    assert rows[0][0] == 0 and rows[-1][1] == 600
    assert all(a[1] == b[0] for a, b in zip(rows, rows[1:]))
    bpm, seconds_per_minute, sample_rate = [scalar(a) for a in (0x437040, 0x436428, 0x43642c)]
    assert (bpm, seconds_per_minute, sample_rate) == (80, 60, 44100)
    rate = f32(bpm / seconds_per_minute)

    def frame(n):
        seconds = f32(f32(float(735 * n)) / sample_rate)
        beat = f32(seconds * rate)
        row = next((i for i, (_, end) in enumerate(rows) if end > beat), -1)
        local = f32(beat - rows[row][0]) if row >= 0 else None
        return seconds, beat, row, local

    starts = []
    previous = -1
    for n in range(27001):
        row = frame(n)[2]
        if row != previous:
            starts.append(n)
            previous = row
    assert len(starts) == 51 and starts[1] == 1440 and starts[-1] == 27000
    assert frame(26999)[2] == 49 and frame(27000)[2] == -1
    ranges = [[a, b - 1] for a, b in zip(starts, starts[1:])]
    retain = sorted(set(range(0, starts[-1], 60)) | set(starts[:-1]) |
                    {n - 1 for n in starts[1:]})
    assert len(retain) == 510 and retain[0] == 0 and retain[-1] == 26999
    assert sum(b - a + 1 for a, b in ranges) == 27000

    def sample(n):
        seconds, beat, row, local = frame(n)
        return {'n': n, 'cursor_samples': 735 * n, 'seconds_f32_bits': bits(seconds),
                'beat_f32_bits': bits(beat), 'row': row,
                'local_beat_f32_bits': bits(local) if local is not None else None,
                'scene_token': tokens[row] if row >= 0 else None}

    arrays = shader_arrays(path, words)
    cloud_programs = [i for i, pointers in enumerate(arrays)
                      if any(b'#define CLOUDS\n' in string(a) for a in pointers)]
    assert cloud_programs == [20, 21]
    assert b'texture(uClouds,data.intersection' in string(0x41d710)
    consumers = []
    cloud_routes = []
    for row, token in enumerate(tokens):
        passes = words(0x435e30 + token * 4, words(0x435e2c + token * 4, 1)[0])
        routes = []
        for p in passes:
            program, framebuffer = words(0x4359d0 + p * 8, 2)
            if program in cloud_programs:
                routes.append({'pass': p, 'program_index': program,
                               'framebuffer_descriptor': framebuffer - 1})
        cloud_routes.append(routes)
        if routes:
            consumers.append(row)
    assert consumers[0] == 6 and starts[6] == 5760
    assert cloud_routes[6] == [{'pass': 20, 'program_index': 20, 'framebuffer_descriptor': 9}]
    rng_calls = [pc for pc, op, arg in disassemble(path, 0x401000, 0x408647)
                 if op == 'call' and arg == '0x401038']
    assert rng_calls == [0x4027d4, 0x402946, 0x402bac, 0x402d27, 0x402de8,
                         0x402ed8, 0x4044cb, 0x404c1e, 0x40565e, 0x4056d5]
    seed = words(0x437000, 4)
    old = provenance['runtime_diagnostic']['files']['synth_init']
    init = checked(data / old['path'], old['sha256'])
    assert seed == struct.unpack_from('<4I', init, 0x10) == (1, 0, 31337, 0)
    assert struct.unpack_from('<4I', init, 0x30) == (16007, 0, 16007, 0)
    assert struct.unpack_from('<2d', init, 0x40) == (2 ** -31,) * 2
    assert struct.unpack_from('<I', init, 0x520)[0] == 1

    manifests = args.manifests or [root / '.worktrees/T11/artifacts/reference' /
                                 f'proxy-b-d11-{name}-20261016.json'
                                 for name in ('boundary3', 'boundary-repeat')]
    if args.static_only:
        manifests = []
    summaries = []
    for manifest_path in manifests:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw)
        base = data / 'reference' / manifest['run_id']

        def evidence(name):
            p = base / name
            return checked(p, manifest['evidence'][str(p.relative_to(data))])

        events = defaultdict(list)
        wanted = {'scene_state', 'scene_pass', 'shader_source', 'shader_program',
                  'volume_upload', 'noise_atlas', 'initial_resources', 'synth_launch',
                  'synth_complete', 'bootstrap_before_synth', 'planned_partial_stop'}
        for line in evidence('backend.jsonl').splitlines():
            event = json.loads(line)
            if event['event'] in wanted:
                events[event['event']].append(event)
        # Review source bytes that define observation semantics, without running
        # or importing the capture producer's checks/reconciliation code.
        snapshot = Path(manifest['build']['build_directory']) / 'source-snapshot'
        for name in ('tools/capture/proxy-b-compat/stage.c',
                     'tools/capture/proxy-b-compat/core.c', 'tools/capture/proxy-b/core.c'):
            digest = manifest['build']['outputs']['source-snapshot/' + name]
            checked(snapshot / name, digest)
        scenes = events['scene_state']
        assert [e['n'] for e in scenes] == list(range(1443))
        for event in scenes:
            seconds, _, row, local = frame(event['n'])
            assert event['seconds_f32_bits'] == bits(seconds)
            assert event['scene_local_beat_f32_bits'] == bits(local)
            assert event['scene_token'] == tokens[row]
            assert event['delta_f32_bits'] == 18
        assert scenes[1439]['scene_local_beat_f32_bits'] == 1107284606
        assert scenes[1440]['scene_local_beat_f32_bits'] == 0
        programs = {e['creation']: e['program'] for e in events['shader_program']}
        sources = defaultdict(list)
        for event in events['shader_source']:
            address = int(event['pointer'], 16)
            source = string(address)
            assert sha(source) == event['raw_sha256']
            assert len(source) == event['raw_bytes']
            sources[event['creation']].append(address)
        assert len(programs) == 31
        assert all(sources[i + 2] == pointers for i, pointers in enumerate(arrays))
        passes = events['scene_pass']
        assert len(passes) == 1443 * 19
        for n in range(1443):
            group = passes[n * 19:(n + 1) * 19]
            assert all(e['n'] == n and e['cloud_location'] == -1 for e in group)
            # Initialization-only pass descriptors branch around state setup;
            # original glRecti still executes on the preceding current program.
            expected = [programs[1] if n == 0 else programs[20]] * 9
            expected += [programs[i] for i in range(11, 21)]
            assert [e['program'] for e in group] == expected
            for e in group[9:]:
                if e['time_location'] >= 0:
                    assert e['time_resolution_bits'][0] == bits(frame(n)[0])
        upload, = events['volume_upload']
        atlas, = events['noise_atlas']
        atlas_data = evidence('noise-atlas.rgba32f')
        assert len(atlas_data) == 128 ** 3 * 16
        assert sha(atlas_data) == upload['source_sha256'] == atlas['sha256']
        assert upload['source'] == 0xb17bff0 and upload['caller'] == '0x00407a5a'
        assert upload['dimensions'] == [128] * 3 and upload['internal_format'] == 0x8814
        assert upload['unpack'] == [4, 0, 0, 0, 0, 0, 0, 0, 0]
        assert events['initial_resources'][0]['sha256'] == sha(at(0x409100, 0x3edc0 - 0x9100))
        assert events['bootstrap_before_synth'][0]['mapping_sha256'] == sha(at(0x401000, 0x7647))
        assert events['synth_launch'][0]['initial_tick'] == 1
        complete, = events['synth_complete']
        assert complete['final_tick'] - complete['initial_tick'] == 19964544
        assert complete['final_cursor'] == '0x0a753470'
        fp = {}
        for name in ('bootstrap', 'completion'):
            context = evidence(f'{name}-context-before.bin')
            assert len(context) == 716
            fp[name] = [struct.unpack_from('<H', context, 204)[0],
                        struct.unpack_from('<I', context, 228)[0]]
            assert fp[name] == [0x27f, 0x1f80]
        assert events['planned_partial_stop'][0]['frames'] == 1443
        summaries.append({'manifest': str(manifest_path), 'sha256': sha(raw),
                          'frames_reconciled': len(scenes), 'draws_without_cloud_sampler': len(passes),
                          'atlas_source_upload_equal': True, 'fp_fcw_mxcsr': fp})
    endpoint = sample(27000)
    assert endpoint['seconds_f32_bits'] == bits(450) and endpoint['beat_f32_bits'] == bits(600)
    endpoint.update({'selection_pc': '0x407c1d', 'eax_u32': 0xffffffff,
                     'branch_pc': '0x407c20', 'branch_target': '0x408617',
                     'exit_call_pc': '0x408618', 'exit_code': 0, 'presents': False})
    result = {'status': 'TECHNICAL_CONFIRMATION_ONLY',
              'scope': 'static_only' if args.static_only else 'static_and_saved_evidence',
              'native_inputs': {'postfix': identity, 'synth_init': old}, 'runs': summaries,
              'boundary_frame': 1440, 'cloud_candidate_frame': starts[consumers[0]],
              'cloud_program_indices': cloud_programs,
              'rng_direct_call_sites': [hex(a) for a in rng_calls],
              'rng_seed': seed, 'last_rendered_frame_static': 26999,
              'endpoint_query_static': 27000, 'reference_accepted': False,
              'endpoint_static': endpoint,
              'sampling_range_count': len(ranges), 'retention_count': len(retain),
              'state_and_probe_specification': 'tools/reverse/capture-gate.md',
              'pending_live_probes': {'acquisition_owner': 'T11', 'validation_owner': 'T15',
                                      'ids': ['S1_initial_state', 'S2_node_stream',
                                              'V1_active_consumer', 'E1_natural_endpoint']},
              'limitations': ['Static candidates do not establish executed consumer draws',
                              'T11 staged bundles lack explicit runtime RNG-state snapshots',
                              'Active volume consumption and controlled endpoint remain unobserved']}
    if args.timeline:
        result['row_frame_ranges_inclusive'] = ranges
        result['sampling_ranges'] = [
            {'row': i, 'beat_range_half_open': list(rows[i]), 'scene_token': tokens[i],
             'frame_range_inclusive': bounds, 'first': sample(bounds[0]),
             'last': sample(bounds[1]), 'cloud_capable_routes_static': cloud_routes[i]}
            for i, bounds in enumerate(ranges)]
        result['retain_frames'] = retain
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
