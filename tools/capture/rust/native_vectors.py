#!/usr/bin/env python3
"""Bounded missing native oracle, built solely from the accepted observer snapshot."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'verify/rust'))
from conformance import CHECKOUT,ROOT,DATA,Native,load,checked,sha,need
from semantic import cleanup


def replace(path,old,new):
    text=path.read_text();need(text.count(old)==1,'native source transformation anchor: '+old[:60]);path.write_text(text.replace(old,new))


def prepare(name):
    native=Native();source=native.producer['build'];old=Path(source['build_directory'])
    # Preparation itself has a separate small reservation while candidate owns GPU.
    used=sum(p.stat().st_size for p in DATA.rglob('*') if p.is_file())
    active=load(DATA/'verification/rust/live-d28-scalars-full01/state.json')
    remaining=max(0,70_000_000-sum(p.stat().st_size for p in (DATA/'verification/rust/live-d28-scalars-full01').rglob('*') if p.is_file())) if active['phase']=='running' else 0
    need(used+remaining+2_000_000<30_000_000_000,'native build plus active reservation exceeds budget')
    job=DATA/'verification/rust'/name;job.mkdir(exist_ok=False);build=job/'build';build.mkdir();out=job/'output';out.mkdir()
    inputs={}
    for path,digest in source['outputs'].items():
        if path.endswith(('.c','.S','.h','.def')):
            src=checked(old/path,digest);target=build/path;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target);inputs[path]=digest
    core=build/'source-snapshot/tools/capture/proxy-b/core.c'
    replace(core,'static DWORD record(const char *event, const char *fields, ...) {','static DWORD record(const char *event, const char *fields, ...) {\n    if(!strcmp(event,"lookup")||!strcmp(event,"clock")||!strcmp(event,"program_use")||!strcmp(event,"clock_routes_checked")||!strcmp(event,"scene_anchor_locals")||!strcmp(event,"scene_state")||!strcmp(event,"post_present")) return 0;')
    replace(core,'    file_write(path, (void *)(uintptr_t)submitted_base, submitted_bytes, FALSE);','    /* Scalar oracle retains PCM hashes, not another PCM payload. */')
    compat=build/'source-snapshot/tools/capture/proxy-b-compat'
    replace(compat/'core.c','    char path[32768];\n    if (snprintf(path,sizeof(path),"%s/%s",folder,name)', '    if(!strncmp(name,"shader-",7)||strstr(name,"rgba")) return;\n    char path[32768];\n    if (snprintf(path,sizeof(path),"%s/%s",folder,name)')
    replace(compat/'consumer.c','    if(frame<5760 || frame>5762 || s[0]!=0x4085d7) return;','    (void)s; return; /* Existing volume evidence is immutable; no duplicate readback. */')
    stage=(compat/'stage.c').read_text();start=stage.index('static void stage_draw(DWORD *s) {');stop=stage.index('static void stage_capture(HDC dc) {')
    stage=stage[:start]+'#include "native_vectors.c"\nstatic void stage_draw(DWORD*s){vector_draw(s);}\n\n'+stage[stop:]
    stage=stage[:stage.index('static void stage_capture(HDC dc) {')]+'static void stage_capture(HDC dc){vector_capture(dc);}\n'
    (compat/'stage.c').write_text(stage);shutil.copyfile(CHECKOUT/'tools/capture/rust/native_vectors.c',compat/'native_vectors.c')
    compiler=subprocess.check_output(['i686-w64-mingw32-gcc','--version'],text=True).splitlines()[0];need(compiler==source['compiler'],'native compiler differs')
    commands=[]
    for command in source['commands'][:2]:
        command=[arg.replace(str(old),str(build)) if str(old) in arg else str(build/'source-snapshot'/arg) if arg.startswith('tools/') else arg for arg in command]
        subprocess.run(command,check=True);commands.append(command)
    original=native.producer['input'];archive=checked(ROOT/original['archive'],original['archive_sha256'])
    with zipfile.ZipFile(archive) as zipped:(build/original['exe']).write_bytes(zipped.read(original['exe']))
    checked(build/original['exe'],original['exe_sha256'])
    samples={0,1,2,26999}
    for row in native.manifest['scenes']:
        samples.update(n for n in (row['first']-1,row['first'],row['first']+1) if 0<=n<27000)
    (out/'samples.txt').write_text(''.join(str(n)+'\n' for n in sorted(samples)));(out/'retention.txt').write_text('')
    manifest=dict(schema='eidolon-native-vector-build-1',native_manifest_sha256=sha(native.path),candidate_sha256=load(CHECKOUT/'artifacts/rust/engine/candidate.json')['executable_sha256'],original=original,
                  tool_sources={p:sha(CHECKOUT/'tools/capture/rust'/p) for p in ('native_vectors.py','native_vectors.c')},
                  accepted_build_id=source['build_id'],original_build_inputs=inputs,compiler=compiler,commands=commands,samples=sorted(samples),
                  build_files={str(p.relative_to(build)):sha(p) for p in build.rglob('*') if p.is_file()},
                  scope='sequential27000 frames; bounded post-update physics at151 scene-edge samples, floating uniforms at those samples/draw ordinals9/18; unobserved later fields remain unclaimed; no media readback',
                  prepared_storage=dict(existing_bytes=used,active_reservation=remaining,build_reserve=2_000_000,limit=30_000_000_000))
    (job/'build.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(dict(prepared=str(job),samples=len(samples))))


def run(name):
    job=DATA/'verification/rust'/name;manifest=load(job/'build.json');build=job/'build';out=job/'output'
    scalar=load(DATA/'verification/rust/live-d28-scalars-full01/state.json');need(scalar['phase']=='closed','scalar job still owns GPU');cleanup(scalar)
    need(load(CHECKOUT/'artifacts/verification/rust/live-d28-scalars-full01.json')['status']=='SEMANTIC_FULL_EXACT','full scalar review missing')
    for path,digest in manifest['build_files'].items():checked(build/path,digest)
    for path,digest in manifest['tool_sources'].items():checked(CHECKOUT/'tools/capture/rust'/path,digest)
    used=sum(p.stat().st_size for p in DATA.rglob('*') if p.is_file());reserve=5_000_000
    prefix=DATA/'verification/rust/prefix';baseline=ROOT/'.tools/capture/T11-prefix-baseline'
    need(prefix.resolve()==prefix,'unexpected prefix link')
    old_prefix_bytes=sum(p.stat().st_size for p in prefix.rglob('*') if p.is_file())
    baseline_bytes=sum(p.stat().st_size for p in baseline.rglob('*') if p.is_file())
    projected=used-old_prefix_bytes+baseline_bytes
    need(projected+reserve<30_000_000_000 and shutil.disk_usage(DATA).free>reserve,'native vector storage preflight')
    shutil.rmtree(prefix);subprocess.run(['cp','-a','--reflink=auto',str(baseline),str(prefix)],check=True)
    need(sum(p.stat().st_size for p in DATA.rglob('*') if p.is_file())+reserve<30_000_000_000,'native actual reset storage')
    bank=sha(DATA/'reference/dependencies/gm.dls')
    for arch in ('system32','syswow64'):need(sha(prefix/f'drive_c/windows/{arch}/drivers/gm.dls')==bank,'native sound bank identity')
    exe=build/manifest['original']['exe'];sink='eidolon_T24_native_vectors';module=subprocess.check_output(['pactl','load-module','module-null-sink',f'sink_name={sink}'],text=True).strip()
    env={k:v for k,v in os.environ.items() if not k.startswith(('EIDOLON_B_','EIDOLON_RUST_'))}
    win=lambda p:'Z:'+str(p)
    env.update(AGENT='T24',WINE_TIMEOUT='14400',WINEDEBUG='-all',WINEDLLOVERRIDES='opengl32,winmm=n,b;winemenubuilder.exe,mscoree,mshtml=d',PULSE_SINK=sink,
               EIDOLON_B_LOG=win(out/'backend.jsonl'),EIDOLON_B_BOOTSTRAP='capture-probe',EIDOLON_B_OUTPUT=win(out),EIDOLON_B_FRAMES='3',EIDOLON_B_COMPAT='450-compatibility',EIDOLON_B_FULL='27000',EIDOLON_B_RETENTION=win(out/'retention.txt'))
    command=['bash','tools/run','tools/wine-headless',str(exe)]
    state=dict(phase='running',pid=os.getpid(),sid=os.getsid(0),name=name,started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
               command=command,build_sha256=sha(job/'build.json'),sound_bank_sha256=bank,wine_launcher_sha256=sha(CHECKOUT/'tools/wine-headless'),storage=dict(existing_bytes=used,replaced_owned_prefix_bytes=old_prefix_bytes,baseline_prefix_bytes=baseline_bytes,projected_bytes=projected,reserved_bytes=reserve,limit_bytes=30_000_000_000),environment={k:v for k,v in env.items() if k.startswith(('EIDOLON_B_','WINE','PULSE_'))},production_accepted=False)
    with (job/'runner.log').open('wb') as log:
        process=subprocess.Popen(command,cwd=CHECKOUT,env=env,stdout=log,stderr=subprocess.STDOUT);state['runner_pid']=process.pid;(job/'state.json').write_text(json.dumps(state,indent=2)+'\n')
        try:code=process.wait()
        finally:subprocess.run(['pactl','unload-module',module],check=True)
    state.update(phase='closed',exit_code=code,native_after_sha256=sha(exe),output={p.name:dict(bytes=p.stat().st_size,sha256=sha(p)) for p in out.iterdir() if p.is_file()},runner_log_sha256=sha(job/'runner.log'))
    (job/'state.json').write_text(json.dumps(state,indent=2)+'\n');print(json.dumps(state))


def launch(name):
    job=DATA/'verification/rust'/name;need(not (job/'state.json').exists(),'native job already executed')
    root=DATA/'verification/rust/jobs'/name;root.mkdir(exist_ok=False)
    command=['setsid','nohup','bash','tools/run','python','-u','tools/capture/rust/native_vectors.py',name]
    request=dict(command=command,build_sha256=sha(job/'build.json'),source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),state=str(job/'state.json'),log=str(root/'detached.log'),production_accepted=False)
    with (root/'detached.log').open('xb') as log:child=subprocess.Popen(command,cwd=CHECKOUT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
    request['pid']=child.pid;(root/'request.json').write_text(json.dumps(request,indent=2)+'\n')
    pointer=dict(request=str(root/'request.json'),request_sha256=sha(root/'request.json'),pid=child.pid,state=request['state'],log=request['log'],production_accepted=False)
    (CHECKOUT/'artifacts/verification/rust/native-vector-job.json').write_text(json.dumps(pointer,indent=2)+'\n');print(json.dumps(pointer))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('name');mode=p.add_mutually_exclusive_group();mode.add_argument('--prepare',action='store_true');mode.add_argument('--launch',action='store_true');a=p.parse_args()
    prepare(a.name) if a.prepare else launch(a.name) if a.launch else run(a.name)
