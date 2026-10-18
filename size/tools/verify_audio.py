#!/usr/bin/env python3
"""Render the size crate's entire PCM on an x86 host and compare every byte.

Usage: python3 size/tools/verify_audio.py --bank /path/to/gm.dls --reference /path/to/pcm.f32le
Outputs stay in .build/size-audio (override with --work). No Wine or GPU is used.
This checks the sizecoded audio source and LLVM options on the host; the linked,
postprocessed Windows executable still needs its separate target verification.
"""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
FRAMES = 19_964_544
BANK_SHA256 = '3229b09b9d7d9f3f4793b0d9b34fe6abc75cfa4a2503c0c90f43ff651ba7f2c0'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bank', required=True, type=Path)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--work', type=Path, default=ROOT / '.build/size-audio')
    args = parser.parse_args()
    if platform.machine().lower() not in ('x86_64', 'amd64', 'i686', 'i386'):
        sys.exit('the synth requires an x86 host with SSE4.1')
    expected = (ROOT / 'verify/pcm.sha256').read_text().split()[0]
    if args.bank.stat().st_size != 3_440_660 or digest(args.bank) != BANK_SHA256:
        sys.exit('bank identity mismatch')
    if args.reference.stat().st_size != FRAMES * 8 or digest(args.reference) != expected:
        sys.exit('reference PCM identity mismatch')
    args.work.mkdir(parents=True, exist_ok=True)
    binary = args.work.resolve() / 'render_pcm'
    output = args.work.resolve() / 'pcm.f32le'
    # Same codegen options as size/build.py. std supplies only the host adapter;
    # its prebuilt libraries require panic=abort rather than immediate-abort.
    sys.path.insert(0, str(ROOT / 'size'))
    from build import RUSTFLAGS
    import shlex
    flags = shlex.split(RUSTFLAGS.replace('panic=immediate-abort', 'panic=abort'))
    command = ['rustc', '--edition=2021', '--cfg', 'feature="sizecoded"',
               '-C', 'opt-level=z', '-C', 'codegen-units=1', '-C', 'lto=fat',
               *flags, str(ROOT / 'size/tools/render_pcm.rs'), '-o', str(binary)]
    print('compile:', shlex.join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=dict(os.environ, RUSTC_BOOTSTRAP='1'), check=True)
    output.unlink(missing_ok=True)
    start = time.monotonic()
    subprocess.run([str(binary), str(args.bank.resolve()), str(output)], cwd=ROOT, check=True)
    if output.stat().st_size != FRAMES * 8:
        sys.exit('rendered PCM extent mismatch')
    with output.open('rb') as actual, args.reference.open('rb') as reference:
        offset = 0
        while block := actual.read(1024 * 1024):
            other = reference.read(len(block))
            if block != other:
                at = offset + next(i for i, (a, b) in enumerate(zip(block, other)) if a != b)
                sys.exit(f'PCM mismatch at byte {at}, sample {at // 4}, frame {at // 8}')
            offset += len(block)
    actual = digest(output)
    if actual != expected:
        sys.exit(f'PCM hash mismatch: {actual}, expected {expected}')
    print(f'PASS size audio: {FRAMES} frames, {FRAMES * 8} bytes, byte-exact')
    print(f'SHA-256 {actual}; render + comparison {time.monotonic() - start:.1f}s')


if __name__ == '__main__':
    main()
