#!/usr/bin/env python3
"""Read-only, one-shot reconciliation of the existing D26 full job.

Only complete records from a bounded read of the growing ledger are inspected.
No process is started, signalled, attached, resumed or stopped by this checker.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import zstandard

from conformance import CHECKOUT, DATA, N, PIN, PCM_BYTES, Native, checked, exact_files, load, need, sha, ref

TIME_PIN = "363ca20b3e537f57da1d0dd937a3e1fc9f3c92e3377af9c7d8d12706186cf406"
SIZES = {1:284,2:284,3:284,4:284,5:284,6:32,7:32,8:36,9:32,10:64}


def exact_retained(native_path, actual_path, expected_hash):
    decoder=zstandard.ZstdDecompressor().decompressobj()
    raw=decoder.decompress(native_path.read_bytes())
    need(decoder.eof and not decoder.unused_data,"native raw compression extent")
    need(len(raw)==8294400 and hashlib.sha256(raw).hexdigest()==expected_hash,"native retained raw identity")
    need(actual_path.read_bytes()==raw,"retained raw byte mismatch")


def closure_status(exit_code, complete, natural, errors, differences, cleanup):
    if exit_code != 0 or errors:
        return "CLOSED_FAILED"
    if not complete or not natural:
        return "CLOSED_INCOMPLETE"
    if differences:
        return "CLOSED_WITH_DIFFERENCES"
    if cleanup["wine_pids"] or cleanup["private_sink_present"] or cleanup["runner_alive"] or cleanup.get("session_pids"):
        return "CLOSED_EXACT_FILES_CLEANUP_PENDING"
    return "CLOSED_EXACT_FILES"


def native_times(native):
    path = DATA / "verification/rust/native-times.bin"
    if not path.exists():
        raw = b"".join(struct.pack("<5I", *item) for item in native.times())
        need(hashlib.sha256(raw).hexdigest() == TIME_PIN, "native time projection identity")
        # Verifier-owned reproducible cache, never an acquisition output.
        with path.open("xb") as f:
            f.write(raw)
    raw = checked(path, TIME_PIN).read_bytes()
    need(len(raw) == N * 20, "native time vector extent")
    return list(struct.iter_unpack("<5I", raw))


def bounded_records(raw, closed=False):
    if len(raw) < 8:
        need(not closed and b"EIDCAP01".startswith(raw), "capture magic/truncation")
        return [], len(raw)
    need(raw[:8] == b"EIDCAP01", "capture magic")
    at, sequence, thread, records = 8, 0, None, []
    while at < len(raw):
        if len(raw) - at < 16:
            break
        seq, tid, kind, size = struct.unpack_from("<4I", raw, at)
        need(kind in SIZES and size == SIZES[kind], "record kind/extent")
        need(seq == sequence + 1 and tid > 0 and (thread is None or thread == tid), "record sequence/thread")
        if len(raw) - at - 16 < size:
            break
        records.append((kind, raw[at+16:at+16+size]))
        sequence, thread, at = seq, tid, at + 16 + size
    need(not closed or at == len(raw), "closed ledger is truncated")
    return records, len(raw)-at


def prefix(records, native, times):
    rows = [i for i, r in enumerate(native.manifest["scenes"]) for _ in range(r["last"]-r["first"]+1)]
    expected_pcm = bytes.fromhex(native.manifest["audio"]["sha256"])
    result = dict(records=len(records), queries=0, post_presents=0, frame_hashes=0,
                  matching_frame_hashes=0, frame_mismatches=0, first_frame_mismatch=None,
                  time_mismatches=0, first_time_mismatch=None, initial_physics=None,
                  pcm_digest_observations=0, endpoint=False, terminal_stability=False)
    query, hashes = None, {}
    for i, (kind, payload) in enumerate(records):
        if i < 3:
            need(kind == (6,7,1)[i], "initial event order")
            if kind in (6,7):
                need(payload == expected_pcm, "native PCM digest differs")
                result["pcm_digest_observations"] += 1
            else:
                need(struct.unpack_from("<2I",payload) == (0,0), "initial clock")
                result["initial_physics"] = payload[28:] == native.states["first-query/physics"].read_bytes()
                need(result["initial_physics"], "native initial physics differs")
            continue
        n, position = divmod(i-3, 5)
        if n < N:
            need(kind == (2,3,10,8,4)[position], f"frame {n} event order")
            if kind == 2:
                query = payload
                header = struct.unpack("<7I",payload[:28])
                need(header[0] == n, "query frame number")
                native_n, cursor, seconds, local, _token = times[n]
                if header[:3] != (native_n,cursor,seconds) or header[4:6] != (rows[n],local):
                    result["time_mismatches"] += 1
                    if result["first_time_mismatch"] is None:
                        result["first_time_mismatch"] = dict(n=n, actual=list(header), expected_native=[native_n,cursor,seconds,rows[n],local])
                result["queries"] += 1
            elif kind in (3,4):
                need(payload == query, f"frame {n} query/pre/post snapshot changed")
                if kind == 4:
                    result["post_presents"] += 1
            elif kind == 10:
                need(struct.unpack("<16I",payload) == (n,1920,1080,8,8,8,8,0,0,0,0,0,0x405,0,0,0), "GL layout")
            else:
                need(struct.unpack_from("<I",payload)[0] == n, "pixel frame number")
                actual, expected = payload[4:].hex(), native.frames[n]["sha256"]
                hashes[n] = actual; result["frame_hashes"] += 1
                if actual == expected:
                    result["matching_frame_hashes"] += 1
                else:
                    result["frame_mismatches"] += 1
                    if result["first_frame_mismatch"] is None:
                        result["first_frame_mismatch"] = dict(n=n, actual=actual, expected=expected, row=rows[n])
        else:
            offset = i-3-N*5
            need(offset < 2 and kind == (5,9)[offset], "extra/invalid terminal events")
            if kind == 5:
                need(struct.unpack("<7I",payload[:28])[:5] == (N,19845000,0x43e10000,0x44160000,0xffffffff), "terminal native time/row")
                result["queries"] += 1; result["endpoint"] = True
            else:
                need(payload == expected_pcm, "terminal source-memory PCM differs")
                result["pcm_digest_observations"] += 1; result["terminal_stability"] = True
    return result, hashes


def process(pid):
    directory = Path("/proc") / str(pid)
    if not directory.exists():
        return dict(pid=pid, exists=False)
    try:
        stat = (directory / "stat").read_text().rsplit(") ",1)[1].split()
        env = (directory/"environ").read_bytes().split(b"\0")
        selected = {key:value for entry in env if b"=" in entry for key,value in [entry.decode(errors="replace").split("=",1)]
                    if key in ("AGENT","EIDOLON_RUST_FULL","EIDOLON_RUST_FRAMES","EIDOLON_RUST_KEEP","PULSE_SINK")}
        return dict(pid=pid, exists=True, state=stat[0], ppid=int(stat[1]), sid=os.getsid(pid),
                    start_ticks=int(stat[19]), command=(directory/"cmdline").read_bytes().replace(b"\0",b" ").decode().strip(),
                    cwd=str((directory/"cwd").resolve()),environment=selected)
    except FileNotFoundError:
        return dict(pid=pid,exists=False)


def live_images(candidate, helper):
    result=[]
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():continue
        try:
            if b"WINEPREFIX=/tmp/opencode/eidolon/T24/prefix" not in (p/"environ").read_bytes().split(b"\0"):continue
            maps=(p/"maps").read_text()
            if candidate not in maps:continue
            lines=[line for line in maps.splitlines() if candidate in line or str(helper) in line]
            executable=(p/"exe").resolve()
            result.append(dict(pid=int(p.name),candidate_mapped=True,helper_mapped=str(helper) in maps,
                               mappings=lines,wine_executable=str(executable),wine_executable_sha256=sha(p/"exe")))
        except (OSError,PermissionError):pass
    return result


def observe(pointer_path):
    pointer = load(pointer_path)
    request_path = checked(DATA / pointer["request"], pointer["request_sha256"])
    request = load(request_path)
    state_path = Path(pointer["state"]); state_raw=state_path.read_bytes();state=ref.load_json(state_raw)
    directory = state_path.parent; output = directory/"output"
    need(state["pid"] == state["sid"] == pointer["pid"] == request["pid"] == 2440688, "job PID/SID identity")
    need(state["name"] == "live-d26-full01" and state["full"] is True and state["frames_requested"] == N, "wrong job/mode")
    need(state["reference_manifest_sha256"] == PIN, "native reference identity")
    checked(Path(state["candidate"]),state["candidate_sha256"])
    candidate = load(CHECKOUT/"artifacts/rust/engine/candidate.json")
    need(state["candidate_sha256"] == candidate["executable_sha256"], "published candidate differs")
    for name,digest in state["sources"].items():
        need(request["sources"][name] == digest, "launch/source snapshot differs")
        checked(directory/name,digest)
    checked(directory/"live.dll",state["helper_sha256"])
    checked(directory/"launch.exe",state["launcher_sha256"])
    checked(CHECKOUT/"tools/wine-headless",state["wine_launcher_sha256"])
    checked(directory/"retention.bin",state["retention_sha256"])
    processes = [process(state[key]) for key in ("pid","runner_pid")]
    running = state["phase"] == "running"
    if running:
        need(processes[0]["exists"] and processes[0]["sid"] == state["sid"] and processes[0]["state"] != "Z", "lost/reused full supervisor")
        need("tools/capture/rust/live.py live-d26-full01 --full" in processes[0]["command"] and processes[0]["cwd"] == str(CHECKOUT), "supervisor command/directory changed")
        if processes[1]["exists"]:
            need(processes[1]["sid"] == state["sid"] and processes[1]["ppid"] == state["pid"] and "tools/wine-headless" in processes[1]["command"], "runner process identity")
            for key,value in dict(AGENT="T24",EIDOLON_RUST_FULL="1",EIDOLON_RUST_FRAMES="27000",PULSE_SINK="eidolon_T24_rust").items():
                need(processes[1]["environment"].get(key)==value,"actual runner mode/environment changed")
    native = Native(); times = native_times(native)
    ledger = output/"events.bin"
    if ledger.exists():
        with ledger.open("rb") as stream:
            boundary = os.fstat(stream.fileno()).st_size
            raw = stream.read(boundary)
    else:
        raw = b""
    records, pending = bounded_records(raw,closed=not running)
    progress, hashes = prefix(records,native,times)
    complete = progress["post_presents"]
    raws, raw_native_mismatches, gl_witnesses, exact_raws = 0, [], 0, 0
    for n in range(complete):
        witness = output/f"gl-{n:05d}.bin"
        values = struct.unpack("<18i",witness.read_bytes())
        need(values[:9] == values[9:],f"GL restoration differs at {n}"); gl_witnesses += 1
        if "raw_zst" in native.frames[n]:
            frame = output/f"frame-{n:05d}.raw"
            need(frame.stat().st_size == 8294400, "retained raw extent")
            digest = sha(frame); need(digest == hashes[n],"raw/hash ledger inconsistency")
            raws += 1
            if digest != native.frames[n]["sha256"]:
                raw_native_mismatches.append(n)
            if not running:
                exact_retained(ref.payload_path(native.directory,native.frames[n]["raw_zst"]),frame,native.frames[n]["sha256"])
                exact_raws+=1
    pcm = "not-yet-complete"
    if progress["pcm_digest_observations"]:
        exact_files(native.pcm,output/"pcm.f32le",PCM_BYTES); pcm = "EXACT_NATIVE_PCM"
    restoration = {}
    for name,a,b,start,end in (("entry_gpr","entry-before.bin","entry-after.bin",0,36),
                              ("entry_fp","entry-before.bin","entry-after.bin",64,576),
                              ("marker_gpr","marker-before-gpr.bin","marker-restored-gpr.bin",0,36),
                              ("marker_fp","marker-before-fx.bin","marker-restored-fx.bin",0,512)):
        if (output/a).exists() and (output/b).exists():
            first,second=(output/a).read_bytes(),(output/b).read_bytes()
            need(len(first)>=end and len(second)>=end and first[start:end]==second[start:end],name+" physical restoration")
            restoration[name] = True
    if complete:
        need(set(restoration)=={"entry_gpr","entry_fp","marker_gpr","marker_fp"},"missing physical restoration witnesses")
    log = (directory/"runner.log").read_text(errors="replace")
    errors = [line for line in log.splitlines() if re.search(r"HOOK_(?:FP|GPR)_MISMATCH|LAUNCH_FAILURE|EIDOLON_RUNTIME error:|CAPTURE_GL_|CAPTURE_EVENT.*rc=[1-9]|Unhandled exception|TIMEOUT after|waveOut cleanup failed:|waveOutClose failed:",line)]
    current_bytes = sum(p.stat().st_size for p in DATA.rglob("*") if p.is_file())
    need(current_bytes < 30000000000,"30GB data limit exceeded")
    timings = [line for line in log.splitlines() if line.startswith(("RUNTIME_TIMING","CHILD_METRICS","EIDOLON_RUNTIME mode=","CHILD_EXIT","WINE_EXIT="))]
    result = dict(schema="eidolon-rust-full-observation-1",observed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  status="ACTIVE_PREFIX_CHECKED" if running else "CLOSED_REQUIRES_REVIEW",phase=state["phase"],
                  pointer_sha256=sha(pointer_path),request_sha256=sha(request_path),state_snapshot_sha256=hashlib.sha256(state_raw).hexdigest(),
                  candidate_sha256=state["candidate_sha256"],identities_rehashed=True,processes=processes,
                  live_mappings=live_images(state["candidate"],directory/"live.dll"),
                  ledger_snapshot_bytes=len(raw),ledger_snapshot_sha256=hashlib.sha256(raw).hexdigest(),pending_record_bytes=pending,
                  progress=progress,retained_raws_checked=raws,retained_native_mismatches=raw_native_mismatches,
                  retained_raws_byte_compared=exact_raws,
                  gl_restoration_witnesses=gl_witnesses,pcm=pcm,physical_restoration=restoration,errors=errors,timing_lines=timings,
                  storage=dict(current_bytes=current_bytes,launch_reserved_total=state["storage"]["existing_bytes"]+state["storage"]["reserved_bytes"],limit_bytes=30000000000),
                  native_post_update_state_verified=False,production_accepted=False,gpu_reservation="T24 exclusive; preserve through closure/cleanup")
    if errors or progress["frame_mismatches"] or progress["time_mismatches"]:
        result["status"] = "ACTIVE_WITH_DIFFERENCES" if running else "CLOSED_WITH_DIFFERENCES"
    if not running:
        need(state["phase"] == "closed", "unknown producer state")
        result["exit_code"] = state["exit_code"]
        for name,item in state["output"].items():checked(directory/name,item["sha256"])
        checked(directory/"runner.log",state["runner_log_sha256"])
        need(state["candidate_after_sha256"] == state["candidate_sha256"],"post-run EXE differs")
        result["complete_capture"] = complete == N and progress["endpoint"] and progress["terminal_stability"] and raws == 510
        prefix_path = b"WINEPREFIX=/tmp/opencode/eidolon/T24/prefix"
        leftovers,session_pids = [],[]
        for p in Path("/proc").iterdir():
            if not p.name.isdigit():continue
            try:
                if os.getsid(int(p.name))==state["sid"]:session_pids.append(int(p.name))
                if prefix_path in (p/"environ").read_bytes().split(b"\0") and "wine" in str((p/"exe").resolve()):leftovers.append(int(p.name))
            except (OSError,PermissionError):pass
        sinks = subprocess.check_output(["pactl","list","short","sinks"],text=True)
        result["cleanup"] = dict(wine_pids=leftovers,session_pids=session_pids,private_sink_present="eidolon_T24_rust" in sinks,runner_alive=processes[1]["exists"])
        terminal="EIDOLON_RUNTIME mode=playback reason=natural_exit queries=27001 frames=27000 terminal_cursor=19845000"
        result["natural_exit_log"] = terminal in log and "CHILD_EXIT 0 entry_proof=1" in log and "WINE_EXIT=0 " in log and "PLANNED_SHORT_STOP" not in log
        result["status"]=closure_status(state["exit_code"],result["complete_capture"],result["natural_exit_log"],errors,
                                        progress["frame_mismatches"] or progress["time_mismatches"],result["cleanup"])
        startup={int(k):int(ms) for k,ms in re.findall(r"RUNTIME_TIMING kind=(\d+) elapsed_ms=(\d+)",log)}
        metrics=re.search(r"CHILD_METRICS peak_working_set_bytes=(\d+) wall_ms=(\d+)",log)
        result["performance"] = dict(executable_bytes=Path(state["candidate"]).stat().st_size,
                                   startup_pcm_ready_ms=startup.get(6),timeline_ready_ms=startup.get(1),terminal_marker_ms=startup.get(5),
                                   child_peak_working_set_bytes=int(metrics[1]) if metrics else None,
                                   child_wall_ms=int(metrics[2]) if metrics else None,
                                   runner_elapsed_seconds=state["elapsed_seconds"],scope="instrumented controlled-clock run; not an uninstrumented baseline")
        if 1 in startup and 5 in startup and startup[5]>startup[1]:
            result["performance"]["controlled_present_interval_ms"]=startup[5]-startup[1]
            result["performance"]["controlled_mean_fps"]=N*1000/(startup[5]-startup[1])
    return result


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pointer",type=Path,default=CHECKOUT/"artifacts/verification/rust/full-job.json")
    p.add_argument("--result",type=Path,default=CHECKOUT/"artifacts/verification/rust/full-progress.json")
    args=p.parse_args()
    try:
        result=observe(args.pointer)
    except (OSError,ValueError,KeyError,struct.error) as exc:
        result=dict(schema="eidolon-rust-full-observation-1",status="RECONCILIATION_FAILURE",
                    observed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),reason=str(exc),production_accepted=False)
    args.result.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,sort_keys=True))
    raise SystemExit(int(result["status"]=="RECONCILIATION_FAILURE"))
