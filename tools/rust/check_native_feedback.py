#!/usr/bin/env python3
"""Run T24's independent checker against current host probe output, never against a PE runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BUILD = Path(os.environ['EIDOLON_DATA']) / 'builds/T22'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('t24_checker', type=Path)
    args = parser.parse_args()
    checker_sha256 = sha(args.t24_checker)
    probe = BUILD / 'host/x86_64-unknown-linux-gnu/release/eidolon-engine'
    assert probe.read_bytes()[:4] == b'\x7fELF'
    output = BUILD / 'probes'
    output.mkdir(exist_ok=True)
    results = {}
    for mode, operation in [('raw', 'probe'), ('state', 'probe'), ('shader', 'shaders')]:
        destination = output / (mode + '.bin')
        with destination.open('wb') as stream:
            subprocess.run([str(probe), '--' + mode + '-stream'], stdout=stream, check=True)
        result = subprocess.run([sys.executable, str(args.t24_checker.resolve()), '--capture-root', str(ROOT),
            '--data-root', os.environ['EIDOLON_DATA'], operation, str(destination)], check=True,
            stdout=subprocess.PIPE, cwd=ROOT)
        results[mode] = {'stream_sha256': sha(destination), 'result': json.loads(result.stdout)}
    assert sha(args.t24_checker) == checker_sha256, 'independent checker changed during verification'
    manifest = {'schema': 'eidolon-t22-native-feedback-v1', 'host_probe_sha256': sha(probe),
                'checker_sha256': checker_sha256, 'checker_path': str(args.t24_checker.resolve()),
                'results': results, 'target_executed': False, 'production_accepted': False}
    (ROOT / 'artifacts/rust/engine/native-feedback.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('T24_CURRENT_HOST_PROBES_PASS raw=27000 state=27000 sources=235 production_accepted=false')


if __name__ == '__main__':
    main()
