#!/usr/bin/env python3
"""A isolated, bounded native diagnostic; never declares G1 or reference PASS."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import time
import threading
import frida
from inject import inject

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as file:
        for block in iter(lambda:file.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def native_pid(stage,prefix):
    for path in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            args=path.read_bytes().split(b'\0')
            if args and args[0].decode(errors='replace')==str(stage):
                if f'WINEPREFIX={prefix}'.encode() in (path.parent/'environ').read_bytes().split(b'\0'):
                    return int(path.parent.name)
        except (PermissionError,FileNotFoundError,ProcessLookupError): pass
    return None

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--frames',type=int,default=3)
    parser.add_argument('--bad-fingerprint',action='store_true')
    parser.add_argument('--invalid-helper',action='store_true')
    args=parser.parse_args()
    assert re.fullmatch(r'[a-zA-Z0-9_-]+',args.run_id) and 1<=args.frames<=600
    root=Path(os.environ['EIDOLON_ROOT']);data_root=Path(os.environ['EIDOLON_DATA'])
    used=sum(p.stat().st_size for p in data_root.rglob('*') if p.is_file() and not p.is_symlink())
    reserve=159716352+args.frames*1920*1080*4+50_000_000
    assert used+reserve<30_000_000_000 and shutil.disk_usage(data_root).free>reserve,'storage budget'
    os.environ['TMPDIR']='/tmp/opencode/eidolon/T2/build-tmp'
    Path(os.environ['TMPDIR']).mkdir(parents=True,exist_ok=True)
    data=data_root/'reference'/args.run_id;data.mkdir(parents=True,exist_ok=False)
    subprocess.run(['python','tools/capture/prepare-native.py'],check=True)
    build=Path(subprocess.check_output(['python','tools/capture/frida-a/build.py'],text=True).strip())
    stage=Path('/tmp/opencode/eidolon/T2/a-demo')/args.run_id;stage.mkdir(parents=True,exist_ok=False)
    original=json.loads(Path('artifacts/reference/wine-smoke-manifest.json').read_text())['input']
    native=stage/original['exe'];shutil.copyfile(Path('/tmp/opencode/eidolon/T2/input')/native.name,native)
    assert sha(native)==original['exe_sha256']
    assert not any(p.name.lower() in ('opengl32.dll','winmm.dll') for p in stage.iterdir())
    prefix=Path('/tmp/opencode/eidolon/T2/prefix')
    baseline={str(p.relative_to(prefix)):sha(p) for p in [prefix/f for f in
        ('system.reg','user.reg','userdef.reg','drive_c/windows/system32/drivers/gm.dls','drive_c/windows/syswow64/drivers/gm.dls')]}
    frozen=json.loads(Path('artifacts/reference/proxy-b-g1-20261016.json').read_text())
    b_evidence={name:sha(data_root/name) for name in frozen['evidence']}
    assert b_evidence==frozen['evidence'],'immutable B evidence differs'
    env=dict(os.environ,AGENT='T2',WINE_TIMEOUT='300',WINE_W='1920',WINE_H='1080',
             WINEDLLOVERRIDES='opengl32,winmm=b;winemenubuilder.exe,mscoree,mshtml=d',
             WINEDEBUG='-all,+loaddll',EIDOLON_A_LOG='Z:'+str(data/'events.jsonl'),
             EIDOLON_A_OUTPUT='Z:'+str(data),EIDOLON_A_FRAMES=str(args.frames),
             XDG_CACHE_HOME='/tmp/opencode/eidolon/T2/cache',
             __GL_SHADER_DISK_CACHE_PATH='/tmp/opencode/eidolon/T2/cache/nvidia')
    for name in list(env):
        if name in ('DISPLAY','WAYLAND_DISPLAY') or name.startswith('EIDOLON_B_'):env.pop(name)
    sink=subprocess.check_output(['pactl','load-module','module-null-sink',
         'sink_name=eidolon_T2_A','rate=44100','channels=2'],text=True).strip()
    env['PULSE_SINK']='eidolon_T2_A'
    command=['bash','tools/run','tools/wine-headless',str(build/'launcher.exe'),str(native),
             'Z:'+str(data/'rendezvous.json')]
    started=datetime.now(timezone.utc).isoformat();control_error=None;injection=None;runner=None
    try:
        with (data/'runner.log').open('wb') as log:
            runner=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            deadline=time.monotonic()+65
            while time.monotonic()<deadline and runner.poll() is None:
                ready=data/'rendezvous.json'
                if ready.exists():
                    try: config=json.loads(ready.read_text())
                    except json.JSONDecodeError: time.sleep(.1);continue
                    pid=native_pid(native,prefix)
                    if pid: break
                time.sleep(.1)
            else: config=None;pid=None
            if not config or not pid: control_error='post_fixup_rendezvous_or_host_pid_missing'
            else:
                text=(data/'runner.log').read_text(errors='replace')
                config.update(modules=['0x'+v for v in re.findall(r'A_MODULE base=([0-9a-fA-F]+)',text)],
                              helper='Z:'+str(build/('absent.dll' if args.invalid_helper else 'eidolon-a.dll')),
                              badFingerprint=args.bad_fingerprint)
                (data/'inject-config.json').write_text(json.dumps(config,indent=2)+'\n')
                # Attach from the target's ancestor, not a sibling subprocess:
                # Yama ptrace_scope=1 otherwise rejects /proc/PID/mem access.
                access={'injector_pid':os.getpid(),'target_pid':pid,
                        'ptrace_scope':Path('/proc/sys/kernel/yama/ptrace_scope').read_text().strip(),
                        'target_status':Path(f'/proc/{pid}/status').read_text()}
                try:
                    with open(f'/proc/{pid}/mem','rb') as memory:
                        memory.seek(config['site']);access['ancestor_read_bytes']=memory.read(9).hex()
                except OSError as exc:access['ancestor_read_error']=str(exc)
                (data/'attach-access.json').write_text(json.dumps(access,indent=2)+'\n')
                outcome=[]
                worker=threading.Thread(target=lambda:outcome.append(inject(pid,config,data/'injection.json')),daemon=True)
                worker.start();worker.join(45)
                if worker.is_alive():control_error='Frida_attach_injection_timeout_45s'
                elif outcome:injection=outcome[0]
            result=runner.wait(timeout=325)
    finally:
        if runner and runner.poll() is None:
            os.killpg(runner.pid,signal.SIGTERM)
            runner.wait(timeout=20)
        subprocess.run(['pactl','unload-module',sink],check=True)
    events=[json.loads(s) for s in (data/'events.jsonl').read_text().splitlines()] if (data/'events.jsonl').exists() else []
    failure=next((e for e in events if e['event']=='failure'),None)
    injection_observation=json.loads((data/'injection.json').read_text()) if (data/'injection.json').exists() else None
    if not failure and injection_observation and injection_observation['status']=='failed':failure=injection_observation
    planned=any(e['event']=='planned_partial_stop' for e in events)
    for name,digest in b_evidence.items():assert sha(data_root/name)==digest,'B changed during A'
    manifest={'kind':'frida-A-G1-diagnostic','run_id':args.run_id,'reference_eligible':False,
        'diagnostic_incomplete':True,'status':'partial_acquisition' if planned and result==0 else 'G1_failed',
        'first_failed_check':control_error or failure or (None if planned else 'Frida/native bootstrap did not reach planned stop'),
        'unpassed_gates':['G1a full ABI','G1b full state','G1c two fresh diagnostics','G1d canary',
                         'G1e state and negative controls','G2 independent review','G3 fidelity','G4','G5','G6'],
        'input':original,'dependency_manifest_sha256':sha('artifacts/reference/dependencies/gm-dls.json'),
        'build':json.loads((build/'build.json').read_text()),'stage':str(stage),'prefix_baseline':baseline,
        'environment':{'os':platform.platform(),'arch':platform.machine(),'frida':frida.__version__,
            'wine':subprocess.check_output(['wine','--version'],text=True).strip(),
            'packages':subprocess.check_output(['pacman','-Q','wine','gamescope','nvidia-utils','lib32-nvidia-utils'],text=True).splitlines(),
            'gpu':subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version','--format=csv,noheader'],text=True).strip(),
            'display':{'kind':'gamescope-headless','width':1920,'height':1080,'launcher':'tools/wine-headless','wine_virtual_desktop':False},
            'settings':{k:v for k,v in env.items() if k.startswith(('WINE','EIDOLON_A_')) or k in ('AGENT','PULSE_SINK','XDG_CACHE_HOME','__GL_SHADER_DISK_CACHE_PATH')}},
        'bundle':{p:sha(p) for p in ('tools/run','tools/wine-headless','tools/capture/prepare-native.py')},
        'command':command,'started_utc':started,'finished_utc':datetime.now(timezone.utc).isoformat(),
        'launcher_exit':result,'injection_exit':injection,'negative_control':args.bad_fingerprint or args.invalid_helper,
        'runner_terminal':[s for s in (data/'runner.log').read_text(errors='replace').splitlines() if s.startswith(('WINE_EXIT=','A_CHILD_EXIT','TIMEOUT'))],
        'observations':[e for e in events if e['event'] not in ('clock','lookup')],
        'evidence':{str(p.relative_to(data_root)):sha(p) for p in sorted(data.iterdir()) if p.is_file()},
        'B_immutable_evidence':b_evidence}
    output=Path('artifacts/reference')/(args.run_id+'.json');output.write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'manifest':str(output),'status':manifest['status'],'failure':manifest['first_failed_check'],'exit':result}))
    return 0 if planned and result==0 else 1

if __name__=='__main__':raise SystemExit(main())
