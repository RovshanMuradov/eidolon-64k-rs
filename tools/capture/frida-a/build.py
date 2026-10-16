#!/usr/bin/env python3
"""Content-addressed isolated A build; B sources and artifacts remain immutable."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    temporary=Path('/tmp/opencode/eidolon/T2/build-tmp');temporary.mkdir(parents=True,exist_ok=True)
    os.environ['TMPDIR']=str(temporary)
    source=Path('tools/capture/frida-a')
    compiler=subprocess.check_output(['i686-w64-mingw32-gcc','--version'],text=True).splitlines()[0]
    inputs=[p for p in source.iterdir() if p.is_file()]+[Path('tools/capture/proxy-b/core.c')]
    identity={'compiler':compiler,'sources':{str(p):sha(p) for p in sorted(inputs)},
              'flags':['-O2','-Wall','-Wextra','-Werror','-Wl,--no-insert-timestamp']}
    build_id=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    out=Path(os.environ['EIDOLON_ROOT'])/'.tools/capture/A'/build_id
    out.mkdir(parents=True,exist_ok=True)
    wrappers=['.text']
    for api,argbytes in {'gettick':0,'timegettime':0,'qpc':4,'qpf':4,'position':12,
            'swap':4,'create_thread':24,'wave_open':24,'wave_prepare':12,
            'wave_write':12,'lookup':8,'wgl_lookup':4}.items():
        core='swap_a' if api=='swap' else api
        wrappers += [f'.globl _eidolon_{api}',f'_eidolon_{api}:','pushfl','pushal',
            'movl %esp,%ebp','subl $528,%esp','andl $-16,%esp','fxsave (%esp)',
            'subl $16,%esp','leal 36(%ebp),%eax','movl %eax,(%esp)',f'call _core_{core}',
            'movl %eax,28(%ebp)','addl $16,%esp','fxrstor (%esp)','movl %ebp,%esp',
            'popal','popfl',f'ret ${argbytes}']
    (out/'wrappers.S').write_text('\n'.join(wrappers)+'\n')
    (out/'helper.def').write_text('LIBRARY eidolon-a\nEXPORTS\nEidolonInitialize=EidolonInitialize@4\n')
    commands=[['i686-w64-mingw32-gcc',*identity['flags'],'-shared',str(source/'helper.c'),
               str(out/'wrappers.S'),str(out/'helper.def'),'-ladvapi32','-o',str(out/'eidolon-a.dll')],
              ['i686-w64-mingw32-gcc',*identity['flags'],str(source/'launcher.c'),'-o',str(out/'launcher.exe')]]
    for command in commands: subprocess.run(command,check=True)
    manifest=dict(identity,build_id=build_id,commands=commands,
                  outputs={p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file() and p.name!='build.json'})
    (out/'build.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(out)

if __name__=='__main__': main()
