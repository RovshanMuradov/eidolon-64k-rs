#!/usr/bin/env python3
"""Offline strict parser for the prepared capture helper's binary event ledger."""
import argparse
import json
from pathlib import Path
import struct
from conformance import Native, N, need, fields, load, binding, checked, ref, exact_files, PCM_BYTES


def events(path):
    with Path(path).open("rb") as stream:
        need(stream.read(8) == b"EIDCAP01", "capture event magic")
        sequence, thread = 0, None
        while header := stream.read(16):
            need(len(header) == 16, "truncated event header")
            seq, tid, kind, size = struct.unpack("<4I", header)
            sizes = {1:284,2:284,3:284,4:284,5:284,6:32,7:32,8:36,9:32,10:64}
            need(kind in sizes and size == sizes[kind], "event kind/extent")
            need(seq == sequence+1 and tid > 0 and (thread is None or tid == thread), "event sequence/thread")
            payload = stream.read(size); need(len(payload) == size, "truncated event payload")
            sequence, thread = seq, tid
            yield kind, payload


def audit(path, native, times):
    records = iter(events(path))
    def take(kind):
        event = next(records, None)
        need(event is not None and event[0] == kind, f"missing/reordered event {kind}")
        return event[1]
    pcm_hash = bytes.fromhex(native.manifest["audio"]["sha256"])
    need(take(6) == pcm_hash and take(7) == pcm_hash, "PCM render/submission differs")
    initial = take(1)
    need(initial[28:] == native.states["first-query/physics"].read_bytes() and struct.unpack_from("<2I",initial) == (0,0), "initial state")
    rows = [i for i,r in enumerate(native.manifest["scenes"]) for _ in range(r["last"]-r["first"]+1)]
    need(len(times) == N, "native vector extent")
    for n, cursor, seconds, local, _ in times:
        query = take(2); words = struct.unpack("<7I",query[:28])
        need(words[:3] == (n,cursor,seconds) and words[4:6] == (rows[n],local), f"native marker time/row {n}")
        need(take(3) == query, "pre-present state differs from query")
        layout = struct.unpack("<16I",take(10))
        need(layout == (n,1920,1080,8,8,8,8,0,0,0,0,0,0x405,0,0,0), "GL readback layout")
        pixels = take(8)
        need(struct.unpack_from("<I",pixels)[0] == n and pixels[4:] == bytes.fromhex(native.frames[n]["sha256"]), f"native pixel hash {n}")
        need(take(4) == query, "post-present state differs")
    endpoint = struct.unpack("<7I",take(5)[:28])
    need(endpoint[:5] == (N,19845000,0x43e10000,0x44160000,0xffffffff), "terminal query")
    need(take(9) == pcm_hash, "later source-memory PCM stability")
    need(next(records,None) is None, "extra capture events")
    return dict(status="RUNTIME_LEDGER_CONFORMANCE_ONLY", frames=N, queries=N+1, pcm_stability_observations=3,
                reference_accepted=True, production_accepted=False,
                pending=["raw pixel and PCM files", "actual process-exit/identity envelope", "live instrumentation restoration"],
                unchecked=["post-update physics/uniform native semantics", "marker beat/dt except terminal"])


def envelope(path, request_digest):
    root, value = Path(path).resolve().parent, load(path)
    fields(value, "schema status request events pcm process")
    need(value["schema"] == "eidolon-rust-runtime-envelope-1" and value["status"] == "CLOSED", "runtime envelope is unexecuted/unclosed")
    need(value["request"]["sha256"] == request_digest, "request is not independently pinned")
    request_path = binding(root, value["request"])
    request = load(request_path); directory = request_path.parent
    need(request["schema"] == "eidolon-rust-capture-request-1" and request["mode"] == "play-controlled-sample-cursor", "capture request mode")
    for name, digest in request["files"].items(): checked(ref.payload_path(directory,name),digest)
    native = Native()
    process = value["process"]
    fields(process, "command environment exe_before_sha256 exe_after_sha256 exit_code timeout dropped_frames dropped_audio_sample_frames evidence")
    ref.require(ref.exact_equal(process["command"],request["command"]),"executed command differs")
    ref.require(ref.exact_equal(process["environment"],native.manifest["conditions"]["environment"]),"observed runtime environment differs")
    for key in ("exe_before_sha256","exe_after_sha256"):
        need(process[key] == request["executable"]["sha256"],"observed shipped EXE identity")
    for key in ("exit_code","dropped_frames","dropped_audio_sample_frames"):
        need(type(process[key]) is int and process[key] == 0,"nonzero exit/loss")
    need(process["timeout"] is False,"timed-out run")
    evidence = binding(root,process["evidence"]); need(evidence.stat().st_size>0,"missing process observation evidence")
    event_path = binding(root,value["events"])
    result = audit(event_path,native,native.times())
    exact_files(native.pcm,binding(root,value["pcm"]),PCM_BYTES)
    retained = 0
    for record in native.frames:
        if "raw_zst" in record:
            p = ref.payload_path(event_path.parent,f"frame-{record['n']:05d}.raw")
            need(p.stat().st_size == 8294400,"raw frame extent")
            checked(p,record["sha256"]); retained += 1
    result.update(status="BOUND_RUNTIME_FILES_ONLY",retained_raws=retained,runtime_evidence_authenticated=False,
                  pending=["independent actual launch/exit/source-memory/hook/ABI/GL-restoration evidence review"])
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("path",type=Path)
    p.add_argument("--request-sha256")
    args=p.parse_args()
    if args.request_sha256: result=envelope(args.path,args.request_sha256)
    else:
        native=Native(); result=audit(args.path,native,native.times())
    print(json.dumps(result))
