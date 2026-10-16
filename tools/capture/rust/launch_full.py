#!/usr/bin/env python3
"""D26 gated single detached full acquisition, with durable launch identity."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"verify/rust"))
from conformance import CHECKOUT, DATA, need, sha
from review_live import review


def launch(name,semantic=False,curves=False):
    checks={key:review(DATA/"verification/rust"/job) for key,job in
            (("short","live-d26-02"),("marker_fp_fault","live-d26-fp-reject"),("entry_gpr_fault","live-d26-entry-gpr"))}
    short=checks["short"]
    need(short["status"]=="SHORT_EXACT_PARTIAL" and short["checks"]["gl_restoration_witnesses"]==3,
         "short pixel/PCM/GL gate is not closed")
    need(all(short["checks"][key] is True for key in ("entry","marker_fp","marker_gpr")),"physical restoration gate")
    need(all(checks[k]["status"]=="FAULT_REJECTED" for k in ("marker_fp_fault","entry_gpr_fault")),"live rejection gate")
    if semantic:
        from semantic import review as review_semantic
        checks["semantic_prefix"]=review_semantic("live-d28-prefix")
        checks["seed_fault"]=review_semantic("live-d28-seed-reject")
        need(checks["semantic_prefix"]["status"]=="SEMANTIC_PREFIX_EXACT" and checks["seed_fault"]["status"]=="SEED_PHYSICAL_FAULT_REJECTED","semantic launch gate")
    root=DATA/"verification/rust/jobs"/name;root.mkdir(parents=True,exist_ok=False)
    command=["setsid","nohup","bash","tools/run","python","-u","tools/capture/rust/live.py",name,"--full"]
    if semantic:command.append("--semantic")
    if curves:
        need(semantic,"curve mode requires semantic adapter");command.append("--curves")
    request=dict(schema="eidolon-rust-detached-job-1",decision="D26",phase="launching",
                 created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),command=command,
                 source_commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=CHECKOUT,text=True).strip(),
                 sources={p.name:sha(p) for p in (CHECKOUT/"tools/capture/rust").iterdir() if p.is_file()},
                 gates=checks,expected_seconds=4500,gpu_reservation="T24 exclusive; persists until closed and cleanup confirmed",
                 state_path=str(DATA/"verification/rust"/name/"state.json"),log_path=str(root/"detached.log"),production_accepted=False)
    path=root/"request.json";path.write_text(json.dumps(request,indent=2)+"\n")
    with (root/"detached.log").open("wb") as log:
        process=subprocess.Popen(command,cwd=CHECKOUT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,close_fds=True)
    request.update(phase="launched",pid=process.pid);path.write_text(json.dumps(request,indent=2)+"\n")
    (root/"pid").write_text(str(process.pid)+"\n")
    pointer=dict(schema=request["schema"],request=str(path.relative_to(DATA)),request_sha256=sha(path),pid=process.pid,
                 state=request["state_path"],log=request["log_path"],expected_seconds=4500,production_accepted=False)
    (CHECKOUT/"artifacts/verification/rust"/("curve-job.json" if curves else "semantic-job.json" if semantic else "full-job.json")).write_text(json.dumps(pointer,indent=2)+"\n")
    print(json.dumps(pointer))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("name")
    parser.add_argument("--semantic",action="store_true");parser.add_argument("--curves",action="store_true");args=parser.parse_args()
    launch(args.name,args.semantic,args.curves)
