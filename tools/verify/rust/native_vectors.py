#!/usr/bin/env python3
"""Review the missing native oracle independently of the producing C helper."""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
from conformance import CHECKOUT,DATA,Native,load,checked,sha,need
from runtime_events import events


def physics_records(raw,samples):
    need(len(raw)==len(samples)*268,'native physics extent')
    for index,n in enumerate(samples):
        offset=index*268;header=struct.unpack_from('<3I',raw,offset)
        need(header==(n,n*735,n*735),'native physics clock/order')
        yield raw[offset+12:offset+268]


def curve_records(raw,samples):
    at=0
    for n in samples:
        for ordinal in (9,18):
            need(at+44<=len(raw),'curve header extent');h=struct.unpack_from('<11I',raw,at);at+=44
            need(h[:3]==(n,n*735,ordinal) and h[4]>0 and h[10]<=256,'curve phase')
            values={}
            for _ in range(h[10]):
                need(at+140<=len(raw),'curve value extent');record=raw[at:at+140];at+=140
                name=record[:64].split(b'\0',1)[0].decode('ascii');count,kind,location=struct.unpack_from('<3I',record,64)
                expected={0x1406:1,0x8b50:2,0x8b51:3,0x8b52:4,0x8b5a:4,0x8b5b:9,0x8b5c:16}
                need(name and name not in values and expected.get(kind)==count and location<0x80000000,'curve name/type/liveness')
                values[name]=dict(type=kind,words=struct.unpack_from('<'+'I'*count,record,76))
            yield h,values
    need(at==len(raw),'extra curve records')


def review(name):
    job=DATA/'verification/rust'/name;state=load(job/'state.json');need(state['phase']=='closed' and state['exit_code']==0,'native oracle not closed successfully')
    build=load(checked(job/'build.json',state['build_sha256']));native=Native();need(build['native_manifest_sha256']==sha(native.path),'native reference identity')
    need(build['original']['exe_sha256']==native.producer['input']['exe_sha256']==state['native_after_sha256'],'native image identity')
    for p,digest in build['build_files'].items():checked(job/'build'/p,digest)
    for p,binding in state['output'].items():checked(job/'output'/p,binding['sha256'])
    log=checked(job/'runner.log',state['runner_log_sha256']).read_text(errors='replace');need('WINE_EXIT=0 GAMESCOPE_EXIT=0' in log,'native wrapper exit')
    observations=[json.loads(line) for line in (job/'output/backend.jsonl').read_text().splitlines()]
    need(not any(e['event']=='failure' for e in observations),'native observer failure')
    endpoint=[e for e in observations if e['event']=='native_endpoint'];need(len(endpoint)==1 and endpoint[0]['frames']==27000 and endpoint[0]['queries']==27001,'native natural endpoint')
    need(any(e['event']=='native_exit_forward' and e['registers_fp_equal'] for e in observations),'native exit restoration')
    need(all(e['equal'] for e in observations if e['event'] in ('abi_canary','native_resumed')),'native physical restoration')
    physical=list(physics_records((job/'output/physics.bin').read_bytes(),build['samples']))
    candidate_job=DATA/'verification/rust/live-d26-full01';candidate=load(candidate_job/'state.json')
    need(candidate['candidate_sha256']==build['candidate_sha256'],'candidate image identity')
    path=checked(candidate_job/'output/events.bin',candidate['output']['output/events.bin']['sha256'])
    snapshots=[p for kind,p in events(path) if kind==2];need(len(snapshots)==27000,'candidate physics coverage')
    differences=[n for n,a in zip(build['samples'],physical) if a!=snapshots[n][28:]]
    curves=list(curve_records((job/'output/curves.bin').read_bytes(),build['samples']))
    leftovers=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            if os.getsid(int(p.name))==state['sid'] or (b'WINEPREFIX=/tmp/opencode/eidolon/T24/prefix' in (p/'environ').read_bytes().split(b'\0') and 'wine' in str((p/'exe').resolve())):leftovers.append(int(p.name))
        except OSError:pass
    need(not leftovers and 'eidolon_T24_native_vectors' not in subprocess.check_output(['pactl','list','short','sinks'],text=True),'native cleanup')
    result=dict(status='NATIVE_SAMPLED_PHYSICS_EXACT_CURVES_UNPAIRED' if not differences else 'NATIVE_PHYSICS_DIFFERENCES',physics_frames=len(physical),physics_differences=len(differences),first_difference=next(iter(differences),None),
                sampled_curve_draws=len(curves),curve_float_words=sum(len(v['words']) for _,values in curves for v in values.values()),state_sha256=sha(job/'state.json'),candidate_state_sha256=sha(candidate_job/'state.json'),cleanup_verified=True,production_accepted=False)
    (CHECKOUT/f'artifacts/verification/rust/{name}.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('name');review(p.parse_args().name)
