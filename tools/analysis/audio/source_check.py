#!/usr/bin/env python3
"""Adapt pinned public player OS glue for bounded Linux CPU diagnostic comparison."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import time


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frames', type=int, default=262144)
    p.add_argument('--closed-bank', action='store_true', help='Zero every PCM wave outside the conservative 15-sample closure in a private bank copy')
    p.add_argument('--manifest', type=Path)
    args = p.parse_args()
    assert 0 < args.frames <= 19964544 and args.frames % 64 == 0
    root, data = Path(os.environ['EIDOLON_ROOT']), Path(os.environ['EIDOLON_DATA'])
    previous = json.loads(Path('analysis/audio/manifest.json').read_text())
    source = root / '.tools/analysis/audio/64klang'
    build = data / 'analysis/audio/T19' / ('source-player-closed' if args.closed_bank else 'source-player')
    build.mkdir(parents=True, exist_ok=True)
    inputs, adaptations = {}, []
    for name in ('Synth.cpp', 'Synth.h', 'SynthNode.cpp', 'SynthNode.h', 'SynthAllocator.h', 'sample_t.cpp', 'sample_t.h'):
        raw = subprocess.check_output(['git', '-C', str(source), 'show', f"{previous['source']['commit']}:Player/Player/{name}"])
        if name in previous['source']['files']:
            assert sha(raw) == previous['source']['files'][name]
        inputs[name] = sha(raw)
        text = raw.decode()
        if name == 'sample_t.h':
            text = text.replace('#include <intrin.h>', '#include <immintrin.h>\n#define _MM_ALIGN16\n#define __int64 long long\n#define __fastcall')
            text = re.sub(r'(operator(?:==|!=|<=|>=|<|>)\s*\(const sample_t& x\))', r'\1 const', text)
            adaptations.append('sample_t.h: platform intrinsic include and MSVC type/calling-convention spellings only')
            adaptations.append('sample_t.h: pure comparison members marked const')
        if name == 'SynthNode.cpp':
            for function in ('TriSaw', 'Pulse', 'Sampler_Sample', 'SetBufferSample'):
                lines = text.splitlines(keepends=True)
                for i, line in enumerate(lines):
                    if function + '(' in line and line.startswith('inline '):
                        lines[i] = line.replace('sample_t&', 'const sample_t&')
                text = ''.join(lines)
            adaptations.append('SynthNode.cpp: read-only helper parameters accept const references for standard C++ temporary binding')
            text = text.replace('goto CreateNodes_ReturnExisting;', 'return CreateNodes(offset, true);')
            for i in (2, 3):
                text = text.replace(f'n->v[{i}].i[0] = (int)(pdata+', f'n->v[{i}].l[0] = (long long)(pdata+')
                text = text.replace(f'(char*)(n->v[{i}].i[0])', f'(char*)(n->v[{i}].l[0])')
            adaptations.append('SynthNode.cpp: equivalent immediate return avoids goto crossing initialization; TRIGGERSEQ pointer lanes widened for host')
            text = re.sub(r'(void SYNTHCALL \w+_tick\(SynthNode\* n\)\s*\{)',
                          r'\1\n source_seen[n->valueOffset] = 1;', text)
            text = 'extern unsigned char source_seen[4096];\n' + text
            adaptations.append('SynthNode.cpp: integer-only tick-entry node-offset coverage bitmap; includes cache hits')
        (build / name).write_text(text)
    windows = '''#pragma once
#include <cstdint>
#define __fastcall
#define __int64 long long
typedef uint8_t BYTE; typedef uint16_t WORD; typedef uint32_t DWORD;
typedef int BOOL; typedef void* HANDLE; typedef BYTE* LPBYTE;
#define TRUE 1
#define GENERIC_READ 0x80000000u
#define FILE_SHARE_READ 1
#define OPEN_EXISTING 3
#define FILE_ATTRIBUTE_NORMAL 0x80
#define MAKEFOURCC(a,b,c,d) ((DWORD)(a)|((DWORD)(b)<<8)|((DWORD)(c)<<16)|((DWORD)(d)<<24))
unsigned GetSystemDirectoryA(char*,unsigned);
HANDLE CreateFileA(const char*,unsigned,unsigned,void*,unsigned,unsigned,void*);
int ReadFile(HANDLE,void*,unsigned,DWORD*,void*);
int CloseHandle(HANDLE);
'''
    (build / 'windows.h').write_text(windows)
    # Every absent dispatch unit is compiled out; preserve all submodes of used nodes.
    all_names = ['SHAPER', 'SCALE', 'LOGIC', 'SELECT', 'CROSSMIX', 'EQ', 'SAMPLEREC', 'ABS',
                 'SQRT', 'SAPI', 'BOWED', 'FORMULA', 'SNH', 'WTFOSC', 'EQ3']
    flags = all_names + ['STOREDSAMPLES', 'SPECIALDATA', 'SONG_AFTERTOUCH']
    (build / '64k2Patch.h').write_text('#pragma once\n#define ADSR_SKIP_TRIGGER_GATE\n' + ''.join(f'#define {n}_SKIP\n' for n in flags))
    adaptations.append('Recovered native build flag ADSR_SKIP_TRIGGER_GATE: all54 native ADSRs have five references, not seven')
    command = ['g++', '-O2', '-msse4.1', '-D_M_X64', '-ffp-contract=off', '-fno-fast-math',
               '-frounding-math', '-Wno-unknown-pragmas', '-include', str(build / '64k2Patch.h'), '-I', str(build),
               'tools/analysis/audio/source_player.cpp'] + [str(build / n) for n in ('Synth.cpp', 'SynthNode.cpp', 'sample_t.cpp')] + ['-o', str(build / 'source-player')]
    subprocess.run(command, check=True)
    base = data / 'analysis/audio/T19'
    image = (data / previous['inputs']['postfix']['path']).read_bytes()
    assert sha(image) == previous['inputs']['postfix']['sha256']
    assert (base / 'score-encoded.bin').read_bytes() == image[0x37040:0x3edcf]
    assert (base / 'patch-and-trailer.bin').read_bytes() == image[0x3edf0:0x40c30]
    node_bytes = (base / 'nodes.json').read_bytes()
    assert sha(node_bytes) == previous['patch']['nodes_sha256']
    nodes = json.loads(node_bytes)
    assert len([n for n in nodes if n['id'] == 5]) == 54
    assert all(len(n['refs']) == 5 for n in nodes if n['id'] == 5)
    bank = data / 'reference/dependencies/gm.dls'
    assert sha(bank.read_bytes()) == previous['inputs']['dls']['sha256']
    bank_transformation = None
    if args.closed_bank:
        closure = json.loads(Path('analysis/audio/audit.json').read_text())['event_closure']['event_reachable_samples']
        raw = bytearray(bank.read_bytes())
        def chunks(start, end):
            while start + 8 <= end:
                length, = struct.unpack_from('<I', raw, start + 4)
                assert start + 8 + length <= end
                yield bytes(raw[start:start+4]), start + 8, length
                start += 8 + length + (length & 1)
        pools = [(p, n) for kind, p, n in chunks(12, len(raw)) if kind == b'LIST' and raw[p:p+4] == b'wvpl']
        assert len(pools) == 1
        pool, length = pools[0]
        zeroed, retained, count = 0, 0, 0
        for kind, wave, size in chunks(pool + 4, pool + length):
            assert kind == b'LIST' and raw[wave:wave+4] == b'wave'
            for name, off, size2 in chunks(wave + 4, wave + size):
                if name == b'data':
                    if count not in closure:
                        raw[off:off+size2] = b'\0' * size2
                        zeroed += size2
                    else:
                        retained += size2
            count += 1
        assert retained == 85548
        bank = build / 'closed-bank.dls'
        bank.write_bytes(raw)
        bank_transformation = {'retained_samples': closure, 'retained_pcm_bytes': retained,
                               'zeroed_pcm_bytes': zeroed, 'wave_count': count, 'sha256': sha(raw)}
    output = build / f'pcm-{args.frames}.f32le'
    started = time.monotonic()
    run = [str(build / 'source-player'), str(base / 'score-encoded.bin'), str(base / 'patch-and-trailer.bin'),
           str(bank), str(output), str(args.frames), str(build / 'coverage.bin')]
    completed = subprocess.run(run, check=True, capture_output=True, text=True, timeout=300)
    elapsed = time.monotonic() - started
    saved_path = Path('artifacts/reference/proxy-b-d12-volume-20261016.json')
    saved = json.loads(saved_path.read_text())
    reference_path = data / 'reference' / saved['run_id'] / 'pcm.f32le'
    reference = reference_path.read_bytes()
    assert sha(reference) == saved['evidence'][str(reference_path.relative_to(data))]
    actual = output.read_bytes()
    assert len(actual) == args.frames * 8
    expected = reference[:len(actual)]
    equal = actual == expected
    first = None if equal else next(i for i, (a, b) in enumerate(zip(actual, expected)) if a != b)
    seen = (build / 'coverage.bin').read_bytes()
    covered = [n for n in nodes if seen[n['offset_words']]]
    assert all(i < 3836 for i, hit in enumerate(seen) if hit)
    result = {'source_commit': previous['source']['commit'], 'source_files': inputs,
              'adaptations': adaptations + ['Linux zero-initializing aligned allocator/deferred free and pinned-file I/O shim',
                                            '_M_X64 source pointer layout; native PE32 ABI is not reproduced'],
              'compiler': subprocess.check_output(['g++', '--version'], text=True).splitlines()[0],
              'compile_command': command, 'run_command': run, 'stdout': completed.stdout,
              'build_files': {f.name: sha(f.read_bytes()) for f in build.iterdir() if f.suffix in ('.cpp', '.h')},
              'harness_sha256': sha(Path('tools/analysis/audio/source_player.cpp').read_bytes()),
              'binary_sha256': sha((build / 'source-player').read_bytes()),
              'input_image_sha256': sha(image), 'bank_transformation': bank_transformation,
              'coverage': {'kind': 'source tick entries including cache hits',
                           'node_types': sorted({n['name'] for n in covered}),
                           'native_tick_addresses': sorted({n['tick_va'] for n in covered}),
                           'node_offsets': sorted(n['offset_words'] for n in covered),
                           'gmdls_samples': sorted({struct.unpack_from('<H', image, 0x3edf0 + 2*n['mode_word_offset'])[0]
                                                   for n in covered if n['id'] == 52})},
              'frames': args.frames, 'elapsed_seconds': elapsed,
              'actual_sha256': sha(actual), 'reference_prefix_sha256': sha(expected),
              'reference_manifest_sha256': sha(saved_path.read_bytes()),
              'reference_full_sha256': sha(reference), 'equal': equal,
              'first_mismatch_byte': first, 'first_mismatch_sample': first // 8 if first is not None else None,
              'limitations': ['CPU source diagnostic, not Rust conformance or new reference acceptance.',
                              'Equality covers this fixed score/bank/initial state, not all kernel inputs or host ABI behavior.']}
    if first is not None:
        sample = first // 8
        result['first_actual_f32'] = struct.unpack_from('<2f', actual, sample * 8)
        result['first_reference_f32'] = struct.unpack_from('<2f', expected, sample * 8)
    (build / f'comparison-{args.frames}.json').write_text(json.dumps(result, indent=2) + '\n')
    if args.manifest:
        args.manifest.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'coverage'}, indent=2))
    print('COVERAGE', len(covered), 'nodes', len(result['coverage']['node_types']), 'types', result['coverage']['gmdls_samples'])


if __name__ == '__main__':
    main()
