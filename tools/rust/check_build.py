#!/usr/bin/env python3
"""Reproducible cross-build, host CPU checks and embedded shader-byte verification.

Execute via bash tools/run. PE files are inspected, never executed.
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BUILD = Path(os.environ['EIDOLON_DATA']) / 'builds/T22'
TARGET = 'i686-pc-windows-gnu'
HOST = 'x86_64-unknown-linux-gnu'


def run(*args, capture=False):
    return subprocess.run([str(a) for a in args], cwd=ROOT, check=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    versions = {tool: run(tool, '--version', capture=True).decode().splitlines()[0]
                for tool in ('rustc', 'cargo', 'i686-w64-mingw32-gcc', 'objdump')}
    run(sys.executable, 'tools/rust/import_assets.py', '--check')
    for directory, target in [('host', HOST), ('cross', TARGET), ('cross-repeat', TARGET)]:
        run('cargo', 'build', '--locked', '--offline', '--release', '--target', target,
            '--target-dir', BUILD / directory)
    run('cargo', 'test', '--locked', '--offline', '--release', '--target', HOST,
        '--target-dir', BUILD / 'host')
    probe = BUILD / 'host' / HOST / 'release/eidolon-engine'
    pe = BUILD / 'cross' / TARGET / 'release/eidolon-engine.exe'
    repeat = BUILD / 'cross-repeat' / TARGET / 'release/eidolon-engine.exe'
    assert pe.read_bytes() == repeat.read_bytes(), 'independent output directories produced different PE bytes'
    raw = pe.read_bytes()
    assert raw[:2] == b'MZ'
    pe_offset, = struct.unpack_from('<I', raw, 0x3c)
    assert raw[pe_offset:pe_offset+4] == b'PE\0\0'
    machine, sections, timestamp = struct.unpack_from('<HHI', raw, pe_offset + 4)
    assert machine == 0x14c and timestamp == 0
    imports = [line.split('DLL Name:', 1)[1].strip() for line in
               run('objdump', '-p', pe, capture=True).decode().splitlines() if 'DLL Name:' in line]
    assert probe.read_bytes()[:4] == b'\x7fELF'
    tracks = json.loads(run(sys.executable, 'tools/rust/check_tracks.py', probe, capture=True))
    shaders = run(probe, '--shader-stream', capture=True)
    assert shaders[:8] == b'EIDGLS01'
    offset = 8

    def word():
        nonlocal offset
        value, = struct.unpack_from('<I', shaders, offset)
        offset += 4
        return value

    recovered = json.loads((ROOT / 'analysis/graphics/assets.json').read_bytes())
    chunks = {c['address']: c['path'] for c in recovered['chunks']}
    programs = [p['source_addresses'] for p in recovered['programs']] + [[recovered['loading_shader']]]
    assert word() == len(programs) == 31
    source_count = 0
    for index, program in enumerate(programs):
        assert word() == len(program)
        for address in program:
            path = chunks[address]
            if index == 0 and address == '0x409918':
                path = 'shaders/00409918-effective.glsl'
            expected = (ROOT / path).read_bytes() + b'\0'
            size = word()
            actual = shaders[offset:offset+size]
            offset += size
            assert actual == expected, (index, address)
            # Ensure effective source bytes are embedded in the cross-built PE too.
            assert expected in raw, (index, address, 'missing from PE')
            source_count += 1
    assert offset == len(shaders) and source_count == 235
    inputs = [ROOT / p for p in ('Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml', '.cargo/config.toml')]
    inputs += sorted((ROOT / 'src').rglob('*.rs'))
    inputs += [ROOT / 'artifacts/rust/engine/assets.json']
    manifest = {
        'schema': 'eidolon-rust-engine-build-v1',
        'scope': 'CPU candidate, not audiovisual runtime or native equivalence',
        'tools': versions,
        'target': TARGET,
        'profile': 'release; opt-level=s; lto=true; codegen-units=1; panic=abort; strip=symbols',
        'target_features': '+sse2,+sse4.1; no fast-math or explicit FMA',
        'pe': {'path': str(pe.relative_to(Path(os.environ['EIDOLON_DATA']))), 'bytes': len(raw),
               'sha256': sha(pe), 'machine': machine, 'sections': sections, 'timestamp': timestamp, 'imports': imports},
        'independent_build_equal': True,
        'host_probe_sha256': sha(probe),
        'host_tests': 4,
        'raw_track_check': tracks,
        'embedded_shader_array_elements': source_count,
        'inputs': {str(p.relative_to(ROOT)): sha(p) for p in inputs},
        'runtime': {'resolution': None, 'gpu': None, 'driver': None, 'wine': None,
                    'target_executed': False, 'native_equivalence': False},
    }
    destination = ROOT / 'artifacts/rust/engine/build.json'
    destination.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'status': 'RUST_ENGINE_BUILD_VERIFIED', 'pe_bytes': len(raw),
                      'sha256': sha(pe), 'independent_build_equal': True, 'shader_elements': source_count,
                      'track_scalars': tracks['scalar_samples'], 'host_tests': 4}))


if __name__ == '__main__':
    main()
