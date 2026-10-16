#!/usr/bin/env python3
"""Isolated D9 build; original B/D7 source and outputs are immutable inputs."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    temporary = Path('/tmp/opencode/eidolon/T11/build-tmp')
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ['TMPDIR'] = str(temporary)
    original_path = Path('artifacts/reference/proxy-b-g1-20261016.json')
    original = json.loads(original_path.read_text())['build']
    old = Path(original['build_directory'])
    for name, digest in original['sources'].items():
        assert sha(name) == digest, name
    for name, digest in original['outputs'].items():
        assert sha(old / name) == digest, name
    compiler = subprocess.check_output(['i686-w64-mingw32-gcc', '--version'], text=True).splitlines()[0]
    assert compiler == original['compiler']
    for backend in original['backends'].values():
        assert sha(backend['path']) == backend['sha256']
    sources = {str(p): sha(p) for p in sorted(Path('tools/capture/proxy-b-compat').glob('*')) if p.is_file()}
    identity = dict(sources=sources, original_manifest_sha256=sha(original_path), compiler=compiler,
                    flags=original['flags'], original_sources=original['sources'], backends=original['backends'])
    build_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    out = Path(os.environ['EIDOLON_ROOT']) / '.tools/capture/B-compat' / build_id
    if (out / 'build.json').exists():
        for name, digest in json.loads((out / 'build.json').read_text())['outputs'].items():
            assert sha(out / name) == digest, name
        print(out)
        return
    out.mkdir(parents=True, exist_ok=False)
    for name in original['outputs']:
        if not name.endswith(('.dll', '.exe')):
            target = out / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(old / name, target)
    wrappers = ['.text']
    for api, argbytes in {'shader': 12, 'use': 4, 'rect': 16, 'teximage': 20}.items():
        wrappers += [f'.globl _compat_{api}', f'_compat_{api}:',
                     'pushfl', 'pushal', 'movl %esp,%ebp', 'subl $528,%esp',
                     'andl $-16,%esp', 'fxsave (%esp)', 'subl $16,%esp',
                     'leal 36(%ebp),%eax', 'movl %eax,(%esp)', f'call _compat_core_{api}',
                     'movl %eax,28(%ebp)', 'addl $16,%esp', 'fxrstor (%esp)',
                     'movl %ebp,%esp', 'popal', 'popfl', f'ret ${argbytes}']
    (out / 'compat.S').write_text('\n'.join(wrappers) + '\n')
    commands = []
    exports = runpy.run_path('tools/capture/proxy-b/build.py')['exports']
    for command in original['commands']:
        command = [arg.replace(str(old), str(out)) for arg in command]
        if 'tools/capture/proxy-b/core.c' in command:
            command[command.index('tools/capture/proxy-b/core.c')] = 'tools/capture/proxy-b-compat/core.c'
            command.insert(1, str(out / 'compat.S'))
        subprocess.run(command, check=True)
        commands.append(command)
    for name, backend in original['backends'].items():
        actual = exports(out / f'{name}.dll')
        assert all(actual[k] == v for k, v in exports(backend['path']).items())
    for name in dict(original['sources'], **sources):
        target = out / 'source-snapshot' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(name, target)
    manifest = dict(identity, build_id=build_id, build_directory=str(out), commands=commands,
                    export_maps_equal=True,
                    outputs={str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*')) if p.is_file()})
    (out / 'build.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(out)


if __name__ == '__main__':
    main()
