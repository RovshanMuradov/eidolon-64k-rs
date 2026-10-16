#!/usr/bin/env python3
"""Compare Rust ABI constants against independent MinGW headers, without executing PE code."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ['EIDOLON_DATA']) / 'builds/T22/abi'
TYPES = {
    'WindowClass': ('WNDCLASSA', {'style': 'style', 'procedure': 'lpfnWndProc', 'class_extra': 'cbClsExtra',
        'window_extra': 'cbWndExtra', 'instance': 'hInstance', 'icon': 'hIcon', 'cursor': 'hCursor',
        'background': 'hbrBackground', 'menu': 'lpszMenuName', 'name': 'lpszClassName'}),
    'Message': ('MSG', {'window': 'hwnd', 'message': 'message', 'wparam': 'wParam', 'lparam': 'lParam',
        'time': 'time', 'x': 'pt.x', 'y': 'pt.y'}),
    'PixelFormat': ('PIXELFORMATDESCRIPTOR', {'size': 'nSize', 'version': 'nVersion', 'flags': 'dwFlags',
        'pixel_type': 'iPixelType', 'color_bits': 'cColorBits', 'accum_alpha': 'cAccumAlphaBits',
        'depth_bits': 'cDepthBits', 'layer_type': 'iLayerType', 'layer_mask': 'dwLayerMask',
        'visible_mask': 'dwVisibleMask', 'damage_mask': 'dwDamageMask'}),
    'WaveFormat': ('WAVEFORMATEX', {'tag': 'wFormatTag', 'channels': 'nChannels', 'rate': 'nSamplesPerSec',
        'bytes_per_second': 'nAvgBytesPerSec', 'block_align': 'nBlockAlign', 'bits': 'wBitsPerSample', 'extra': 'cbSize'}),
    'WaveHeader': ('WAVEHDR', {'data': 'lpData', 'bytes': 'dwBufferLength', 'recorded': 'dwBytesRecorded',
        'user': 'dwUser', 'flags': 'dwFlags', 'loops': 'dwLoops', 'next': 'lpNext', 'reserved': 'reserved'}),
    'MultimediaTime': ('MMTIME', {'kind': 'wType', 'value': 'u'}),
}


def run(*args):
    subprocess.run([str(a) for a in args], cwd=ROOT, check=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    temporary = OUT / 'tmp'
    temporary.mkdir(exist_ok=True)
    os.environ['TMPDIR'] = str(temporary)
    rust, c, labels = [], [], []
    for name, (native, fields) in TYPES.items():
        labels.append(name + '.sizeof')
        rust.append(f'size_of::<windows::{name}>() as u32')
        c.append(f'sizeof({native})')
        for field, native_field in fields.items():
            labels.append(name + '.' + field)
            rust.append(f'std::mem::offset_of!(windows::{name}, {field}) as u32')
            c.append(f'offsetof({native}, {native_field})')
    (OUT / 'rust.rs').write_text(f'#[path="{ROOT}/src/windows.rs"] mod windows;\n'
        '#[used]\n#[no_mangle]\n#[link_section=".eidabi"]\n'
        f'pub static ABI: [u32; {len(rust)}] = [{", ".join(rust)}];\n'
        '#[used]\n#[no_mangle]\n#[link_section=".eidpfd"]\n'
        'pub static PFD: windows::PixelFormat = windows::PixelFormat::native();\n')
    (OUT / 'native.c').write_text('#include <windows.h>\n#include <mmsystem.h>\n#include <stddef.h>\n'
        '__attribute__((section(".eidabi"),used)) const unsigned int ABI[] = {' + ','.join(c) + '};\n')
    run('rustc', '--edition=2021', '--target=i686-pc-windows-gnu', '--crate-type=lib', '--emit=obj',
        '-Adead_code', OUT / 'rust.rs', '-o', OUT / 'rust.o')
    run('i686-w64-mingw32-gcc', '-c', OUT / 'native.c', '-o', OUT / 'native.o')
    for name in ('rust', 'native'):
        run('objcopy', '-O', 'binary', '--only-section=.eidabi', OUT / (name + '.o'), OUT / (name + '.bin'))
    size = len(labels) * 4
    rust_bytes, native_bytes = [(OUT / (name + '.bin')).read_bytes()[:size] for name in ('rust', 'native')]
    assert len(rust_bytes) == size and rust_bytes == native_bytes
    run('objcopy', '-O', 'binary', '--only-section=.eidpfd', OUT / 'rust.o', OUT / 'pfd.bin')
    source_path = Path(os.environ['EIDOLON_DATA']) / 'reverse/confirmed-debug/postfix-00400000.bin'
    source = source_path.read_bytes()
    pfd = (OUT / 'pfd.bin').read_bytes()[:40]
    assert pfd == source[0x40c30:0x40c58]
    data = {'schema': 'eidolon-windows-abi-v1', 'target': 'i686-pc-windows-gnu',
            'method': 'object-section comparison; target code not executed',
            'constants': dict(zip(labels, struct.unpack('<' + 'I' * len(labels), rust_bytes))),
            'constants_sha256': hashlib.sha256(rust_bytes).hexdigest(),
            'native_pfd': {'address': '0x440c30', 'bytes_hex': pfd.hex(),
                           'source_sha256': hashlib.sha256(source).hexdigest(),
                           'source': str(source_path)}}
    (ROOT / 'artifacts/rust/engine/windows-abi.json').write_text(json.dumps(data, indent=2) + '\n')
    print(f'WINDOWS_ABI_MATCHES_MINGW constants={len(labels)}')


if __name__ == '__main__':
    main()
