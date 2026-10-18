#!/usr/bin/env python3
"""Build the size-optimized intro (no_std Rust + patched kkrunchy) and compare it with the verified build.

Steps: stage size/crate with the shared shaders and tables, build the sizecoded PE with one section per
function and static, laid out in the order of size/crate/tools/rust/sizecoded.ld, clear its export
directory and .eh_frame/.edata, build NASM 2.10.09 and the patched kkrunchy_k7 from source, pack under
Wine, drop the trailing zero padding, then compare the SHA-256 with size/expected.sha256.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SIZE = ROOT / 'size'
WORK = ROOT / '.build/size'
OUTPUT = ROOT / '.build/eidolon-size.exe'
NASM_URLS = ['https://www.nasm.us/pub/nasm/releasebuilds/2.10.09/nasm-2.10.09.tar.xz',
             'https://web.archive.org/web/2020id_/https://www.nasm.us/pub/nasm/releasebuilds/2.10.09/nasm-2.10.09.tar.xz']
NASM_SHA256 = '9ffd9f910c783ee798cf2986cec01ebeeb01ba0ecacef64d2d4bea927c41fbf2'
RUSTFLAGS = ('-C target-feature=+sse2,+sse4.1 -C jump-tables=no -Z location-detail=none -Z fmt-debug=none '
             '-Z unstable-options -C panic=immediate-abort -Z tune-cpu=nehalem -C llvm-args=-inline-threshold=20')


def step(message):
    print(f'==> {message}', flush=True)


def run(argv, cwd, env=None):
    result = subprocess.run([str(a) for a in argv], cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode:
        sys.exit(f'{argv[0]} failed:\n{result.stdout[-4000:]}\n{result.stderr[-4000:]}')
    return result.stdout


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_identity(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': sha(data)}


def input_hashes(tree):
    """Record the actual staged inputs, including an experimental link-order override."""
    inputs = {}
    for prefix, directory in (('tree', tree), ('packer', SIZE / 'packer')):
        for path in sorted(directory.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                inputs[f'{prefix}/{path.relative_to(directory)}'] = sha(path.read_bytes())
    for name in ('size/build.py', 'rust-toolchain.toml'):
        inputs[name] = sha((ROOT / name).read_bytes())
    return inputs


def stage():
    tree = WORK / 'tree'
    shutil.rmtree(tree, ignore_errors=True)
    shutil.copytree(SIZE / 'crate', tree)
    shutil.copytree(ROOT / 'shaders', tree / 'shaders')
    shutil.copytree(ROOT / '.cargo', tree / '.cargo')
    shutil.copyfile(ROOT / 'Cargo.lock', tree / 'Cargo.lock')
    for table in (ROOT / 'src/data').glob('*.bin'):
        shutil.copyfile(table, tree / 'src/data' / table.name)
    (tree / 'tools/rust/minimal-linker').chmod(0o755)
    return tree


def build_pe(tree):
    step('building the sizecoded Rust executable')
    target = WORK / 'target'
    env = dict(os.environ, CARGO_TARGET_DIR=str(target), CARGO_PROFILE_SIZECODED_OPT_LEVEL='z',
               CARGO_TARGET_I686_PC_WINDOWS_GNU_LINKER=str(tree / 'tools/rust/minimal-linker'),
               EIDOLON_COMPACT_GRAPHICS_BLOB=str(tree / 'src/data/graphics.cg29'), RUSTC_BOOTSTRAP='1',
               RUSTFLAGS=f'{RUSTFLAGS} --remap-path-prefix={tree}=/eidolon  -C link-arg=-Wl,--no-insert-timestamp '
                         f'-Z function-sections=yes -C link-arg=-Wl,-T,{tree}/tools/rust/sizecoded.ld')
    env.pop('CARGO_ENCODED_RUSTFLAGS', None)
    run(['cargo', 'build', '--target', tree / 'tools/rust/i686-pc-windows-gnu.json', '--profile', 'sizecoded',
         '--features', 'sizecoded,compact-graphics,fixed-core', '--bin', 'eidolon-runtime', '--locked', '--offline',
         '-Z', 'build-std=core,alloc', '-Z', 'json-target-spec'], tree, env)
    return (target / 'i686-pc-windows-gnu/sizecoded/eidolon-runtime.exe').read_bytes()


def prepare(data):
    """Clear the export directory and the unused .eh_frame/.edata contents before packing."""
    data = bytearray(data)
    pe = struct.unpack_from('<I', data, 60)[0]
    struct.pack_into('<II', data, pe + 24 + 96, 0, 0)
    table = pe + 24 + struct.unpack_from('<H', data, pe + 20)[0]
    for i in range(struct.unpack_from('<H', data, pe + 6)[0]):
        entry = table + i * 40
        if data[entry:entry + 8].rstrip(b'\0') in (b'.eh_fram', b'.edata'):
            size, offset = struct.unpack_from('<II', data, entry + 16)
            data[offset:offset + size] = bytes(size)
    return bytes(data)


def build_nasm():
    nasm = WORK / 'nasm-2.10.09/nasm'
    if nasm.exists():
        return nasm
    step('building NASM 2.10.09 (the packer depends on this exact version)')
    archive = WORK / 'nasm-2.10.09.tar.xz'
    for url in NASM_URLS:
        if archive.exists():
            break
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                archive.write_bytes(response.read())
        except OSError as error:
            print(f'    {url}: {error}', flush=True)
    if not archive.exists() or sha(archive.read_bytes()) != NASM_SHA256:
        sys.exit(f'{archive}: unexpected SHA-256')
    with tarfile.open(archive) as tar:
        tar.extractall(WORK, filter='data')
    run(['./configure', 'CC=gcc -std=gnu11', 'CFLAGS=-O2'], nasm.parent)
    run(['make', '-s', '-j4', 'nasm'], nasm.parent)
    return nasm


def build_packer(nasm):
    step('building the patched kkrunchy_k7 packer')
    work = WORK / 'packer'
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(SIZE / 'packer', work)
    run([nasm, '-f', 'bin', '-o', 'depack2.bin', 'depack2.asm'], work)
    run([nasm, '-f', 'rdf', '-o', 'depacker.rdf', 'depacker.asm'], work)
    run([nasm, '-f', 'win32', '-o', 'incdata.obj', 'incdata.asm', '-DPACKNAME="depacker.rdf"', '-DPACKNAME2="depack2.bin"'], work)
    run([nasm, '-f', 'win32', '-o', 'model_asm.obj', 'model_asm.asm'], work)
    for source in sorted(work.glob('*.cpp')):
        run(['clang++', '--target=i686-w64-windows-gnu', '-fms-extensions', '-fasm-blocks', '-Wno-everything',
             '-fwritable-strings', '-O2', '-DNDEBUG', '-DWIN32', '-I/usr/i686-w64-mingw32/include',
             '-c', source, '-o', source.with_suffix('.o')], work)
    objects = sorted(str(p) for p in work.glob('*.o'))
    run(['i686-w64-mingw32-g++', '-static', '-s', '-Wl,--no-insert-timestamp', *objects, 'incdata.obj',
         'model_asm.obj', '-lole32', '-lwinmm', '-o', 'kkrunchy.exe'], work)
    return work / 'kkrunchy.exe'


def pack(packer, prepared):
    step('packing')
    source, packed = WORK / 'input.exe', WORK / 'packed.exe'
    source.write_bytes(prepared)
    packed.unlink(missing_ok=True)
    win = lambda p: 'Z:' + str(p).replace('/', '\\')
    env = dict(os.environ, WINEPREFIX=str(WORK / 'wine-prefix'), WINEARCH='win64', WINEDEBUG='-all',
               WINEDLLOVERRIDES='winemenubuilder.exe,mscoree,mshtml=d')
    print(run(['wine', packer, '--out', win(packed), win(source)], WORK, env).strip().splitlines()[-1])
    return packed.read_bytes()


def trim(data):
    """Drop the zero padding after the packed data; the loader zero-fills the rest of the section."""
    data = bytearray(data.rstrip(b'\0'))
    pe = struct.unpack_from('<I', data, 60)[0]
    section = pe + 24 + struct.unpack_from('<H', data, pe + 20)[0]
    raw_offset = struct.unpack_from('<I', data, section + 20)[0]
    struct.pack_into('<I', data, section + 16, len(data) - raw_offset)
    return bytes(data)


def main():
    global WORK, OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', action='store_true',
                        help='build and record an experimental candidate without checking the accepted hash')
    parser.add_argument('--work-dir', type=Path, default=WORK,
                        help='private build directory (default: .build/size)')
    parser.add_argument('--output', type=Path, default=OUTPUT,
                        help='delivered EXE path (default: .build/eidolon-size.exe)')
    parser.add_argument('--link-order', type=Path,
                        help='use this linker script in the staged tree (requires --candidate)')
    args = parser.parse_args()
    if args.link_order and not args.candidate:
        parser.error('--link-order requires --candidate')
    WORK, OUTPUT = args.work_dir.resolve(), args.output.resolve()
    if WORK == ROOT or ROOT.is_relative_to(WORK):
        parser.error('--work-dir must not be the repository or one of its parents')
    if OUTPUT == WORK or OUTPUT.is_relative_to(WORK / 'tree') or OUTPUT.is_relative_to(WORK / 'packer'):
        parser.error('--output must be outside the disposable staging directories')
    for tool in ('cargo', 'wine', 'clang++', 'i686-w64-mingw32-g++', 'gcc', 'make'):
        if not shutil.which(tool):
            sys.exit(f'missing tool: {tool}')
    WORK.mkdir(parents=True, exist_ok=True)
    tree = stage()
    if args.link_order:
        shutil.copyfile(args.link_order, tree / 'tools/rust/sizecoded.ld')
    inputs = input_hashes(tree)
    unprepared = build_pe(tree)
    (WORK / 'unprepared.exe').write_bytes(unprepared)
    prepared = prepare(unprepared)
    nasm = build_nasm()
    packer = build_packer(nasm)
    packed = trim(pack(packer, prepared))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(packed)
    actual = sha(packed)
    expected = None if args.candidate else (SIZE / 'expected.sha256').read_text().split()[0]
    status = 'CANDIDATE' if args.candidate else ('EXPECTED_HASH_MATCH' if actual == expected else 'HASH_MISMATCH')
    report = {
        'schema': 'eidolon-size-build-1', 'status': status,
        'media_capture_performed': False, 'expected_sha256': expected,
        'source_sha256': inputs, 'rustflags': RUSTFLAGS,
        'unprepared': file_identity(WORK / 'unprepared.exe'),
        'prepared': file_identity(WORK / 'input.exe'),
        'packer': file_identity(packer), 'nasm': file_identity(nasm),
        'delivered': file_identity(OUTPUT),
        'tool_versions': {tool: run([tool, '--version'], ROOT).splitlines()[0]
                          for tool in ('rustc', 'cargo', 'clang++', 'i686-w64-mingw32-g++', 'wine')},
    }
    (WORK / 'build.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    displayed = OUTPUT.relative_to(ROOT) if OUTPUT.is_relative_to(ROOT) else OUTPUT
    print(f'{displayed}: {len(packed)} bytes (original: 60928 bytes)')
    if args.candidate:
        print(f'CANDIDATE size: SHA-256 {actual}; media verification required')
        return
    if actual == expected:
        print(f'PASS size: identical to the verified build, SHA-256 {actual}')
    else:
        sys.exit(f'FAIL size: SHA-256 {actual}, expected {expected}; a different compiler or packer version '
                 'changes the bytes, so this build is not the verified one')


if __name__ == '__main__':
    main()
