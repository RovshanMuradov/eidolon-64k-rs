#!/usr/bin/env python3
"""Verify an uninjected wall-clock playback and externally sampled baseline."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from conformance import CHECKOUT,DATA,load,checked,sha,need


def review(name):
    job=DATA/"verification/rust"/name;state=load(job/"state.json")
    need(state["phase"]=="closed" and state["exit_code"]==0,"playback not closed successfully")
    pointer=load(CHECKOUT/"artifacts/rust/engine/candidate.json")
    need(state["candidate_sha256"]==state["candidate_after_sha256"]==pointer["executable_sha256"],"production image identity")
    checked(Path(state["candidate"]),state["candidate_sha256"])
    checked(job/"playback.py",state["source_sha256"])
    checked(job/"runner.log",state["runner_log_sha256"]);checked(job/"telemetry.jsonl",state["telemetry_sha256"])
    need(state["command"]==["bash","tools/run","tools/wine-headless",state["candidate"],"--play"],"uninjected command")
    for path,digest in state["mapped_files"].items():checked(path,digest)
    need(state["candidate"] in state["mapped_files"] and not any(Path(p).name=="live.dll" for p in state["mapped_files"]),"candidate mapping/capture injection")
    log=(job/"runner.log").read_text(errors="replace")
    matches=re.findall(r"EIDOLON_RUNTIME mode=playback reason=natural_exit queries=(\d+) frames=(\d+) terminal_cursor=(\d+)",log)
    need(len(matches)==1,"natural endpoint")
    queries,frames,cursor=map(int,matches[0])
    need(queries==frames+1 and frames>0 and 19845000<=cursor<19964544,"live-clock terminal range/count")
    need("WINE_EXIT=0 GAMESCOPE_EXIT=0" in log,"launcher exit")
    need(not re.search(r"TIMEOUT|Unhandled exception|EIDOLON_RUNTIME error:|cleanup failed:|waveOutClose failed:",log),"runtime error")
    rows=[json.loads(line) for line in (job/"telemetry.jsonl").read_text().splitlines()]
    need(all(a["seconds"]<b["seconds"] for a,b in zip(rows,rows[1:])),"external sample order")
    audio=[r for r in rows if r.get("audio_streams")]
    need(bool(audio),"actual audio stream not observed")
    for row in audio:
        for stream in row["audio_streams"]:
            need(stream["properties"]["application.process.id"]==str(state["process"]),"stream process identity")
            need(stream["properties"]["target.object"]=="eidolon_T24_playback","private sink identity")
            need(stream["sample_specification"]=="float32le 2ch 44100Hz" and not stream["corked"],"live playback format/state")
    leftovers=[]
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():continue
        try:
            if b"WINEPREFIX=/tmp/opencode/eidolon/T24/prefix" in (p/"environ").read_bytes().split(b"\0") and "wine" in str((p/"exe").resolve()):leftovers.append(int(p.name))
        except OSError:pass
    sinks=subprocess.check_output(["pactl","list","short","sinks"],text=True)
    need(not leftovers and "eidolon_T24_playback" not in sinks,"playback cleanup incomplete")
    result=dict(status="UNINSTRUMENTED_PLAYBACK_BASELINE",candidate_sha256=state["candidate_sha256"],
                job=name,state_sha256=sha(job/"state.json"),frames=frames,queries=queries,terminal_cursor=cursor,
                executable_bytes=Path(state["candidate"]).stat().st_size,launch_to_first_audio_seconds=audio[0]["seconds"],
                first_audio_to_last_sample_seconds=audio[-1]["seconds"]-audio[0]["seconds"],
                terminal_audio_seconds=cursor/44100,mean_present_fps=frames/(cursor/44100),
                launcher_wall_seconds=state["elapsed_seconds"],host_process_peak_rss_bytes=state["peak_rss_bytes"],
                host_process_peak_hwm_bytes=state["peak_hwm_bytes"],sample_interval_max_seconds=max(b["seconds"]-a["seconds"] for a,b in zip(rows,rows[1:])),
                audio_samples_observed=len(audio),mapped_file_count=len(state["mapped_files"]),cleanup_verified=True,
                environment=dict(wine=state["tools"]["wine"],command=state["command"],launcher=state["environment"],
                                 context_log_lines=[line for line in log.splitlines() if line.startswith(("GL renderer:","GL version:")) or "gamescope version" in line]),
                limitations=["External approximately one-second sampling; first audio stream is not an internal synth-completion timestamp",
                             "Private null sink verifies actual live-clock device submission, not physical-speaker output",
                             "Loaded mappings are observed closure, not a syscall-complete file-access trace",
                             "Startup overlapped bounded host rebuild/state-audit work; this is a measured baseline, not an isolated microbenchmark"],production_accepted=False)
    (CHECKOUT/"artifacts/verification/rust/playback.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))


if __name__=="__main__":review(sys.argv[1])
