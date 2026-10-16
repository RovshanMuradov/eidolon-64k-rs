#!/usr/bin/env python3
"""Physical negative-control review; never accepts diagnostic jobs as production."""
import json
import struct
import sys
import subprocess
from pathlib import Path
from conformance import CHECKOUT,DATA,Native,load,checked,sha,need
from runtime_events import events


def review(name):
    job=DATA/"verification/rust"/name;m=load(job/"state.json");out=job/"output"
    need(m["phase"]=="closed" and m["exit_code"]==125,"fault must reject")
    pointer=load(CHECKOUT/"artifacts/rust/engine/candidate.json")
    need(m["candidate_sha256"]==m["candidate_after_sha256"]==pointer["executable_sha256"],"control production image identity")
    checked(m["candidate"],m["candidate_sha256"])
    for source,digest in m["sources"].items():checked(job/source,digest)
    checked(job/"live.dll",m["helper_sha256"]);checked(job/"launch.exe",m["launcher_sha256"])
    checked(job/"runner.log",m["runner_log_sha256"])
    for path,item in m["output"].items():checked(job/path,item["sha256"])
    native=Native();records=list(events(out/"events.bin"))
    need([k for k,_ in records[:3]]==[6,7,1],"real synthesis/submission/initial marker missing")
    need(all(payload.hex()==native.manifest["audio"]["sha256"] for k,payload in records if k in (6,7)),"control PCM digest mismatch")
    need(not any(k in (4,8) for k,_ in records),"fault accepted a pixel/present")
    before=(out/"position-before-fx.bin").read_bytes();after=(out/"position-after-fx.bin").read_bytes()
    need(len(before)==len(after)==512,"physical FP extent")
    log=(job/"runner.log").read_text(errors="replace")
    mode=m["physical_control"]
    if mode=="gl":
        need(before==after,"position FP preservation")
        a=(out/"position-before-gpr.bin").read_bytes();b=(out/"position-after-gpr.bin").read_bytes()
        need(len(a)==len(b)==36 and a[:28]==b[:28] and a[32:]==b[32:],"position GPR restoration excluding MMRESULT EAX")
        key,a,b=struct.unpack("<3i",(out/"gl-rejected.bin").read_bytes())
        need(key==0x0d05 and a!=b and b==(4 if a==1 else 1),"actual GL alignment mutation")
        need("CAPTURE_GL_RESTORE_MISMATCH" in log and "rc=23" in log,"GL restoration fault not detected")
    else:
        need(mode=="position" and before[:24]==after[:24] and before[25:]==after[25:] and before[24]^after[24]==0x40,"actual position MXCSR mutation")
        need("POSITION_FP_MISMATCH" in log,"position fault not detected")
    need(not Path(f"/proc/{m['runner_pid']}").exists(),"fault runner still active")
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():continue
        try:
            if b"WINEPREFIX=/tmp/opencode/eidolon/T24/prefix" in (p/"environ").read_bytes().split(b"\0"):
                need("wine" not in str((p/"exe").resolve()),"fault prefix process survived")
        except OSError:pass
    need("eidolon_T24_rust" not in subprocess.check_output(["pactl","list","short","sinks"],text=True),"fault private sink survived")
    return dict(job=name,mode=mode,status="PHYSICAL_FAULT_REJECTED",exit_code=125,accepted_pixels=0,
                state_sha256=sha(job/"state.json"),gpr_scope="position gate compares seven saved GPRs and EFLAGS; EAX is the MMRESULT output",
                helper_scope="follow-up diagnostic helper; original full capture remains bound to its prior source/helper hashes",cleanup_verified=True,production_accepted=False)


if __name__=="__main__":
    result=review(sys.argv[1]);(CHECKOUT/f"artifacts/verification/rust/control-{result['mode']}.json").write_text(json.dumps(result,indent=2)+"\n");print(json.dumps(result))
