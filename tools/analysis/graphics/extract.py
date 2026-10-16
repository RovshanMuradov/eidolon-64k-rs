#!/usr/bin/env python3
"""Recover byte-exact shader fragments and engine tables from the pinned T1 dump.

No target execution or GL calls. Outputs live in EIDOLON_DATA/analysis/graphics.
Use --write-manifest for the first extraction; otherwise verify the committed
manifest as well as every generated asset. Pointer/curve offsets remain native.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    'capture_gate', ROOT / 'tools/reverse/confirm_capture_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(obj):
    return (json.dumps(obj, indent=2, allow_nan=False) + '\n').encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-manifest', action='store_true')
    args = parser.parse_args()
    data = Path(os.environ['EIDOLON_DATA'])
    out = data / 'analysis/graphics'
    provenance = json.loads((ROOT / 'reports/evidence/reverse/manifest.json').read_text())
    source = provenance['runtime_diagnostic']['files']['postfix']
    path = data / source['path']
    image = path.read_bytes()
    assert digest(image) == source['sha256'] and len(image) == source['bytes']

    def at(address, size):
        offset = address - 0x400000
        assert offset >= 0 and offset + size <= len(image)
        return image[offset:offset + size]

    def words(address, count):
        return struct.unpack('<' + 'I' * count, at(address, 4 * count))

    def floats(address, count):
        return struct.unpack('<' + 'f' * count, at(address, 4 * count))

    def string(address):
        start = address - 0x400000
        assert 0 <= start < len(image)
        return image[start:image.index(0, start)]

    def name(index):
        return string(words(0x4361f0 + 4 * index, 1)[0]).decode('ascii')

    outputs = {}

    def asset(relative, content):
        outputs[relative] = content
        return {'path': relative, 'bytes': len(content), 'sha256': digest(content)}

    arrays = gate.shader_arrays(path, words)
    loader_pointer, = words(0x440c58, 1)
    addresses = sorted({loader_pointer} | {a for pointers in arrays for a in pointers})
    chunks = [dict(address=hex(a), **asset(f'shaders/{a:08x}.glsl', string(a)))
              for a in addresses]
    programs = [{'index': i, 'source_addresses': [hex(a) for a in pointers],
                 'concatenated_bytes': sum(len(string(a)) for a in pointers),
                 'concatenated_sha256': digest(b''.join(string(a) for a in pointers))}
                for i, pointers in enumerate(arrays)]
    assert len(programs) == 30
    # These ranges are exact address spans, not inferred PE sections.
    ranges = {'curve_pool': (0x426de0, 0x42fc54),
              'timeline_ranges': (0x42fc50, 0x42fde0),
              'timeline_tokens': (0x42fde0, 0x42fea8),
              'timeline_track_ranges': (0x42fea8, 0x430038),
              'uniform_descriptors': (0x430038, 0x4357e0),
              'program_recipes': (0x4357e0, 0x4358d0),
              'framebuffers': (0x4358d0, 0x4359d4),
              'pass_routes': (0x4359d0, 0x435ac0),
              'pass_static_uniform_views': (0x435ac0, 0x435b44),
              'pass_inputs': (0x435ae4, 0x435e2c),
              'scene_pass_lists': (0x435e2c, 0x4361ec),
              'physics_constants': (0x436410, 0x4364d0)}
    # 13 framebuffer records end at 0x4359d4; the final zero flag aliases
    # the first pass's program index at 0x4359d0. Preserve this overlap.
    tables = {k: dict(base=hex(a), end_exclusive=hex(b),
                      **asset(f'tables/{k}.bin', at(a, b-a)))
              for k, (a, b) in ranges.items()}
    framebuffer = []
    texture = 0
    for i in range(13):
        count, width, height, divisor, init_only = words(0x4358d0 + i * 20, 5)
        assert count in (1, 3) and divisor > 0 and init_only in (0, 1)
        framebuffer.append({'index': i, 'address': hex(0x4358d0 + 20*i),
                            'attachments': count, 'width': width, 'height': height,
                            'size_divisor': divisor, 'initialization_only': bool(init_only),
                            'texture_indices': list(range(texture, texture+count))})
        texture += count
    assert texture == 15
    passes = []
    for i in range(30):
        program, selector = words(0x4359d0 + i * 8, 2)
        count, *inputs = words(0x435ae4 + i * 28, 7)
        assert program < 30 and selector <= 13 and count <= 6
        assert all(t < 15 for t in inputs[:count])
        static_count, = words(0x435ac0 + i * 4, 1)
        assert static_count == 0
        passes.append({'index': i, 'program': program, 'static_uniform_count': static_count,
                       'framebuffer': selector-1, 'texture_inputs': inputs[:count]})
    curves = {}
    rows = []
    tokens = words(0x42fde0, 50)
    all_descriptors = set()
    for row in range(50):
        begin, end = floats(0x42fc50 + 8 * row, 2)
        offset, count = words(0x42fea8 + 8 * row, 2)
        token = tokens[row]
        pass_count, = words(0x435e2c + token * 4, 1)
        route = words(0x435e30 + token * 4, pass_count)
        assert all(p < 30 for p in route)
        descriptors = []
        for j in range(count):
            address = 0x430038 + 4*offset + 40*j
            assert 0x430038 <= address < 0x4357e0
            all_descriptors.add(address)
            index, components, *channels = words(address, 10)
            assert 1 <= components <= 4
            refs = []
            for component in range(components):
                start, length = channels[component*2:component*2+2]
                assert length >= 4 and length % 4 == 0
                base = 0x426de0 + 4*start
                assert base + length*4 <= 0x42fc54
                key = f'{start}:{length}'
                bits = words(base, length)
                values = floats(base, length)
                times = values[1::4]
                assert all(a <= b for a, b in zip(times, times[1:])), (row, j, component)
                curves[key] = {'address': hex(base), 'word_count': length,
                               'key_count': length//4, 'float32_bits': bits,
                               'duplicate_times': [a for a,b in zip(times,times[1:]) if a == b]}
                refs.append(key)
            descriptors.append({'address': hex(address), 'name_index': index,
                                'uniform': name(index), 'components': components,
                                'curve_refs': refs})
        rows.append({'row': row, 'beats_half_open': [begin, end],
                     'seconds_half_open': [begin*.75, end*.75],
                     'controlled_frames_half_open': [int(begin*45), int(end*45)],
                     'scene_token': token, 'passes': route, 'uniforms': descriptors})
    assert rows[0]['beats_half_open'][0] == 0 and rows[-1]['beats_half_open'][1] == 600
    assert all(a['beats_half_open'][1] == b['beats_half_open'][0] for a,b in zip(rows,rows[1:]))
    assert set(all_descriptors) == set(range(0x430038, 0x4357e0, 40))
    decoded = asset('engine-tables.json', encoded({'framebuffers': framebuffer,
                    'passes': passes, 'rows': rows, 'curves': curves}))
    manifest = {'schema': 'eidolon-graphics-static-v1',
                'source_manifest': 'reports/evidence/reverse/manifest.json',
                'source_key': 'runtime_diagnostic.files.postfix',
                'tools': {'python': '3.14.7', 'objdump': '2.47', 'ghidra': '12.1.4'},
                'execution': 'static extraction; no GPU/Wine; snapshot environment in source manifest',
                'loading_shader': hex(loader_pointer), 'chunks': chunks,
                'programs': programs, 'tables': tables, 'decoded': decoded,
                'counts': {'unique_shader_chunks_including_loading': len(chunks),
                           'unique_shader_bytes_excluding_nuls': sum(c['bytes'] for c in chunks),
                           'programs_excluding_loading': len(programs),
                           'rows': len(rows), 'unique_scene_tokens': len(set(tokens)),
                           'uniform_descriptors': len(all_descriptors),
                           'unique_curve_views': len(curves),
                           'framebuffers': len(framebuffer), 'textures_2d': texture},
                'limitations': ['Decoded tables are static, not executed GL-state observations',
                                'Curve float32_bits preserve negative zero and native tangents',
                                'Fourth-component native gate needs review before supporting vec4 tracks',
                                'No graphics equivalence or full-reference acceptance is asserted']}
    target = ROOT / 'analysis/graphics/assets.json'
    if args.write_manifest:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encoded(manifest))
    else:
        assert json.loads(target.read_bytes()) == json.loads(encoded(manifest)), 'manifest differs'
    for relative, content in outputs.items():
        destination = out / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            assert destination.read_bytes() == content, str(destination)
        else:
            destination.write_bytes(content)
    print(json.dumps({'status': 'STATIC_ASSETS_VERIFIED', **manifest['counts']}, sort_keys=True))


if __name__ == '__main__':
    main()
