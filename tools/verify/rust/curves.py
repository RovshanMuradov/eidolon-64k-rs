#!/usr/bin/env python3
"""Pair bounded native GPU-active curve vectors with the immutable production EXE."""
import argparse
import json
from pathlib import Path
import re
import struct
from conformance import CHECKOUT,DATA,Native,load,checked,sha,need
from native_vectors import curve_records,physics_records
from runtime_events import events
from semantic import cleanup
from monitor_full import native_times,process,live_images


def compare_draw(actual,expected,programs,native_programs,fbos,mapping,reverse):
    a,av=actual;b,bv=expected
    need(a[:3]==b[:3],'curve sample clock/order')
    need(programs[a[4]]==native_programs[b[4]],'curve shader source identity')
    need(a[6:10]==b[6:10],'curve viewport')
    logical=0 if a[5]==0 else fbos.index(a[5])+1
    need(mapping.setdefault(b[5],logical)==logical and reverse.setdefault(logical,b[5])==b[5],'curve framebuffer role consistency')
    need(av.keys()==bv.keys(),'curve active-name set')
    for name in bv:need(av[name]==bv[name],f'curve bits/type differ at frame{b[0]} pass{b[2]} {name}')
    return sum(len(value['words']) for value in bv.values())


def bindings():
    pointer=load(CHECKOUT/'artifacts/verification/rust/curve-job.json');request=load(checked(DATA/pointer['request'],pointer['request_sha256']))
    job=Path(pointer['state']).parent;state=load(job/'state.json')
    need(pointer['pid']==request['pid']==state['pid']==state['sid'],'curve job identity')
    need(state['curves'] and state['semantic'] and state['full'] and state['frames_requested']==27000,'curve mode')
    candidate=load(CHECKOUT/'artifacts/rust/engine/candidate.json');need(candidate['executable_sha256']==state['candidate_sha256'],'curve candidate identity');checked(state['candidate'],state['candidate_sha256'])
    for name,digest in state['sources'].items():
        need(request['sources'][name]==digest,'curve source snapshot');checked(job/name,digest)
    checked(job/'live.dll',state['helper_sha256']);checked(job/'launch.exe',state['launcher_sha256'])
    native_job=DATA/'verification/rust/native-d28-vectors01';review=load(CHECKOUT/'artifacts/verification/rust/native-d28-vectors01.json')
    native_state=load(checked(native_job/'state.json',review['state_sha256']));build=load(checked(native_job/'build.json',native_state['build_sha256']))
    samples=build['samples'];mask=checked(job/'retention.bin',state['retention_sha256']).read_bytes();need(len(mask)==27000 and [n for n,v in enumerate(mask) if v]==samples and set(mask)=={0,1},'curve sample mask')
    return job,state,native_job,native_state,build


def program_roles(path,native):
    actual={};expected={}
    with path.open('rb') as f:
        for index,call in enumerate(native.sidecar['calls']):
            header=f.read(12);need(len(header)==12,'curve shader header');program,stage,count=struct.unpack('<3I',header)
            need(program not in actual and stage==call['stage'] and count==call['count'],'curve program identity')
            for source in call['forwarded']:
                raw=native.bound(source).read_bytes()+b'\0';length=f.read(4);need(len(length)==4 and struct.unpack('<I',length)[0]==len(raw) and f.read(len(raw))==raw,'curve shader source bytes')
            actual[program]=index;expected[call['program']]=index
        need(not f.read(1),'extra curve shader source')
    return actual,expected


def complete_curve_prefix(raw,samples):
    offset=0;ends=[]
    while len(raw)-offset>=44:
        header=struct.unpack_from('<11I',raw,offset);need(header[10]<=256,'growing curve record extent')
        end=offset+44+140*header[10]
        if end>len(raw):break
        ends.append(end);offset=end
    pairs=len(ends)//2;need(pairs<=len(samples),'growing curve sample coverage')
    boundary=ends[pairs*2-1] if pairs else 0
    return list(curve_records(raw[:boundary],samples[:pairs])),len(raw)-boundary


def review():
    job,state,native_job,native_state,build=bindings();out=job/'output';native=Native();samples=build['samples']
    need(state['phase']=='closed' and state['exit_code']==0 and state['candidate_after_sha256']==state['candidate_sha256'],'curve process closure')
    for path,binding in state['output'].items():checked(job/path,binding['sha256'])
    log=checked(job/'runner.log',state['runner_log_sha256']).read_text(errors='replace')
    need('reason=natural_exit queries=27001 frames=27000 terminal_cursor=19845000' in log and 'CHILD_EXIT 0 entry_proof=1' in log and 'WINE_EXIT=0 GAMESCOPE_EXIT=0' in log and 'PLANNED_SHORT_STOP' not in log,'curve natural endpoint')
    need(not re.search(r'SEMANTIC_FAILURE|HOOK_(?:FP|GPR)_MISMATCH|LAUNCH_FAILURE|EIDOLON_RUNTIME error:|TIMEOUT',log),'curve runtime error')
    clean=cleanup(state)
    for stem,size in (('seed',512),('draw',512)):
        for kind,length in (('fx',size),('gpr',36)):
            a=(out/f'{stem}-before-{kind}.bin').read_bytes();b=(out/f'{stem}-after-{kind}.bin').read_bytes();need(len(a)==len(b)==length and a==b,'curve physical '+stem+'/'+kind)
    for name,a,b,start,end in (('entry GPR','entry-before.bin','entry-after.bin',0,36),('entry FP','entry-before.bin','entry-after.bin',64,576),('marker FP','marker-before-fx.bin','marker-restored-fx.bin',0,512),('marker GPR','marker-before-gpr.bin','marker-restored-gpr.bin',0,36)):
        first=(out/a).read_bytes();second=(out/b).read_bytes();need(len(first)>=end and len(second)>=end and first[start:end]==second[start:end],name)
    need((out/'ready-seed.bin').read_bytes()==native.states['prethread/rng'].read_bytes()[16:32] and (out/'ready-tick.bin').read_bytes()==native.states['prethread/tick'].read_bytes(),'curve ready fields')
    need((out/'previous-seconds.bin').read_bytes()==native.states['first-query/previous-seconds'].read_bytes() and (out/'initial-physics-live.bin').read_bytes()==native.states['first-query/physics'].read_bytes(),'curve initial fields')
    ledger=list(events(out/'events.bin'));need([k for k,_ in ledger]==[6,7,1]+[2,3,4]*len(samples)+[5,9],'sparse curve ledger order')
    for k,p in ledger:
        if k in (6,7,9):need(p.hex()==native.manifest['audio']['sha256'],'curve PCM memory digest')
    native_physics=checked(native_job/'output/physics.bin',native_state['output']['physics.bin']['sha256']).read_bytes()
    times=native_times(native)
    for index,(n,physics) in enumerate(zip(samples,physics_records(native_physics,samples))):
        actual=ledger[3+3*index][1];need(actual==ledger[4+3*index][1]==ledger[5+3*index][1],'curve marker consistency')
        words=struct.unpack_from('<7I',actual);need(words[:3]==times[n][:3] and words[5]==times[n][3],'curve native clock')
        need(actual[28:]==physics,f'curve-run native physics {n}')
    terminal=struct.unpack_from('<7I',ledger[-2][1]);need(terminal[:3]==(27000,19845000,0x43e10000) and terminal[4]==0xffffffff,'curve terminal marker')
    programs,native_programs=program_roles(out/'programs.bin',native)
    objects=(out/'objects.bin').read_bytes();need(struct.unpack_from('<2I',objects)==(1,13),'curve framebuffer allocation');fbos=struct.unpack_from('<13I',objects,8)
    expected=list(curve_records(checked(native_job/'output/curves.bin',native_state['output']['curves.bin']['sha256']).read_bytes(),samples))
    actual=list(curve_records((out/'curves.bin').read_bytes(),samples));mapping={0:0};reverse={0:0};words=0
    base=struct.unpack_from('<I',(out/'seed-phase.bin').read_bytes())[0]
    for a,b in zip(actual,expected):
        need(a[0][3]==base+0x143d5,'curve observed call site')
        words+=compare_draw(a,b,programs,native_programs,fbos,mapping,reverse)
    need(len(actual)==len(expected)==302,'curve record coverage')
    return dict(status='SAMPLED_NATIVE_CURVES_AND_PHYSICS_EXACT',physics_samples=len(samples),curve_draws=len(actual),float_words=words,
                sampled_coverage='151 scene-edge frames, draw ordinals9/18; full sequential27000-frame execution; no exhaustive hidden-state claim',
                state_sha256=sha(job/'state.json'),native_state_sha256=sha(native_job/'state.json'),candidate_sha256=state['candidate_sha256'],cleanup=clean,production_accepted=False)


def reconcile():
    job,state,native_job,native_state,build=bindings();processes=[process(state[k]) for k in ('pid','runner_pid')]
    if state['phase']=='running':need(all(p['exists'] and p['sid']==state['sid'] for p in processes),'lost curve process')
    used=sum(p.stat().st_size for p in DATA.rglob('*') if p.is_file());need(used<30000000000,'curve storage limit')
    result=dict(phase=state['phase'],state_sha256=sha(job/'state.json'),processes=processes,data_bytes=used,
                live_mappings=live_images(state['candidate'],job/'live.dll'),output_bytes={p.name:p.stat().st_size for p in (job/'output').iterdir() if p.is_file()},production_accepted=False)
    identity=CHECKOUT/'artifacts/verification/rust/curve-live-identity.json'
    if result['live_mappings'] and not identity.exists():
        identity.write_text(json.dumps(dict(candidate_sha256=state['candidate_sha256'],helper_sha256=state['helper_sha256'],state_sha256=sha(job/'state.json'),processes=processes,mappings=result['live_mappings']),indent=2)+'\n')
    path=job/'output/curves.bin'
    if path.exists():
        actual,pending=complete_curve_prefix(path.read_bytes(),build['samples']);result['complete_curve_draws']=len(actual);result['pending_curve_bytes']=pending
        if actual:
            native=Native();programs,native_programs=program_roles(job/'output/programs.bin',native)
            fbos=struct.unpack_from('<13I',(job/'output/objects.bin').read_bytes(),8)
            expected=list(curve_records(checked(native_job/'output/curves.bin',native_state['output']['curves.bin']['sha256']).read_bytes(),build['samples']))
            mapping={0:0};reverse={0:0};result['matching_float_words']=sum(compare_draw(a,b,programs,native_programs,fbos,mapping,reverse) for a,b in zip(actual,expected))
    if state['phase']=='closed':result['cleanup']=cleanup(state)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reconcile',action='store_true');a=p.parse_args();result=reconcile() if a.reconcile else review()
    (CHECKOUT/'artifacts/verification/rust'/('curve-progress.json' if a.reconcile else 'curves.json')).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
