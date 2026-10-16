#!/usr/bin/env python3
"""D26 short live job; Windows programs only through the approved headless launcher."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"verify/rust"))
from conformance import CHECKOUT, ROOT, DATA, Native, checked, sha, load, need


def run(name,frames,control=False,fault=False,entry_fault=None,full=False,physical_control=None,semantic=False,seed_fault=False):
    need((full and frames==27000 and not control and not fault and not entry_fault) or (not full and 1<=frames<=3),"invalid capture extent/mode")
    native=Native();pointer=load(CHECKOUT/"artifacts/rust/engine/candidate.json")
    bundle=Path(pointer["directory"])
    checked(bundle/"candidate.json",pointer["manifest_sha256"])
    exe=checked(bundle/"eidolon-runtime.exe",pointer["executable_sha256"])
    job=DATA/"verification/rust"/name;job.mkdir(parents=True,exist_ok=False)
    out=job/"output";out.mkdir()
    if full:
        present=sum(p.stat().st_size for p in DATA.rglob("*") if p.is_file())
        reserve=70000000 if semantic else 510*8294400+159716352+80000000
        need(present+reserve<30000000000,"full capture exceeds 30GB reservation")
        keep=bytearray(27000)
        for record in native.frames:
            if "raw_zst" in record:keep[record["n"]]=1
        (job/"retention.bin").write_bytes(keep)
    sources={}
    for item in ("capture.c","live.c","hook.S","launch.c","live.py","semantic.c"):
        source=CHECKOUT/"tools/capture/rust"/item;shutil.copyfile(source,job/item);sources[item]=sha(source)
    compiler=subprocess.check_output(["i686-w64-mingw32-gcc","--version"],text=True).splitlines()[0]
    commands=[ ["i686-w64-mingw32-gcc","-O2","-msse2","-Wall","-Wextra","-shared","-Wl,--no-insert-timestamp",str(job/"capture.c"),str(job/"live.c"),str(job/"semantic.c"),str(job/"hook.S"),"-lopengl32","-ladvapi32","-o",str(job/"live.dll")],
               ["i686-w64-mingw32-gcc","-O2","-Wall","-Wextra","-Wl,--no-insert-timestamp",str(job/"launch.c"),"-lpsapi","-o",str(job/"launch.exe")] ]
    for command in commands:subprocess.run(command,check=True)
    scratch=Path("/tmp/opencode/eidolon/T24");scratch.mkdir(parents=True,exist_ok=True)
    prefix=DATA/"verification/rust/prefix"
    for previous in (DATA/"verification/rust").glob("live-*/state.json"):
        prior=load(previous)
        need(prior["phase"]=="closed","another live job still holds the GPU/prefix")
    for previous in (DATA/"verification/rust").glob("playback-*/state.json"):
        need(load(previous)["phase"]=="closed","uninstrumented playback still holds GPU/prefix")
    for previous in (DATA/"verification/rust").glob("resource-*/state.json"):
        need(load(previous)["phase"]=="closed","resource trace still holds GPU/prefix")
    if prefix.exists():shutil.rmtree(prefix)
    subprocess.run(["cp","-a","--reflink=auto",str(ROOT/".tools/capture/T11-prefix-baseline"),str(prefix)],check=True)
    link=scratch/"prefix"
    if not link.exists():link.symlink_to(prefix,target_is_directory=True)
    need(link.resolve()==prefix.resolve(),"unexpected T24 prefix")
    sink="eidolon_T24_rust"
    module=subprocess.check_output(["pactl","load-module","module-null-sink",f"sink_name={sink}"],text=True).strip()
    def win(p):return "Z:"+str(p).replace("/","\\")
    env=dict(os.environ,AGENT="T24",WINE_TIMEOUT="14400" if full else "480",WINEDEBUG="-all",PULSE_SINK=sink,
             EIDOLON_RUST_FRAMES=str(frames),WINEDLLOVERRIDES="winemenubuilder.exe,mscoree,mshtml=d")
    if fault:env["EIDOLON_RUST_FAULT"]=fault if isinstance(fault,str) else "mxcsr"
    if entry_fault:env["EIDOLON_ENTRY_FAULT"]=entry_fault
    if full:env.update(EIDOLON_RUST_FULL="1",EIDOLON_RUST_KEEP=win(job/"retention.bin"))
    if semantic:
        env.update(EIDOLON_RUST_SEMANTIC="1",EIDOLON_RUST_DIAGNOSTIC="1")
        if seed_fault:env["EIDOLON_SEED_FAULT"]="1"
    if physical_control:
        need(not full and not control,"physical controls are bounded diagnostics")
        env["EIDOLON_RUST_DIAGNOSTIC"]="1"
        env["EIDOLON_RUST_GL_FAULT" if physical_control=="gl" else "EIDOLON_RUST_POSITION_FAULT"]="1"
    command=["bash","tools/run","tools/wine-headless"]
    command += [str(exe),"--play"] if control else [str(job/"launch.exe"),win(exe),win(job/"live.dll"),win(out)]
    manifest=dict(schema="eidolon-rust-live-job-1",decision="D26",name=name,phase="running",pid=os.getpid(),sid=os.getsid(0),
                  started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),candidate_sha256=sha(exe),
                  candidate=str(exe),sources=sources,compiler=compiler,build_commands=commands,
                  helper_sha256=sha(job/"live.dll"),launcher_sha256=sha(job/"launch.exe"),
                  wine_launcher_sha256=sha(CHECKOUT/"tools/wine-headless"),command=command,
                  environment={k:env[k] for k in ("AGENT","WINE_TIMEOUT","WINEDEBUG","PULSE_SINK","EIDOLON_RUST_FRAMES","WINEDLLOVERRIDES")},
                  prefix_policy="fresh reflink copy of stopped T11 baseline before this invocation",
                  control=control,fault=fault,entry_fault=entry_fault,full=full,physical_control=physical_control,semantic=semantic,seed_fault=seed_fault,frames_requested=frames,reference_manifest_sha256=sha(native.path),
                  production_accepted=False)
    (job/"state.json").write_text(json.dumps(manifest,indent=2)+"\n")
    if full:
        manifest.update(storage=dict(existing_bytes=present,reserved_bytes=reserve,limit_bytes=30000000000),retention_sha256=sha(job/"retention.bin"))
    start=time.monotonic()
    try:
        with (job/"runner.log").open("wb") as log:
            process=subprocess.Popen(command,cwd=CHECKOUT,env=env,stdout=log,stderr=subprocess.STDOUT)
            manifest["runner_pid"]=process.pid;(job/"state.json").write_text(json.dumps(manifest,indent=2)+"\n")
            result=process.wait()
    finally:
        subprocess.run(["pactl","unload-module",module],check=False)
    manifest.update(phase="closed",exit_code=result,elapsed_seconds=time.monotonic()-start,
                    candidate_after_sha256=sha(exe),finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    output={str(p.relative_to(job)):dict(bytes=p.stat().st_size,sha256=sha(p)) for p in out.iterdir() if p.is_file()},
                    runner_log_sha256=sha(job/"runner.log"))
    (job/"state.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(json.dumps(dict(job=str(job),exit_code=result,elapsed_seconds=manifest["elapsed_seconds"])))
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("name");p.add_argument("--frames",type=int,default=3)
    p.add_argument("--control",action="store_true");p.add_argument("--fault",nargs="?",const="mxcsr",choices=["mxcsr","gpr"])
    p.add_argument("--entry-fault",choices=["mxcsr","gpr"])
    p.add_argument("--full",action="store_true")
    p.add_argument("--physical-control",choices=["gl","position"])
    p.add_argument("--semantic",action="store_true");p.add_argument("--seed-fault",action="store_true")
    a=p.parse_args();raise SystemExit(run(a.name,27000 if a.full else a.frames,a.control,a.fault,a.entry_fault,a.full,a.physical_control,a.semantic,a.seed_fault))
