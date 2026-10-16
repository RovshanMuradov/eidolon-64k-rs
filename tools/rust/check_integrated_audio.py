#!/usr/bin/env python3
"""Exercise the integrated Cargo release synth worker on Linux and compare complete native PCM."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ['EIDOLON_DATA'])
BUILD = DATA / 'builds/T22'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    build_path = ROOT / 'artifacts/rust/engine/build.json'
    build = json.loads(build_path.read_bytes())
    probe = BUILD / 'host/x86_64-unknown-linux-gnu/release/eidolon-engine'
    assert probe.read_bytes()[:4] == b'\x7fELF'
    assert sha(probe) == build['host_probe_sha256']
    for path, expected in build['inputs'].items():
        assert sha(ROOT / path) == expected, ('source changed after build', path)
    baseline = json.loads((ROOT / 'artifacts/rust/audio/standalone.json').read_bytes())
    for path, expected in baseline['rust_files'].items():
        assert sha(ROOT / path) == expected, ('T23 source changed', path)
    reference_manifest = ROOT / 'artifacts/reference/proxy-b-d13-detached-20261016-1-reference.json'
    reference = json.loads(reference_manifest.read_bytes())
    native = DATA / 'reference/proxy-b-d13-detached-20261016-1/pcm.f32le'
    assert sha(reference_manifest) == baseline['reference_manifest_sha256']
    assert sha(native) == reference['audio']['sha256']
    destination = BUILD / 'integrated-pcm.f32le'
    started = time.monotonic()
    result = subprocess.run([str(probe), '--render-pcm', str(destination)], check=True,
                            capture_output=True, text=True, timeout=600, cwd=ROOT)
    elapsed = time.monotonic() - started
    assert destination.stat().st_size == native.stat().st_size == 159716352
    first_difference = None
    offset = 0
    with destination.open('rb') as a, native.open('rb') as b:
        while chunk := a.read(1024 * 1024):
            expected = b.read(len(chunk))
            if chunk != expected:
                first_difference = offset + next(i for i, (x, y) in enumerate(zip(chunk, expected)) if x != y)
                break
            offset += len(chunk)
    manifest = {
        'schema': 'eidolon-integrated-audio-v1', 'kind': 'standalone-rust-host-integration-diagnostic',
        'build_manifest_sha256': sha(build_path), 'host_probe_sha256': sha(probe),
        'production_pe_sha256': build['runtime_candidate']['sha256'],
        'command': [str(probe), '--render-pcm', str(destination)], 'elapsed_seconds': elapsed,
        'pcm_path': str(destination), 'pcm_sha256': sha(destination), 'bytes': destination.stat().st_size,
        'frames': 19964544, 'equal': first_difference is None, 'first_mismatch_byte': first_difference,
        'reference_manifest_sha256': sha(reference_manifest), 'reference_pcm_sha256': sha(native),
        'worker': 'src/synthesis.rs::spawn(audio::render), same allocation/thread seam as Windows playback',
        'stdout': result.stdout, 'stderr': result.stderr, 'target_executed': False,
        'production_accepted': False,
        'scope': 'Cargo release host build, full PCM bytes; not Windows playback or graphics equivalence',
    }
    (ROOT / 'artifacts/rust/engine/audio-integration.json').write_text(json.dumps(manifest, indent=2) + '\n')
    assert manifest['equal'], manifest
    print(json.dumps({'status': 'INTEGRATED_HOST_PCM_EXACT', 'frames': 19964544,
                      'bytes': 159716352, 'elapsed_seconds': elapsed, 'sha256': manifest['pcm_sha256']}))


if __name__ == '__main__':
    main()
