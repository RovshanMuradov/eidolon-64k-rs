#!/usr/bin/env python3
"""Review closed bounded D26 jobs; failures remain failures, never full-run acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from conformance import Native, DATA, CHECKOUT, checked, load, sha, exact_files, need, PCM_BYTES
from runtime_events import events


def review(directory):
    m=load(directory/"state.json");need(m["phase"]=="closed","live job still active")
    checked(directory/"runner.log",m["runner_log_sha256"])
    for name,digest in m["sources"].items():checked(directory/name,digest)
    checked(directory/"live.dll",m["helper_sha256"]);checked(directory/"launch.exe",m["launcher_sha256"])
    for name,item in m["output"].items():checked(directory/name,item["sha256"])
    need(m["candidate_sha256"]==m["candidate_after_sha256"],"candidate changed")
    native=Native();out=directory/"output";log=(directory/"runner.log").read_text(errors="replace")
    result=dict(job=str(directory.relative_to(DATA)),exit_code=m["exit_code"],reference_accepted=True,
                production_accepted=False,control=m["control"],fault=m["fault"],checks={},failures=[])
    if m["control"]:
        result.update(status="UNINSTRUMENTED_CONTROL",terminal=[l for l in log.splitlines() if "EIDOLON" in l or "WINE_EXIT=" in l]);return result
    for label,a,b,parts in (("entry", "entry-before.bin","entry-after.bin",[(0,36),(64,576)]),
                           ("marker_fp","marker-before-fx.bin","marker-restored-fx.bin",[(0,512)]),
                           ("marker_gpr","marker-before-gpr.bin","marker-restored-gpr.bin",[(0,36)])):
        if (out/a).exists() and (out/b).exists():
            first,second=(out/a).read_bytes(),(out/b).read_bytes()
            equal=all(first[x:y]==second[x:y] and len(first)>=y and len(second)>=y for x,y in parts)
            result["checks"][label]=equal
            if not equal:result["failures"].append(label+" physical restoration")
        else:result["checks"][label]="missing"
    if (out/"pcm.f32le").exists():
        try:exact_files(native.pcm,out/"pcm.f32le",PCM_BYTES);result["checks"]["pcm"]="EXACT_NATIVE_PCM"
        except ValueError as e:result["failures"].append(str(e));result["checks"]["pcm"]="MISMATCH"
    stream=list(events(out/"events.bin")) if (out/"events.bin").exists() else []
    times=native.times() if any(k==2 for k,_ in stream) else []
    query,pre,post,pixels,layouts=[],[],[],[],[]
    gl_witnesses=0
    for kind,payload in stream:
        if kind in (6,7,9) and payload.hex()!=native.manifest["audio"]["sha256"]:
            result["failures"].append(f"native PCM digest differs at marker {kind}")
        if kind==1 and payload[28:]!=native.states["first-query/physics"].read_bytes():result["failures"].append("native initial physics")
        if kind==2:
            words=struct.unpack("<7I",payload[:28]);n=words[0];query.append(n)
            expected=times[n]
            if words[:3]!=expected[:3] or words[5]!=expected[3]:result["failures"].append(f"native time at {n}")
        if kind==3:pre.append(payload)
        if kind==4:post.append(payload)
        if kind==10:layouts.append(payload)
        if kind==8:
            n=struct.unpack_from("<I",payload)[0];pixels.append(n)
            if payload[4:].hex()!=native.frames[n]["sha256"]:result["failures"].append(f"native RGBA hash differs at {n}: actual={payload[4:].hex()} expected={native.frames[n]['sha256']}")
            raw=out/f"frame-{n:05d}.raw"
            if not raw.exists() or raw.stat().st_size!=8294400 or sha(raw)!=payload[4:].hex():result["failures"].append(f"candidate raw coverage/identity {n}")
            gl=out/f"gl-{n:05d}.bin"
            if gl.exists():
                words=struct.unpack("<18i",gl.read_bytes())
                if words[:9]!=words[9:]:result["failures"].append(f"GL restoration {n}")
                else:gl_witnesses+=1
            else:result["checks"]["raw_gl_restoration"]="missing"
    need(query==list(range(len(query))),"query order")
    need(pixels==list(range(len(pixels))),"pixel order")
    result["checks"].update(queries=len(query),pre_presents=len(pre),post_presents=len(post),pixels=len(pixels),layouts=len(layouts),
                            gl_restoration_witnesses=gl_witnesses,pre_post_equal=pre==post,planned_stop=f"PLANNED_SHORT_STOP frames={m['frames_requested']}" in log)
    result["status"]="SHORT_EXACT_PARTIAL" if not result["failures"] and len(post)==m["frames_requested"] else "MISMATCH_OR_INCOMPLETE"
    if m.get("entry_fault") or m["fault"]:
        changed=False
        if m.get("entry_fault"):
            a=(out/"entry-before.bin").read_bytes();b=(out/"entry-after.bin").read_bytes()
            changed=(a[:36]!=b[:36] or a[64:576]!=b[64:576])
        elif m["fault"]=="gpr":
            a=(out/"marker-before-gpr.bin").read_bytes();b=(out/"marker-rejected-gpr.bin").read_bytes()
            changed=len(a)==len(b)==36 and a[:28]==b[:28] and a[29:]==b[29:] and a[28]^b[28]==1
        else:
            a=(out/"marker-before-fx.bin").read_bytes();b=(out/"marker-rejected-fx.bin").read_bytes()
            changed=len(a)==len(b)==512 and a[:24]==b[:24] and a[25:]==b[25:] and a[24]^b[24]==0x40
        need(changed and m["exit_code"]==125 and not pixels,"live fault was not physically changed/rejected before pixels")
        result["status"]="FAULT_REJECTED";result["checks"]["physical_fault_changed_and_rejected"]=True
    result["remaining"]=["complete native post-update state", "full-duration runtime/endpoint and performance", "all-hook live fault controls"]
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("directory",type=Path);p.add_argument("--result",type=Path)
    a=p.parse_args();result=review(a.directory);text=json.dumps(result,indent=2)+"\n"
    if a.result:a.result.write_text(text)
    print(text,end="")
