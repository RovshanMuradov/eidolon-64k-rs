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
    temporary = BUILD / 'tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ['TMPDIR'] = str(temporary)
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
    runtime = BUILD / 'cross' / TARGET / 'release/eidolon-runtime.exe'
    runtime_repeat = BUILD / 'cross-repeat' / TARGET / 'release/eidolon-runtime.exe'
    assert runtime.read_bytes() == runtime_repeat.read_bytes(), 'runtime builds differ'
    runtime_headers = run('objdump', '-p', runtime, capture=True).decode()
    runtime_bytes = runtime.read_bytes()
    runtime_pe_offset, = struct.unpack_from('<I', runtime_bytes, 0x3c)
    assert runtime_bytes[runtime_pe_offset:runtime_pe_offset+4] == b'PE\0\0'
    assert struct.unpack_from('<H', runtime_bytes, runtime_pe_offset + 4)[0] == 0x14c
    assert struct.unpack_from('<I', runtime_bytes, runtime_pe_offset + 8)[0] == 0
    for index, program in enumerate(programs):
        for address in program:
            path = 'shaders/00409918-effective.glsl' if index == 0 and address == '0x409918' else chunks[address]
            assert (ROOT / path).read_bytes() + b'\0' in runtime_bytes, ('runtime source missing', index, address)
    runtime_imports = [line.split('DLL Name:', 1)[1].strip()
                       for line in runtime_headers.splitlines() if 'DLL Name:' in line]
    for required in ('wglCreateContext', 'wglMakeCurrent', 'wglGetProcAddress', 'SwapBuffers',
                     'waveOutOpen', 'waveOutPrepareHeader', 'waveOutWrite', 'waveOutGetPosition',
                     'waveOutReset', 'waveOutUnprepareHeader', 'waveOutClose'):
        assert required in runtime_headers, required
    assert 'eidolon_runtime_event' in runtime_headers, 'missing capture ABI export'
    run(sys.executable, 'tools/rust/check_windows_abi.py')
    inputs = [ROOT / p for p in ('Cargo.toml', 'Cargo.lock', 'build.rs', 'rust-toolchain.toml', '.cargo/config.toml')]
    inputs += sorted((ROOT / 'src').rglob('*.rs'))
    inputs += [ROOT / 'artifacts/rust/engine/assets.json']
    manifest = {
        'schema': 'eidolon-rust-engine-build-v1',
        'scope': 'Integrated standalone-Rust WGL/waveOut production candidate; target runtime unexecuted',
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
        'runtime_candidate': {'path': str(runtime.relative_to(Path(os.environ['EIDOLON_DATA']))),
                              'bytes': runtime.stat().st_size, 'sha256': sha(runtime),
                              'imports': runtime_imports, 'independent_build_equal': True,
                              'synth_integrated': True, 'target_executed': False},
        'inputs': {str(p.relative_to(ROOT)): sha(p) for p in inputs},
        'runtime': {'resolution': None, 'gpu': None, 'driver': None, 'wine': None,
                    'target_executed': False, 'native_equivalence': False},
    }
    destination = ROOT / 'artifacts/rust/engine/build.json'
    destination.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'status': 'RUST_ENGINE_BUILD_VERIFIED', 'pe_bytes': len(raw),
                      'sha256': sha(pe), 'independent_build_equal': True, 'shader_elements': source_count,
                      'track_scalars': tracks['scalar_samples'], 'host_tests': 4,
                      'runtime_bytes': runtime.stat().st_size, 'runtime_sha256': sha(runtime)}))


if __name__ == '__main__':
    main()
