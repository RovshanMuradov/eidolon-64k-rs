#!/usr/bin/env python3
"""Capture frame and PCM hashes of the original Eidolon EXE on this machine's GPU (Linux + Wine).

Builds the research capture proxies (opengl32/winmm, tools/capture/proxy-b*) against this machine's
Wine, runs the original under a controlled clock (frame n at sample 735*n) and writes
<out>/frames.sha256 and <out>/pcm.sha256 in the same format as verify/.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import urllib.request
import zipfile

import headless

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_PATH = 'parties/2017/revision17/pc_64k_intro/eidolon_-_poo-brain_-_revision2017_64k_-_rc4.zip'
ARCHIVE_URLS = [f'https://ftp.scene.org/pub/{ARCHIVE_PATH}', f'https://archive.scene.org/pub/{ARCHIVE_PATH}',
                f'https://files.scene.org/get/{ARCHIVE_PATH}']
ARCHIVE_SHA256 = '11104969a59ef85d1f7ed416abfb01a377834504369902a735eb1a2fd1e40008'
EXE_NAME = 'Eidolon - Poo-Brain (native).exe'
EXE_SHA256 = '376b476c358a969da7d5d45c091355520453086ee8cd22625fdbb4fa3a9fd6be'
FRAMES = 27000
FLAGS = ['-O2', '-Wall', '-Wextra', '-Werror', '-Wl,--no-insert-timestamp']
SAVE = ['pushfl', 'pushal', 'movl %esp,%ebp', 'subl $528,%esp', 'andl $-16,%esp', 'movl %esp,%edi',
        'xorl %eax,%eax', 'movl $128,%ecx', 'cld', 'rep stosl', 'fxsave (%esp)', 'subl $32,%esp']
RESTORE = ['addl $32,%esp', 'fxrstor (%esp)', 'movl %ebp,%esp', 'popal', 'popfl']


def sha(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def step(message):
    print(f'==> {message}', flush=True)


def original_exe(work, archive):
    for url in ARCHIVE_URLS:
        if archive.exists():
            break
        step(f'downloading {url}')
        try:
            with urllib.request.urlopen(url, timeout=300) as response:
                archive.write_bytes(response.read())
        except OSError as error:
            print(f'    {error}', flush=True)
    if not archive.exists() or sha(archive) != ARCHIVE_SHA256:
        sys.exit(f'{archive}: unexpected SHA-256; download the rc4 archive from scene.org')
    exe = work / 'stage' / EXE_NAME
    exe.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        exe.write_bytes(z.read(EXE_NAME))
    assert sha(exe) == EXE_SHA256
    return exe


def sample_bank():
    """The system General MIDI bank the original reads; shared by make reference and make run-size."""
    data = ROOT / '.build/data'
    bank = data / 'reference/dependencies/gm.dls'
    if not bank.exists():
        step('downloading gm.dls (Microsoft DirectX redistributable via web.archive.org)')
        subprocess.run([sys.executable, str(ROOT / 'tools/capture/dependencies/gm_dls.py'), 'acquire'],
                       env=dict(os.environ, EIDOLON_DATA=str(data)), check=True, stdout=subprocess.DEVNULL)
    return bank


def install_bank(prefix, bank):
    for arch in ('system32', 'syswow64'):
        target = Path(prefix) / f'drive_c/windows/{arch}/drivers/gm.dls'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bank, target)


def wine_backends():
    """Directory of Wine's 32-bit builtin DLLs; the proxies mirror their export tables."""
    wine = Path(shutil.which('wine')).resolve()
    candidates = [wine.parent.parent / 'lib/wine/i386-windows', wine.parent.parent / 'lib32/wine/i386-windows',
                  *Path('/usr/lib').glob('*/wine/i386-windows'), Path('/usr/lib/wine/i386-windows'),
                  *Path('/opt').glob('wine*/lib/wine/i386-windows')]
    for directory in candidates:
        if (directory / 'opengl32.dll').exists() and (directory / 'winmm.dll').exists():
            return directory
    sys.exit('Wine 32-bit builtin DLLs (i386-windows/opengl32.dll) not found; install Wine with 32-bit support')


def build_proxies(work):
    """Same sources and generated stubs as tools/capture/proxy-b{,-compat}/build.py, without host pins."""
    exports = runpy.run_path(str(ROOT / 'tools/capture/proxy-b/build.py'))['exports']
    # Relative source paths from the repository root, as in the research build: __FILE__ strings end up in the DLLs.
    source, compat = Path('tools/capture/proxy-b'), Path('tools/capture/proxy-b-compat')
    out = work / 'build'
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    backends = wine_backends()
    step(f'building capture proxies against {backends}')
    wrappers = ['.text']
    apis = [('eidolon', api, size) for api, size in {
        'gettick': 0, 'timegettime': 0, 'qpc': 4, 'qpf': 4, 'position': 12, 'swap': 4, 'create_thread': 24,
        'wave_open': 24, 'wave_prepare': 12, 'wave_write': 12, 'lookup': 8, 'wgl_lookup': 4}.items()]
    apis += [('compat', api, size) for api, size in {'shader': 12, 'use': 4, 'rect': 16, 'teximage': 20, 'volume': 40}.items()]
    for number, (prefix, api, argbytes) in enumerate(apis):
        core = 'core_' if prefix == 'eidolon' else 'compat_core_'
        wrappers += [f'.globl _{prefix}_{api}', f'_{prefix}_{api}:', *SAVE,
                     'movl %ebp,(%esp)', 'leal 32(%esp),%eax', 'movl %eax,4(%esp)',
                     f'movl ${number},8(%esp)', f'movl ${argbytes},12(%esp)',
                     'call _stage_canary_begin', 'leal 36(%ebp),%eax', 'movl %eax,(%esp)',
                     f'call _{core}{api}', 'movl %eax,(%esp)', 'call _stage_canary_arm',
                     'movl %eax,28(%ebp)', 'movl $_stage_return,36(%ebp)', *RESTORE, f'ret ${argbytes}']
    wrappers += ['_stage_return:', 'pushl $0', *SAVE, 'movl %ebp,(%esp)', 'leal 32(%esp),%eax', 'movl %eax,4(%esp)',
                 'call _stage_canary_return', 'movl %eax,36(%ebp)', *RESTORE, 'ret']
    for number, name in enumerate(('bootstrap', 'interior', 'synth_return')):
        wrappers += [f'.globl _native_{name}', f'_native_{name}:', 'pushl $0', *SAVE, 'movl %ebp,(%esp)',
                     'leal 32(%esp),%eax', 'movl %eax,4(%esp)', f'movl ${number},8(%esp)', 'call _native_resumed',
                     'movl %eax,36(%ebp)', *RESTORE, 'ret']
    wrappers += ['.globl _full_exit', '_full_exit:', *SAVE, 'movl %ebp,(%esp)', 'leal 32(%esp),%eax', 'movl %eax,4(%esp)',
                 'call _full_exit_observe', *RESTORE, *SAVE, 'movl %ebp,(%esp)', 'leal 32(%esp),%eax',
                 'movl %eax,4(%esp)', 'call _full_exit_restored', *RESTORE, 'jmp *_full_exit_target']
    for number, (name, displaced, next_pc) in enumerate((
            ('initialize', '0x0f,0x28,0x46,0x40,0x0f,0x29,0x46,0x50', 0x405446),
            ('before', '0x0f,0x28,0x86,0x90,0x01,0x00,0x00', 0x405645),
            ('after', '0x0f,0x28,0x07,0x66,0x0f,0x58,0x46,0x60', 0x405746))):
        wrappers += [f'.globl _node_site_{name}', f'_node_site_{name}:', *SAVE, 'movl %ebp,(%esp)',
                     'leal 32(%esp),%eax', 'movl %eax,4(%esp)', f'movl ${number},8(%esp)', 'call _node_probe', *RESTORE,
                     *SAVE, 'movl %ebp,(%esp)', 'leal 32(%esp),%eax', 'movl %eax,4(%esp)', f'movl ${number},8(%esp)',
                     'call _node_return', *RESTORE, '.byte ' + displaced, f'pushl ${next_pc}', 'ret']
    (out / 'compat.S').write_text('\n'.join(wrappers) + '\n')
    for name in ('opengl32', 'winmm'):
        entries = exports(backends / f'{name}.dll')
        directory = out / name
        directory.mkdir()
        definitions, assembly, ordinals = [f'LIBRARY {name}', 'EXPORTS'], ['.text'], []
        for i, (ordinal, names) in enumerate(entries.items()):
            ordinals.append(ordinal)
            for entry in names or [f'ordinal_{ordinal}']:
                definitions.append(f'{entry}=eidolon_stub_{i} @{ordinal}' + ('' if names else ' NONAME'))
            assembly += [f'.globl _eidolon_stub_{i}', f'_eidolon_stub_{i}:', f'pushl ${i}', 'jmp _eidolon_dispatch']
        definitions.append(f'EidolonProbeBackend=EidolonProbeBackend@0 @{max(entries) + 1}')
        assembly += ['_eidolon_dispatch:', 'pushfl', 'pushal', 'movl %esp,%ebp', 'subl $528,%esp', 'andl $-16,%esp',
                     'fxsave (%esp)', 'subl $16,%esp', 'movl 36(%ebp),%eax', 'movl %eax,(%esp)', 'call _eidolon_resolve',
                     'movl %eax,36(%ebp)', 'addl $16,%esp', 'fxrstor (%esp)', 'movl %ebp,%esp', 'popal', 'popfl', 'ret']
        (directory / 'proxy.def').write_text('\n'.join(definitions) + '\n')
        (directory / 'forward.S').write_text('\n'.join(assembly) + '\n')
        symbol = 'wglGetProcAddress' if name == 'opengl32' else 'timeGetTime'
        (directory / 'exports.h').write_text(
            f'#define DLL_NAME "{name}.dll"\n#define DLL_WNAME L"{name}.dll"\n'
            f'#define CANARY_SYMBOL "{symbol}"\n#define EXPORT_COUNT {len(entries)}\n'
            'static const unsigned short export_ordinals[] = {' + ','.join(map(str, ordinals)) + '};\n')
        extra = ([str(out / 'compat.S')], ['-DHAS_BOOTSTRAP', str(source / 'bootstrap.c'), str(compat / 'core.c')]) \
            if name == 'opengl32' else ([], [])
        subprocess.run(['i686-w64-mingw32-gcc', *extra[0], *FLAGS, '-shared', *extra[1], '-I', str(directory),
                        str(source / 'proxy.c'), str(directory / 'forward.S'), str(directory / 'proxy.def'),
                        '-ladvapi32', '-o', str(out / f'{name}.dll')], check=True, cwd=ROOT)
        actual = exports(out / f'{name}.dll')
        assert all(actual[k] == v for k, v in entries.items()), f'{name}: export table mismatch'
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=ROOT / 'eidolon_-_poo-brain_-_revision2017_64k_-_rc4.zip')
    parser.add_argument('--work', type=Path, default=ROOT / '.build/reference')
    parser.add_argument('--out', type=Path, default=ROOT / 'verify/local')
    args = parser.parse_args()
    headless.require_tools('wine', 'wineserver', 'gamescope', 'pactl', 'i686-w64-mingw32-gcc', 'bsdtar', 'openssl')
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    exe = original_exe(work, args.archive)
    bank = sample_bank()
    build = build_proxies(work)
    for name in ('opengl32.dll', 'winmm.dll'):
        shutil.copyfile(build / name, exe.parent / name)

    prefix = work / 'prefix'
    shutil.rmtree(prefix, ignore_errors=True)
    step('creating a fresh Wine prefix with gm.dls installed')
    headless.prepare_prefix(prefix)
    install_bank(prefix, bank)

    output = work / 'output'
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir()
    (output / 'retention.txt').write_text('')  # hashes only; no raw frames are kept
    env = dict(WINEDLLOVERRIDES='opengl32,winmm=n,b;' + headless.OVERRIDES,
               EIDOLON_B_LOG=headless.windows_path(output / 'backend.jsonl'), EIDOLON_B_BOOTSTRAP='capture-probe',
               EIDOLON_B_OUTPUT=headless.windows_path(output), EIDOLON_B_FRAMES='3', EIDOLON_B_COMPAT='450-compatibility',
               EIDOLON_B_RETENTION=headless.windows_path(output / 'retention.txt'), EIDOLON_B_FULL=str(FRAMES),
               PULSE_SINK='eidolon_reference', XDG_CACHE_HOME=str(work / 'cache'),
               __GL_SHADER_DISK_CACHE_PATH=str(work / 'cache/nvidia'))
    sink = subprocess.check_output(['pactl', 'load-module', 'module-null-sink', 'sink_name=eidolon_reference',
                                    'rate=44100', 'channels=2'], text=True).strip()
    step(f'running the original with a controlled clock ({FRAMES} frames, about 1-2 hours); log: {work / "wine.log"}')
    try:
        code = headless.run(exe, [], prefix, env, timeout=6 * 3600, log=work / 'wine.log')
    finally:
        subprocess.run(['pactl', 'unload-module', sink], check=False)

    hashes, failure = {}, None
    log = output / 'backend.jsonl'
    if log.exists():
        with log.open() as stream:
            for line in stream:
                if '"pre_present"' in line or '"failure"' in line:
                    event = json.loads(line)
                    if event['event'] == 'pre_present':
                        hashes[event['n']] = event['sha256']
                    elif event['event'] == 'failure':
                        failure = event
    if code or failure or sorted(hashes) != list(range(FRAMES)) or not (output / 'pcm.f32le').exists():
        sys.exit(f'capture failed: exit={code} frames={len(hashes)} failure={failure}; see {work / "wine.log"} and {log}')
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'frames.sha256').write_text(''.join(f'{n:05d} {hashes[n]}\n' for n in range(FRAMES)))
    (args.out / 'pcm.sha256').write_text(sha(output / 'pcm.f32le') + '\n')
    shutil.rmtree(output)  # backend log and PCM are several GB; only the hashes are kept
    step(f'reference written to {args.out}')


if __name__ == '__main__':
    main()
