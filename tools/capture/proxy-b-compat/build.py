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
    apis = [('eidolon', api, size) for api, size in {
        'gettick':0,'timegettime':0,'qpc':4,'qpf':4,'position':12,'swap':4,
        'create_thread':24,'wave_open':24,'wave_prepare':12,'wave_write':12,
        'lookup':8,'wgl_lookup':4}.items()]
    apis += [('compat', api, size) for api, size in
             {'shader':12,'use':4,'rect':16,'teximage':20,'volume':40}.items()]
    save = ['pushfl','pushal','movl %esp,%ebp','subl $528,%esp','andl $-16,%esp',
            'movl %esp,%edi','xorl %eax,%eax','movl $128,%ecx','cld','rep stosl',
            'fxsave (%esp)','subl $32,%esp']
    restore = ['addl $32,%esp','fxrstor (%esp)','movl %ebp,%esp','popal','popfl']
    for number, (prefix, api, argbytes) in enumerate(apis):
        core = 'core_' if prefix == 'eidolon' else 'compat_core_'
        wrappers += [f'.globl _{prefix}_{api}',f'_{prefix}_{api}:',*save,
                     'movl %ebp,(%esp)','leal 32(%esp),%eax','movl %eax,4(%esp)',
                     f'movl ${number},8(%esp)',f'movl ${argbytes},12(%esp)',
                     'call _stage_canary_begin','leal 36(%ebp),%eax','movl %eax,(%esp)',
                     f'call _{core}{api}','movl %eax,(%esp)','call _stage_canary_arm',
                     'movl %eax,28(%ebp)','movl $_stage_return,36(%ebp)',*restore,f'ret ${argbytes}']
    wrappers += ['_stage_return:','pushl $0',*save,'movl %ebp,(%esp)',
                 'leal 32(%esp),%eax','movl %eax,4(%esp)','call _stage_canary_return',
                  'movl %eax,36(%ebp)',*restore,'ret']
    for number, name in enumerate(('bootstrap','interior','synth_return')):
        wrappers += [f'.globl _native_{name}', f'_native_{name}:','pushl $0',*save,
                     'movl %ebp,(%esp)','leal 32(%esp),%eax','movl %eax,4(%esp)',
                     f'movl ${number},8(%esp)','call _native_resumed',
                     'movl %eax,36(%ebp)',*restore,'ret']
    for number, (name,displaced,next_pc) in enumerate((
            ('initialize','0x0f,0x28,0x46,0x40,0x0f,0x29,0x46,0x50',0x405446),
            ('before','0x0f,0x28,0x86,0x90,0x01,0x00,0x00',0x405645),
            ('after','0x0f,0x28,0x07,0x66,0x0f,0x58,0x46,0x60',0x405746))):
        wrappers += [f'.globl _node_site_{name}', f'_node_site_{name}:',*save,
                     'movl %ebp,(%esp)','leal 32(%esp),%eax','movl %eax,4(%esp)',
                     f'movl ${number},8(%esp)','call _node_probe',*restore,*save,
                     'movl %ebp,(%esp)','leal 32(%esp),%eax','movl %eax,4(%esp)',
                     f'movl ${number},8(%esp)','call _node_return',*restore,
                     '.byte '+displaced,f'pushl ${next_pc}','ret']
    (out / 'compat.S').write_text('\n'.join(wrappers) + '\n')
    commands = []
    exports = runpy.run_path('tools/capture/proxy-b/build.py')['exports']
    for command in original['commands']:
        command = [arg.replace(str(old), str(out)) for arg in command]
        if 'tools/capture/proxy-b/core.c' in command:
            command[command.index('tools/capture/proxy-b/core.c')] = 'tools/capture/proxy-b-compat/core.c'
            command.insert(1, str(out / 'compat.S'))
            command.remove(str(out / 'opengl32/wrappers.S'))
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
