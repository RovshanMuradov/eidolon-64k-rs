#!/usr/bin/env python3
"""Exact D28 field and GPU-active uniform checks against independently saved native observations."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import zstandard
from conformance import CHECKOUT,DATA,Native,load,checked,sha,need
from runtime_events import events
from monitor_full import native_times, process, live_images


def compare_uniform(a,b,n,ordinal,actual_program,expected_program,fbo_ids,volume,native_volume,mapping,reverse):
    need(a[:2]==b[:2]==(n,ordinal),"draw order")
    need(actual_program[a[2]]==expected_program[b[2]],f"shader identity {n}/{ordinal}")
    need(a[4:8]==b[4:8],f"viewport {n}/{ordinal}")
    logical=0 if a[3]==0 else 1+fbo_ids.index(a[3])
    need(mapping.setdefault(b[3],logical)==logical and reverse.setdefault(logical,b[3])==b[3],"framebuffer role correspondence")
    need((a[8]!=0xffffffff)==(b[8]!=0xffffffff),"time-uniform liveness")
    if b[8]!=0xffffffff:need(a[9:12]==b[9:12],f"native time uniform {n}/{ordinal}")
    need((a[12]!=0xffffffff)==(b[12]!=0xffffffff),"cloud-uniform liveness")
    if b[12]!=0xffffffff:need(a[13]==b[13] and a[14]==volume and b[14]==native_volume,"cloud sampler/resource")
    need(a[15]==a[16] and a[17:19]==(0,0),"queried GL restoration")


def cleanup(state):
    leftovers=[];session=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            if os.getsid(int(p.name))==state['sid']:session.append(int(p.name))
            if b'WINEPREFIX=/tmp/opencode/eidolon/T24/prefix' in (p/'environ').read_bytes().split(b'\0') and 'wine' in str((p/'exe').resolve()):leftovers.append(int(p.name))
        except OSError:pass
    sink='eidolon_T24_rust' in subprocess.check_output(['pactl','list','short','sinks'],text=True)
    need(not leftovers and not session and not sink,'semantic cleanup incomplete')
    return dict(wine_pids=leftovers,session_pids=session,private_sink_present=sink)


def reconcile():
    pointer=load(CHECKOUT/'artifacts/verification/rust/semantic-job.json')
    request=load(checked(DATA/pointer['request'],pointer['request_sha256']))
    path=Path(pointer['state']);state=load(path);job=path.parent
    need(pointer['pid']==request['pid']==state['pid']==state['sid']==2493456,'scalar supervisor identity')
    need(state['semantic'] and state['full'] and state['frames_requested']==27000,'scalar mode')
    for name,digest in state['sources'].items():
        need(digest==request['sources'][name],'scalar source snapshot');checked(job/name,digest)
    checked(state['candidate'],state['candidate_sha256']);checked(job/'live.dll',state['helper_sha256'])
    processes=[process(state[k]) for k in ('pid','runner_pid')]
    if state['phase']=='running':
        need(processes[0]['exists'] and processes[0]['sid']==state['sid'] and '--full --semantic' in processes[0]['command'],'lost scalar supervisor')
        need(processes[1]['exists'] and processes[1]['sid']==state['sid'],'lost scalar runner')
    used=sum(p.stat().st_size for p in DATA.rglob('*') if p.is_file());need(used<30000000000,'30GB data limit')
    result=dict(phase=state['phase'],state_sha256=sha(path),processes=processes,data_bytes=used,
                live_mappings=live_images(state['candidate'],job/'live.dll'),uniform_bytes=(job/'output/uniforms.bin').stat().st_size,
                production_accepted=False)
    if state['phase']=='closed':result['cleanup']=cleanup(state)
    return result


def native_uniforms(native):
    root=DATA/"verification/rust";path=root/"native-uniforms.bin.zst";meta=root/"native-uniforms.json"
    desc=native.producer["ordered_stream"]
    if meta.exists():
        pin=load(meta);need(pin["source_sha256"]==desc["sha256"],"uniform projection source")
        return checked(path,pin["sha256"])
    source=checked(native.directory/desc["path"],desc["sha256"]);decoder=zstandard.ZstdDecompressor().decompressobj();digest=hashlib.sha256();size=0;pending=b"";count=0
    with source.open("rb") as stream,path.open("xb") as target,zstandard.ZstdCompressor(level=5).stream_writer(target) as out:
        while block:=stream.read(1<<20):
            raw=decoder.decompress(block);digest.update(raw);size+=len(raw);need(not decoder.unused_data,"native trailing compressed data")
            lines=(pending+raw).split(b"\n");pending=lines.pop()
            for line in lines:
                if b'"event":"scene_pass"' not in line:continue
                e=json.loads(line);n,ordinal=divmod(count,19);need(e["n"]==n,"native pass order")
                words=[n,ordinal,e["program"],e["draw_fbo"],*e["viewport"],e["time_location"],*e["time_resolution_bits"],e["cloud_location"],e["cloud_unit"],e["cloud_texture"]]
                out.write(struct.pack("<15I",*(v&0xffffffff for v in words)));count+=1
    need(decoder.eof and not pending and size==desc["decoded_bytes"] and digest.hexdigest()==desc["decoded_sha256"] and count==513000,"native uniform projection coverage")
    meta.write_text(json.dumps(dict(source_sha256=desc["sha256"],sha256=sha(path),records=count),indent=2)+"\n");return path


def review(name):
    job=DATA/"verification/rust"/name;state=load(job/"state.json");out=job/"output";need(state["phase"]=="closed" and state["semantic"],"semantic job incomplete")
    candidate=load(CHECKOUT/"artifacts/rust/engine/candidate.json")
    need(state["candidate_sha256"]==state["candidate_after_sha256"]==candidate["executable_sha256"],"semantic candidate identity")
    checked(state["candidate"],state["candidate_sha256"])
    for path,item in state["output"].items():checked(job/path,item["sha256"])
    for path,digest in state["sources"].items():checked(job/path,digest)
    checked(job/"live.dll",state["helper_sha256"]);checked(job/"launch.exe",state["launcher_sha256"]);checked(job/"runner.log",state["runner_log_sha256"])
    native=Native();need((out/"ready-seed.bin").read_bytes()==native.states["prethread/rng"].read_bytes()[16:32],"live ready seed differs")
    need((out/"ready-tick.bin").read_bytes()==native.states["prethread/tick"].read_bytes(),"live ready tick differs")
    phase=struct.unpack("<5I",(out/"seed-phase.bin").read_bytes());need(phase[1]==0xa3b5 and phase[2] and phase[3] and phase[4],"seed phase metadata")
    if state["seed_fault"]:
        a=(out/"seed-before-fx.bin").read_bytes();b=(out/"seed-rejected-fx.bin").read_bytes()
        need(state["exit_code"]==125 and a[:24]==b[:24] and a[25:]==b[25:] and a[24]^b[24]==0x40,"seed physical mutation/rejection")
        return dict(status="SEED_PHYSICAL_FAULT_REJECTED",job=name,state_sha256=sha(job/"state.json"),production_accepted=False)
    need(state["exit_code"]==0,"semantic process exit")
    for what,size in (("seed",512),("draw",512)):
        a=(out/f"{what}-before-fx.bin").read_bytes();b=(out/f"{what}-after-fx.bin").read_bytes();need(len(a)==len(b)==512 and a==b,what+" physical FP")
        a=(out/f"{what}-before-gpr.bin").read_bytes();b=(out/f"{what}-after-gpr.bin").read_bytes();need(len(a)==len(b)==36 and a==b,what+" physical GPR")
    need((out/"previous-seconds.bin").read_bytes()==native.states["first-query/previous-seconds"].read_bytes(),"live previous seconds")
    need((out/"initial-physics-live.bin").read_bytes()==native.states["first-query/physics"].read_bytes(),"live initial physics")
    previous=struct.unpack("<3I",(out/"previous-phase.bin").read_bytes());need(previous[0]==phase[0]+0x12a09 and previous[1] and previous[2]!=phase[4],"previous field phase/thread attribution")
    expected_program={};actual_program={}
    with (out/"programs.bin").open("rb") as stream:
        for index,call in enumerate(native.sidecar["calls"]):
            header=stream.read(12);need(len(header)==12,"program header");program,stage,count=struct.unpack("<3I",header)
            need(stage==call["stage"] and count==call["count"] and program not in actual_program,"program identity/count")
            for source in call["forwarded"]:
                raw=native.bound(source).read_bytes()+b"\0";length=stream.read(4);need(len(length)==4 and struct.unpack("<I",length)[0]==len(raw) and stream.read(len(raw))==raw,"observed shader source differs")
            expected_program[call["program"]]=index;actual_program[program]=index
        need(not stream.read(1),"extra programs")
    with (out/"objects.bin").open("rb") as stream:
        fbo_ids=[];texture_ids=[];volume=None
        for kind,count in ((1,13),(2,15),(2,1)):
            need(stream.read(8)==struct.pack("<2I",kind,count),"resource creation role")
            ids=struct.unpack("<"+"I"*count,stream.read(count*4));need(all(ids) and len(set(ids))==count,"resource names")
            if kind==1:fbo_ids=ids
            elif count==15:texture_ids=ids
            else:volume=ids[0]
        need(not stream.read(1) and volume not in texture_ids,"volume resource role")
    records=list(events(out/"events.bin"));frames=sum(k==4 for k,_ in records)
    need(frames==state["frames_requested"],"semantic frame coverage")
    order=[6,7,1]+[2,3,4]*frames+([5,9] if state["full"] else [])
    need([kind for kind,_ in records]==order,"semantic event order/endpoint")
    times=native_times(native)
    for n in range(frames):
        query=records[3+n*3][1];need(query==records[4+n*3][1]==records[5+n*3][1],"marker snapshot consistency")
        words=struct.unpack("<7I",query[:28]);expected=times[n]
        need(words[:3]==expected[:3] and words[5]==expected[3],"native semantic clock")
    if state["full"]:
        terminal=struct.unpack("<7I",records[-2][1][:28]);need(terminal[:3]==(27000,19845000,0x43e10000) and terminal[4]==0xffffffff,"semantic natural endpoint")
        log=(job/'runner.log').read_text(errors='replace')
        need('reason=natural_exit queries=27001 frames=27000 terminal_cursor=19845000' in log and 'CHILD_EXIT 0 entry_proof=1' in log and 'WINE_EXIT=0 GAMESCOPE_EXIT=0' in log and 'PLANNED_SHORT_STOP' not in log,'semantic natural exit log')
        need(not re.search(r'SEMANTIC_FAILURE|HOOK_(?:FP|GPR)_MISMATCH|LAUNCH_FAILURE|EIDOLON_RUNTIME error:|TIMEOUT',log),'semantic runtime error')
        cleanup(state)
    for kind,payload in records:
        if kind in (6,7,9):need(payload.hex()==native.manifest["audio"]["sha256"],"semantic PCM digest")
    native_volume=next(e["texture"] for e in native.producer["observations"] if e["event"]=="volume_upload")
    native_path=native_uniforms(native);mapping={0:0};reverse={0:0};comparisons=0
    with (out/"uniforms.bin").open("rb") as actual,native_path.open("rb") as compressed,zstandard.ZstdDecompressor().stream_reader(compressed) as expected:
        for n in range(frames):
            for ordinal in range(19):
                raw=actual.read(76);need(len(raw)==76,"uniform record truncated");a=struct.unpack("<19I",raw);b=struct.unpack("<15I",expected.read(60))
                compare_uniform(a,b,n,ordinal,actual_program,expected_program,fbo_ids,volume,native_volume,mapping,reverse)
                comparisons+=1
        need(not actual.read(1),"extra uniform records")
    return dict(status="SEMANTIC_PREFIX_EXACT" if not state["full"] else "SEMANTIC_FULL_EXACT",job=name,frames=frames,uniform_passes=comparisons,
                ready_seed=True,ready_tick=True,previous_seconds=True,initial_physics=True,program_sources=31,framebuffer_role_bijection=mapping,
                state_sha256=sha(job/"state.json"),native_uniform_projection_sha256=sha(native_path),cleanup_verified=state['full'],production_accepted=False)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("name",nargs="?");p.add_argument("--prepare-native",action="store_true");p.add_argument('--reconcile',action='store_true');a=p.parse_args()
    if a.reconcile:
        result=reconcile();(CHECKOUT/'artifacts/verification/rust/semantic-progress.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    elif a.prepare_native:print(native_uniforms(Native()))
    else:
        result=review(a.name);(CHECKOUT/f"artifacts/verification/rust/{a.name}.json").write_text(json.dumps(result,indent=2)+"\n");print(json.dumps(result))
