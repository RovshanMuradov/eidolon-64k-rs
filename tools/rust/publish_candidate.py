#!/usr/bin/env python3
"""Publish a content-addressed, read-only production candidate and rebuild from its source archive.

Only builds and reads PE files. It never launches Wine, Windows code, or graphics.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ['EIDOLON_DATA'])
BUILD = DATA / 'builds/T22'


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    return sha_bytes(path.read_bytes())


def command(*args, cwd=ROOT):
    return subprocess.check_output([str(a) for a in args], cwd=cwd)


def write_once(path, data):
    if path.exists():
        assert path.read_bytes() == data, ('immutable candidate already differs', str(path))
    else:
        with path.open('xb') as stream:
            stream.write(data)
        path.chmod(0o444)


def main():
    assert not command('git', 'status', '--porcelain').strip(), 'commit all verified source/proof changes before publishing'
    commit = command('git', 'rev-parse', 'HEAD').decode().strip()
    build_path = ROOT / 'artifacts/rust/engine/build.json'
    build = json.loads(build_path.read_bytes())
    audio_path = ROOT / 'artifacts/rust/engine/audio-integration.json'
    audio = json.loads(audio_path.read_bytes())
    assert audio['equal'] and audio['build_manifest_sha256'] == sha(build_path)
    assert build['runtime_candidate']['synth_integrated']
    exe = DATA / build['runtime_candidate']['path']
    digest = sha(exe)
    assert digest == build['runtime_candidate']['sha256'] == audio['production_pe_sha256']
    for path, expected in build['inputs'].items():
        assert sha(ROOT / path) == expected, ('source no longer matches build', path)
    destination = BUILD / 'candidates' / digest
    destination.mkdir(parents=True, exist_ok=True)
    files = command('git', 'ls-files', '-z', 'Cargo.toml', 'Cargo.lock', 'build.rs', 'rust-toolchain.toml',
                    '.cargo', 'src', 'shaders').decode().split('\0')
    files = sorted(path for path in files if path)
    archive_data = io.BytesIO()
    inventory = {}
    with tarfile.open(fileobj=archive_data, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for path in files:
            data = (ROOT / path).read_bytes()
            inventory[path] = {'bytes': len(data), 'sha256': sha_bytes(data)}
            entry = tarfile.TarInfo(path)
            entry.size = len(data)
            entry.mode = 0o644
            entry.mtime = 0
            archive.addfile(entry, io.BytesIO(data))
    # A source-path-independent rebuild detects hidden worktree/build-directory dependencies.
    relocated = BUILD / 'relocated' / digest
    source = relocated / 'source'
    source.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive_data.getvalue())) as archive:
        archive.extractall(source, filter='data')
    temporary = relocated / 'tmp'
    temporary.mkdir(exist_ok=True)
    os.environ['TMPDIR'] = str(temporary)
    command('cargo', 'build', '--locked', '--offline', '--release', '--target', 'i686-pc-windows-gnu',
            '--bin', 'eidolon-runtime', '--target-dir', relocated / 'target', cwd=source)
    rebuilt = relocated / 'target/i686-pc-windows-gnu/release/eidolon-runtime.exe'
    assert sha(rebuilt) == digest, 'relocated source-archive rebuild differs'
    payloads = {
        'eidolon-runtime.exe': exe.read_bytes(),
        'source.tar': archive_data.getvalue(),
        'source-inventory.json': (json.dumps(inventory, indent=2, sort_keys=True) + '\n').encode(),
        'build.json': build_path.read_bytes(),
        'audio-integration.json': audio_path.read_bytes(),
        'windows-abi.json': (ROOT / 'artifacts/rust/engine/windows-abi.json').read_bytes(),
        'native-feedback.json': (ROOT / 'artifacts/rust/engine/native-feedback.json').read_bytes(),
    }
    provenance = {
        'schema': 'eidolon-integrated-candidate-v1', 'kind': 'production-build-awaiting-runtime-verification',
        'source_commit': commit, 'source_audio_ancestor': command('git', 'rev-parse', 'd1dda46').decode().strip(),
        'executable_sha256': digest, 'executable_bytes': len(payloads['eidolon-runtime.exe']),
        'files': {path: {'path': path, 'bytes': len(data), 'sha256': sha_bytes(data)} for path, data in payloads.items()},
        'relocated_source_rebuild_equal': True,
        'build_command': ['cargo', 'build', '--locked', '--offline', '--release', '--target',
                          'i686-pc-windows-gnu', '--bin', 'eidolon-runtime'],
        'run_argv': [str(destination / 'eidolon-runtime.exe'), '--play'],
        'diagnostic_argv': [str(destination / 'eidolon-runtime.exe'), '--graphics-diagnostic'],
        'capture_export': {'name': 'eidolon_runtime_event', 'calling_convention': 'cdecl',
            'arguments': ['u32 kind', 'const u8* data', 'u32 bytes'],
            'snapshot_bytes': 284, 'snapshot_header_u32': ['frame_index', 'cursor', 'seconds_bits',
                'beat_bits', 'row', 'local_beat_bits', 'dt_bits'], 'physics_records_bytes': 256,
            'events': {'1': 'pre-first-query snapshot', '2': 'evaluated query', '3': 'before timeline SwapBuffers',
                       '4': 'after timeline SwapBuffers', '5': 'terminal query/no present',
                       '6': 'stable complete PCM before submission', '7': 'PCM after waveOutWrite'},
            'payload_lifetime': 'borrowed for synchronous callback only'},
        'dependency_policy': 'no runtime asset files or C++ synth; system DLL imports enumerated in build.json',
        'target_executed': False, 'production_accepted': False,
        'remaining_execution': ['Windows x86 numeric/ABI validation', 'WGL/shader/pass and final-frame comparison',
            'waveOut/complete PCM capture', 'authenticated initial-state and endpoint observations',
            'startup/runtime/memory/size performance baseline'],
    }
    payloads['candidate.json'] = (json.dumps(provenance, indent=2) + '\n').encode()
    for path, data in payloads.items():
        write_once(destination / path, data)
    pointer = {'schema': 'eidolon-candidate-pointer-v1', 'directory': str(destination),
               'manifest_sha256': sha(destination / 'candidate.json'), 'source_commit': commit,
               'executable_sha256': digest, 'executable_bytes': exe.stat().st_size,
               'relocated_source_rebuild_equal': True, 'target_executed': False, 'production_accepted': False}
    (ROOT / 'artifacts/rust/engine/candidate.json').write_text(json.dumps(pointer, indent=2) + '\n')
    print(json.dumps({'status': 'IMMUTABLE_INTEGRATED_CANDIDATE_PUBLISHED', **pointer}))


if __name__ == '__main__':
    main()
