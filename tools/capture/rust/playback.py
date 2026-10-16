#!/usr/bin/env python3
"""Uninjected production --play; external process/audio telemetry only."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"verify/rust"))
from conformance import CHECKOUT,DATA,ROOT,load,checked,sha,need


def run(name):
    pointer=load(CHECKOUT/"artifacts/rust/engine/candidate.json")
    bundle=Path(pointer["directory"]);checked(bundle/"candidate.json",pointer["manifest_sha256"])
    exe=checked(bundle/"eidolon-runtime.exe",pointer["executable_sha256"])
    root=DATA/"verification/rust";job=root/name;job.mkdir(exist_ok=False)
    for previous in root.glob("live-*/state.json"):need(load(previous)["phase"]=="closed","active GPU job")
    prefix=root/"prefix";scratch=Path("/tmp/opencode/eidolon/T24")
    need((scratch/"prefix").resolve()==prefix.resolve(),"unexpected prefix")
    if prefix.exists():shutil.rmtree(prefix) # Owned, reproducible stopped Wine prefix only.
    subprocess.run(["cp","-a","--reflink=auto",str(ROOT/".tools/capture/T11-prefix-baseline"),str(prefix)],check=True)
    sink="eidolon_T24_playback"
    module=subprocess.check_output(["pactl","load-module","module-null-sink",f"sink_name={sink}"],text=True).strip()
    env=dict(os.environ,AGENT="T24",WINE_TIMEOUT="1200",WINEDEBUG="-all",PULSE_SINK=sink,
             WINEDLLOVERRIDES="winemenubuilder.exe,mscoree,mshtml=d")
    command=["bash","tools/run","tools/wine-headless",str(exe),"--play"]
    shutil.copyfile(__file__,job/"playback.py")
    state=dict(schema="eidolon-rust-uninstrumented-1",phase="running",pid=os.getpid(),sid=os.getsid(0),
               started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),candidate=str(exe),candidate_sha256=sha(exe),
               command=command,source_sha256=sha(job/"playback.py"),wine_launcher_sha256=sha(CHECKOUT/"tools/wine-headless"),
               environment={k:env[k] for k in ("AGENT","WINE_TIMEOUT","WINEDEBUG","PULSE_SINK","WINEDLLOVERRIDES")},
               tools={"wine":subprocess.check_output(["wine","--version"],text=True).strip()},
               process=None,peak_rss_bytes=0,peak_hwm_bytes=0,first_audio_stream_seconds=None,production_accepted=False)
    def persist():(job/"state.json").write_text(json.dumps(state,indent=2)+"\n")
    persist();start=time.monotonic();target=None;maps_seen=set()
    try:
        with (job/"runner.log").open("wb") as log, (job/"telemetry.jsonl").open("w") as telemetry:
            process=subprocess.Popen(command,cwd=CHECKOUT,env=env,stdout=log,stderr=subprocess.STDOUT)
            state["runner_pid"]=process.pid;persist()
            while process.poll() is None:
                if target is None:
                    for p in Path("/proc").iterdir():
                        if not p.name.isdigit():continue
                        try:
                            if str(exe) in (p/"maps").read_text():target=p;state["process"]=int(p.name);break
                        except OSError:pass
                row=dict(seconds=round(time.monotonic()-start,3))
                if target:
                    try:
                        status=(target/"status").read_text().splitlines()
                        fields={line.split(":",1)[0]:line.split(":",1)[1].strip() for line in status}
                        row.update(rss_bytes=int(fields.get("VmRSS","0 kB").split()[0])*1024,hwm_bytes=int(fields.get("VmHWM","0 kB").split()[0])*1024)
                        state["peak_rss_bytes"]=max(state["peak_rss_bytes"],row["rss_bytes"])
                        state["peak_hwm_bytes"]=max(state["peak_hwm_bytes"],row["hwm_bytes"])
                        for line in (target/"maps").read_text().splitlines():
                            fields=line.split(maxsplit=5)
                            if len(fields)==6 and fields[5].startswith("/"):maps_seen.add(fields[5])
                    except OSError:pass
                inputs=json.loads(subprocess.check_output(["pactl","--format=json","list","sink-inputs"],text=True))
                streams=[s for s in inputs if s.get("properties",{}).get("application.process.id")==str(state["process"])]
                if streams:
                    row["audio_streams"]=streams
                    if state["first_audio_stream_seconds"] is None:state["first_audio_stream_seconds"]=row["seconds"]
                telemetry.write(json.dumps(row)+"\n");telemetry.flush();persist();time.sleep(1)
            state.update(exit_code=process.returncode,elapsed_seconds=time.monotonic()-start)
    finally:subprocess.run(["pactl","unload-module",module],check=False)
    state.update(phase="closed",candidate_after_sha256=sha(exe),runner_log_sha256=sha(job/"runner.log"),
                 telemetry_sha256=sha(job/"telemetry.jsonl"),finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 mapped_files={p:sha(p) for p in sorted(maps_seen) if Path(p).is_file()})
    persist();print(json.dumps(dict(job=str(job),exit_code=state["exit_code"],seconds=state["elapsed_seconds"])))


if __name__=="__main__":run(sys.argv[1])
