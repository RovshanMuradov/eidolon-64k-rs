#!/usr/bin/env python3
"""Static, hash-pinned score/patch/source comparison and lossless size experiment.

Run from the worktree root with tools/run. Writes large/recoverable outputs only
under EIDOLON_DATA/analysis/audio/T19. Never executes the target or source code.
"""
import argparse
import ast
from collections import Counter
import hashlib
import importlib.util
import json
import lzma
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import zipfile

import zstandard as zstd

PIN = '23d7cfcf5110f5ded50fae4a60e316d557a6d45a'
BASE = 0x400000


def sha(b):
    return hashlib.sha256(b).hexdigest()


def numeric(s):
    """Evaluate only literal arithmetic in the upstream constant table."""
    node = ast.parse(s.strip(), mode='eval').body

    def walk(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -walk(n.operand)
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Mult, ast.Div)):
            a, b = walk(n.left), walk(n.right)
            return a * b if isinstance(n.op, ast.Mult) else a / b
        raise ValueError(ast.dump(n))
    return walk(node)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, help='publish small versioned manifest')
    args = parser.parse_args()
    root, data = Path(os.environ['EIDOLON_ROOT']), Path(os.environ['EIDOLON_DATA'])
    out = data / 'analysis/audio/T19'
    out.mkdir(parents=True, exist_ok=True)
    source = root / '.tools/analysis/audio/64klang'
    source_files = {}
    for name in ('Synth.cpp', 'SynthNode.cpp', 'SynthNode.h', 'sample_t.cpp',
                 'sample_t.h', 'SynthAllocator.cpp', '64k2Patch.h', '64k2Song.h'):
        source_files[name] = subprocess.check_output(
            ['git', '-C', str(source), 'show', f'{PIN}:Player/Player/{name}'])
    provenance = json.loads(Path('reports/evidence/reverse/manifest.json').read_text())
    identity = provenance['runtime_diagnostic']['files']['postfix']
    image_path = data / identity['path']
    image = image_path.read_bytes()
    assert sha(image) == identity['sha256']
    (out / 'postfix-copy.bin').write_bytes(image)

    def at(a, n):
        b = image[a - BASE:a - BASE + n]
        assert len(b) == n
        return b

    def words(a, n):
        return struct.unpack('<' + 'I' * n, at(a, n * 4))

    def cstring(a):
        return image[a - BASE:image.index(0, a - BASE) + 1]

    # Independently match actual double bits, including deliberately truncated
    # polynomial coefficients; this does not claim whole-function equivalence.
    constants = source_files['sample_t.cpp'].decode().split('double ConstantList')[1]
    constants = constants.split('{', 1)[1].split('}', 1)[0]
    constants = re.sub(r'#ifndef S_SKIP_UNUSED.*?#endif', '', constants, flags=re.S)
    constants = re.sub(r'//[^\n]*', '', constants).replace('(double)SYNTH_SAMPLERATE', '44100')
    values = [float(numeric(x)) for x in constants.split(',') if x.strip()][3:]
    native_constants = at(0x4090b8, 0x409330 - 0x4090b8)
    source_constants = b''.join(struct.pack('<d', x) for x in values)
    assert source_constants == native_constants
    pins = {0x401198: '00108a104083e90175f6',
            0x401041: '660f38280530b8160b',
            0x401051: '660f70c072f30fe6c0',
            0x401648: 'b9c0ff000023c1',
            0x401665: '0fae542414',
            0x405b25: '8b41200fb710',
            0x405e47: '8b049dc0964000',
            0x405e51: '8b049de0974000'}
    for a, b in pins.items():
        assert at(a, len(bytes.fromhex(b))).hex() == b

    bpm, frames, quantum, size = struct.unpack('<fIII', at(0x437040, 16))
    encoded = at(0x437050, size)
    decoded = bytearray()
    last = 0
    for b in encoded:
        last = (last + b) & 255
        decoded.append(last)
    # Exact inverse protects against applying delta-decode to an already decoded dump.
    assert bytes((b - (decoded[i - 1] if i else 0)) & 255
                 for i, b in enumerate(decoded)) == encoded
    assert at(0x437050 + size, 4) == b'\xff' * 4
    decoded.extend(b'\xff' * 4)  # sentinel is deliberately outside deltaSize
    streams, events = [], []
    pos = 0
    while True:
        info, = struct.unpack_from('<I', decoded, pos)
        pos += 4
        if info == 0xffffffff:
            break
        count, channel, kind, special = info & 65535, info >> 28, (info >> 24) & 15, (info >> 16) & 255
        assert kind in (0, 1, 3), (pos, hex(info))
        width = 5 if kind == 1 else 4
        block = decoded[pos:pos + count * width]
        assert len(block) == count * width
        times = []
        for i in range(count):
            sample = quantum * (block[i] + (block[count + i] << 8) + (block[2 * count + i] << 16))
            assert sample < frames and (not times or sample >= times[-1])
            times.append(sample)
            events.append({'stream': len(streams), 'index': i, 'sample': sample,
                           'channel': channel, 'type': kind, 'special': special,
                           'value': block[3 * count + i],
                           # Native 0x40159f reads value2 for note-off too, although
                           # off streams store only four planes: retain adjacent
                           # decoded-stream bytes rather than inventing zero velocity.
                           'velocity': decoded[pos + 4 * count + i] if kind != 3 else None})
        streams.append({'channel': channel, 'type': kind, 'special': special,
                        'count': count, 'first_sample': min(times) if times else None,
                        'last_sample': max(times) if times else None})
        pos += count * width
    assert pos == size + 4, (pos, size)
    events.sort(key=lambda e: (e['sample'], e['stream'], e['index']))
    balance = Counter()
    for event in events:
        if event['type'] in (0, 1):
            key = event['channel'], event['value']
            balance[key] += 1 if event['type'] == 1 else -1
            assert balance[key] >= 0, event
    assert not any(balance.values())
    (out / 'events.json').write_text(json.dumps(events, separators=(',', ':')) + '\n')
    (out / 'score-decoded.bin').write_bytes(at(0x437040, 16) + decoded)

    # Follow references rather than guessing sizes of per-node inline modes.
    mono, stereo, maximum = 0xd00, 0xe90, 0xefc
    patch = at(0x43edf0, maximum * 2)
    (out / 'patch-and-trailer.bin').write_bytes(at(0x43edf0, 7744))
    (out / 'score-encoded.bin').write_bytes(at(0x437040, 16 + size + 4))
    pw = struct.unpack('<' + 'H' * maximum, patch)
    names_text = source_files['SynthNode.h'].decode().split('enum NodeIDs')[1].split('};')[0]
    names, enum_value = {}, 0
    for name, explicit in re.findall(r'^\s*([A-Z0-9_]+)_ID\b\s*(?:=\s*(\d+))?', names_text, re.M):
        enum_value = int(explicit) if explicit else enum_value
        names[enum_value] = name
        enum_value += 1
    assert names[52] == 'GMDLS' and names[64] == 'CONSTANT' and names[67] == 'VOICE_ATTACKVELOCITY'
    nodes = {}

    def visit(offset):
        assert 0 <= offset < maximum
        if offset in nodes or offset >= mono:
            return
        info = pw[offset]
        ident, n = info & 127, (info >> 8) & 127
        assert ident < 71 and n <= 16
        refs = list(pw[offset + 1:offset + 1 + n])
        nodes[offset] = {'offset_words': offset, 'id': ident,
                         'name': names[ident], 'global': bool(info & 0x8000), 'refs': refs,
                         'mode_word_offset': offset + 1 + n}
        for ref in refs:
            visit(ref)

    for offset in [0] + [3 * (c + 1) for c in range(16)]:
        visit(offset)
    offset = 51
    for _ in range(16):
        visit(offset)
        offset += 1 + ((pw[offset] >> 8) & 127)
    gmdls = sorted({pw[n['mode_word_offset']] for n in nodes.values() if n['id'] == 52})
    arp_count, = struct.unpack('<H', at(0x43edf0 + maximum * 2, 2))
    assert arp_count == 1
    arp = struct.unpack('<33H', at(0x43edf0 + maximum * 2 + 2, 66))
    assert at(0x440c2c, 2) == b'\xad\xde'
    ticks, inits = words(0x4096c0, 71), words(0x4097e0, 71)
    for node in nodes.values():
        node['tick_va'], node['init_va'] = hex(ticks[node['id']]), hex(inits[node['id']])
        assert ticks[node['id']] != 0
    (out / 'nodes.json').write_text(json.dumps(sorted(nodes.values(), key=lambda n: n['offset_words']), indent=2) + '\n')

    # Match the native literal-data scanner, not an assumed instrument number.
    bank_pin = json.loads(Path('artifacts/reference/dependencies/gm-dls.json').read_text())['bank']
    bank = (data / 'reference/dependencies/gm.dls').read_bytes()
    assert sha(bank) == bank_pin['sha256']
    waves, p = [], 0
    while p < len(bank) - 8:
        if bank[p:p + 4] == b'data':
            n, = struct.unpack_from('<I', bank, p + 4)
            assert n % 2 == 0 and p + 8 + n <= len(bank)
            waves.append(bank[p + 8:p + 8 + n])
            p += 8 + n
        p += 1
    assert len(waves) == 495
    selected = b''.join(waves[i] for i in gmdls)
    (out / 'gmdls-referenced-pcm16.bin').write_bytes(selected)
    delta_pcm = bytearray()
    for index in gmdls:
        wave = waves[index]
        values = struct.unpack('<' + 'H' * (len(wave) // 2), wave)
        differences = [(v - (values[i - 1] if i else 0)) & 65535 for i, v in enumerate(values)]
        transformed = bytes(v & 255 for v in differences) + bytes(v >> 8 for v in differences)
        last, recovered = 0, bytearray()
        for i in range(len(values)):
            last = (last + transformed[i] + (transformed[len(values) + i] << 8)) & 65535
            recovered.extend(struct.pack('<H', last))
        assert recovered == wave
        delta_pcm.extend(transformed)

    # T14's native MOV decoder enumerates actual shader source pointers.
    spec = importlib.util.spec_from_file_location('gate', 'tools/reverse/confirm_capture_gate.py')
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    arrays = gate.shader_arrays(image_path, words)
    loading_shader, = words(0x440c58, 1)  # T18 graphics-to-audio-sync handoff
    assert loading_shader == 0x426c58
    shader_ptrs = sorted(set(a for arr in arrays for a in arr) | {0x409918, loading_shader})
    start, end = 0x401000, 0x440c5c
    labels = ['other_data'] * (end - start)

    def mark(a, b, label):
        assert start <= a <= b <= end
        for i in range(a - start, b - start):
            assert labels[i] in ('other_data', label), (hex(i + start), labels[i], label)
            labels[i] = label

    mark(0x401038, 0x405f98, 'audio_code')
    mark(0x401000, 0x401038, 'engine_code')
    mark(0x405f98, 0x408647, 'engine_code')
    for a in shader_ptrs:
        mark(a, a + len(cstring(a)), 'shaders')
    mark(0x437040, 0x437050 + size + 4, 'song')
    mark(0x43edf0, 0x440c30, 'patch_and_trailer')
    # T18's three overlapping graphics spans are one contiguous union here.
    mark(0x426de0, 0x4364d0, 'graphics_data')
    mark(0x440c30, 0x440c5c, 'graphics_data')
    parts = {label: bytearray() for label in sorted(set(labels))}
    for b, label in zip(at(start, end - start), labels):
        parts[label].append(b)
    assert sum(map(len, parts.values())) == end - start

    def sizes(raw):
        raw = bytes(raw)
        zs = zstd.ZstdCompressor(level=19, threads=0).compress(raw)
        xz = lzma.compress(raw, format=lzma.FORMAT_XZ, preset=9 | lzma.PRESET_EXTREME)
        bcj = lzma.compress(raw, format=lzma.FORMAT_XZ,
                            filters=[{'id': lzma.FILTER_X86}, {'id': lzma.FILTER_LZMA2, 'preset': 9 | lzma.PRESET_EXTREME}])
        assert zstd.ZstdDecompressor().decompress(zs) == raw
        assert lzma.decompress(xz) == raw == lzma.decompress(bcj)
        return {'raw': len(raw), 'zstd19': len(zs), 'xz9e': len(xz), 'xz9e_x86': len(bcj), 'sha256': sha(raw)}

    native = zipfile.ZipFile(root / provenance['inputs']['archive']['path']).read(provenance['inputs']['native']['archive_member'])
    assert sha(native) == provenance['inputs']['native']['sha256']
    measurements = {k: sizes(v) for k, v in parts.items()}
    measurements.update({
        'joint_native_order': sizes(at(start, end - start)),
        'joint_grouped': sizes(b''.join(parts.values())),
        'decoded_song': sizes(at(0x437040, 16) + decoded),
        'referenced_dls_pcm': sizes(selected), 'whole_dls_bank': sizes(bank),
        'referenced_dls_delta16_planar': sizes(delta_pcm),
        'joint_plus_referenced_dls': sizes(at(start, end - start) + selected),
        'joint_plus_delta16_dls': sizes(at(start, end - start) + delta_pcm),
        'packed_native_exe': sizes(native),
    })
    pe, = struct.unpack_from('<I', native, 0x3c)
    optional = pe + 24
    result = {
        'schema': 'eidolon-audio-static-v1',
        'source': {'repository': 'https://github.com/gopher-atz/64klang', 'commit': PIN,
                   'date': '2018-03-03', 'files': {k: sha(v) for k, v in source_files.items()},
                   'matched_constant_bytes': len(native_constants),
                   'source_extra_constant_bytes': len(source_constants) - len(native_constants),
                   'instruction_pins': {hex(a): b for a, b in pins.items()}},
        'inputs': {'postfix': identity, 'native': provenance['inputs']['native'], 'dls': bank_pin},
        'environment': {'python': sys.version, 'zstandard': zstd.__version__,
                        'zstd': zstd.ZSTD_VERSION, 'lzma': 'Python stdlib XZ, preset 9 EXTREME',
                        'resolution': None, 'gpu': None, 'driver': None, 'wine': None,
                        'scope': 'static file/source only'},
        'song': {'va': '0x437040', 'bpm': bpm, 'frames': frames, 'quantum': quantum,
                 'encoded_bytes': size, 'streams': streams,
                 'event_count': len(events), 'types': dict(Counter(e['type'] for e in events)),
                 'first_sample': events[0]['sample'], 'last_sample': events[-1]['sample'],
                 'events_sha256': sha((out / 'events.json').read_bytes())},
        'patch': {'va': '0x43edf0', 'mono_offset_words': mono, 'stereo_offset_words': stereo,
                  'max_offset_words': maximum, 'graph_nodes': len(nodes),
                  'mono_constants': (stereo - mono) // 2, 'stereo_constants': (maximum - stereo) // 4,
                  'arp_sequences': [{'loop_index': arp[0], 'steps_u16': list(arp[1:])}],
                  'node_types': dict(sorted(Counter(n['name'] for n in nodes.values()).items())),
                  'nodes_sha256': sha((out / 'nodes.json').read_bytes()),
                  'gmdls_indices': gmdls,
                  'gmdls_samples': [{'index': i, 'bytes': len(waves[i]), 'sha256': sha(waves[i])} for i in gmdls]},
        'measurement_domain': {'start': hex(start), 'end_exclusive': hex(end),
                               'shader_pointers': [hex(a) for a in shader_ptrs],
                               'all_domain_bytes_assigned_once': True},
        'pe': {'image_base': hex(struct.unpack_from('<I', native, optional + 28)[0]),
               'size_of_image': struct.unpack_from('<I', native, optional + 56)[0],
               'entry_rva': hex(struct.unpack_from('<I', native, optional + 16)[0]),
               'known_unpacker_entry_fragment_bytes': 1294,
               'full_unpacker_cost': None},
        'sizes': measurements,
        'limitations': ['Source lineage/format match, not exact source revision or PCM equivalence.',
                        '2018 source postdates 2017 native; native deferred-free placement differs.',
                        'Memory-layout compression includes gaps; no executable or unpacker generated.',
                        'Referenced DLS is conservative graph reachability, not measured active sample use.',
                        'Shader coverage includes T18 loading pointer; unclassified bytes remain in other_data.',
                        'No decompressor/import/startup/Rust runtime overhead in compressed proxies.']}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': 'STATIC_CHECKS_PASS', 'source_constant_bytes': len(native_constants),
                      'events': len(events), 'streams': len(streams), 'nodes': len(nodes),
                      'note_balance': 'pass', 'sizes': measurements, 'output': str(out)}, indent=2))


if __name__ == '__main__':
    main()
