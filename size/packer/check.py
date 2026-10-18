#!/usr/bin/env python3
"""Pack a prepared PE and roundtrip its prefilter stream through the real depacker.

Linux i386 execution support, gcc, Wine and NASM 2.10.09 are required. Reuses
size/build.py for the source-built packer. All products and the private Wine
prefix live in .build/packer-check. No GPU/audio/image-loader verification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
import build


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(data):
    return {'bytes': len(data), 'sha256': sha(data)}


def win(path):
    return 'Z:' + str(path.resolve()).replace('/', '\\')


def packed_stream(exe, expected_size):
    """Check the observer's entry/tail signatures and locate the coded bytes."""
    pe = struct.unpack_from('<I', exe, 60)[0]
    if exe[pe:pe + 4] != b'PE\0\0' or struct.unpack_from('<H', exe, pe + 6)[0] != 1:
        raise ValueError('expected a one-section kkrunchy PE')
    opt = pe + 24
    table = opt + struct.unpack_from('<H', exe, pe + 20)[0]
    start = table + 40
    entry = struct.unpack_from('<I', exe, opt + 16)[0]
    base = struct.unpack_from('<I', exe, opt + 28)[0]
    va = struct.unpack_from('<I', exe, table + 12)[0]
    raw = struct.unpack_from('<I', exe, table + 20)[0]
    offset = raw + entry - va
    code = exe[offset:offset + 31]
    if (len(code) != 31 or code[0] != 0xbd or code[5:8] != b'\xc7\x45\x00' or
            code[12] != 0xb8 or code[23:26] != b'\x50\xc7\x45' or
            struct.unpack_from('<I', code, 8)[0] != base + start or
            struct.unpack_from('<I', code, 27)[0] != expected_size):
        raise ValueError('stage0 observer entry signature/size changed')
    tail = rb'\x0f\x77\x58\x68.{4}\x68.{4}\x50\xbe.{4}\xbb.{4}\xc3'
    if len(re.findall(tail, exe, flags=re.S)) != 1:
        raise ValueError('stage0 observer tail signature changed')
    return exe[start:]


def build_harness(nasm, work, size):
    if not 0 < size < (1 << 20) - 64:
        raise ValueError('stream exceeds the native test harness bounds')
    source = (HERE / 'depacker.asm').read_text()
    marker = '.decodedone:\n'
    if source.count(marker) != 1:
        raise ValueError('cannot locate decoder completion hook')
    source = source.replace(marker, marker + '  extern harness_done\n  jmp harness_done\n')
    (work / 'depacker-test.asm').write_text(source)
    subprocess.run([nasm, '-f', 'elf32', '-I', str(HERE) + '/', '-o', work / 'depacker.o',
                    work / 'depacker-test.asm'], check=True)
    harness = work / 'decode'
    subprocess.run(['gcc', '-m32', '-O1', '-ffreestanding', '-fno-pic', '-fno-stack-protector',
                    '-nostdlib', '-static', '-no-pie', HERE / 'harness.c', work / 'depacker.o',
                    '-Wl,-z,noexecstack', '-o', harness, f'-Wl,--defsym,DEPACKEDSIZE={size}',
                    '-Wl,--defsym,DEPACKED=OUTBUF+64', '-Wl,--defsym,IMPORTS=0',
                    '-Wl,--defsym,LOADLIBRARY=0', '-Wl,--defsym,PATCHOFFS=0',
                    '-Wl,--defsym,PATCHVALUE=0'], check=True)
    return harness


def decode(harness, stream):
    def no_core():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    return subprocess.run([harness], input=stream, capture_output=True, timeout=60, preexec_fn=no_core)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path, help='PE already prepared by size/build.py')
    parser.add_argument('--packer', type=Path, help='reuse a source-built packer')
    parser.add_argument('--nasm', type=Path, help='NASM 2.10.09 (default: size/build.py cache)')
    parser.add_argument('--work', type=Path, default=ROOT / '.build/packer-check')
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, HERE / 'generate_model.py', '--check'], check=True)
    build.WORK.mkdir(parents=True, exist_ok=True)
    nasm = (args.nasm or build.build_nasm()).resolve()
    packer = (args.packer or build.build_packer(nasm)).resolve()
    packed, dump = work / 'packed.exe', work / 'prefilter.bin'
    packed.unlink(missing_ok=True)
    dump.unlink(missing_ok=True)
    env = dict(os.environ, WINEPREFIX=str(work / 'wine-prefix'), WINEARCH='win64', WINEDEBUG='-all',
               WINEDLLOVERRIDES='winemenubuilder.exe,mscoree,mshtml=d', KK_DUMP=win(dump))
    result = subprocess.run(['wine', packer, '--out', win(packed), win(args.input)],
                            env=env, capture_output=True, text=True, timeout=180)
    (work / 'pack.log').write_text(result.stdout + result.stderr)
    if result.returncode or not packed.is_file() or not dump.is_file():
        raise SystemExit(f'packer failed; see {work / "pack.log"}')
    expected = dump.read_bytes()
    trimmed = build.trim(packed.read_bytes())
    (work / 'trimmed.exe').write_bytes(trimmed)
    stream = packed_stream(trimmed, len(expected))
    harness = build_harness(nasm, work, len(expected))
    result = decode(harness, stream)
    if result.returncode or result.stdout != expected:
        (work / 'decoded.bin').write_bytes(result.stdout)
        raise SystemExit(f'decoder mismatch: status={result.returncode}; see {work}')
    print(f'PASS native decoder roundtrip: {len(expected)} bytes, SHA-256 {sha(expected)}')
    corrupt = bytearray(stream)
    corrupt[100] ^= 0x40
    try:
        result = decode(harness, corrupt)
        if result.returncode == 0 and result.stdout == expected:
            raise SystemExit('negative test failed: corrupted stream accepted')
    except subprocess.TimeoutExpired:
        pass  # Also a rejection; the child is killed and reaped by subprocess.run.
    print('PASS corruption negative test and observer entry/tail signatures')
    report = {'prepared_pe': fingerprint(args.input.read_bytes()),
              'prefilter_stream': fingerprint(expected), 'packed_pe': fingerprint(packed.read_bytes()),
              'trimmed_pe': fingerprint(trimmed), 'decoder_roundtrip': True, 'corruption_rejected': True}
    (work / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'{work / "trimmed.exe"}: {len(trimmed)} bytes, SHA-256 {sha(trimmed)}')


if __name__ == '__main__':
    main()
