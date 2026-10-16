#!/usr/bin/env python3
"""Independent closed-run review; no producer imports, target execution or live polling.

Only explicitly pinned, published runs are read. One valid run is never G6.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys

import zstandard

if __package__:
    from . import review_d12 as d12
else:
    import review_d12 as d12

ref, compat, stage, short = d12.ref, d12.compat, d12.stage, d12.short
require, checked, load, one = d12.require, d12.checked, d12.load, d12.one
N = 27000
PINS = {"proxy-b-d13-detached-20261016-1": {
    "reference": "36c1f7f330682bb4f818ad22cd0dab99359ffcdf2b4abc60cfb9381d98e37c64",
    "preflight": "a85a56842220a8f538e0658803e766d74ff9a37a96a2817a2e93db8babae8abf",
    "native-return": "ef0280963c5604af28688ec550f25c514fe9c29609d8daf133d681a361205801",
    "request": "3760ae0c29403a79b23260216fd5d99aad78da9ff085cd94f4501a86d24a798c",
    "state": "d68e773a988b7b21d3ea1583dc0548a36275d3d254cb703b43ebcfb9780b4fc6",
}}


def decoded_lines(path):
    """Reject truncated, concatenated, trailing and unterminated JSONL streams."""
    decoder = zstandard.ZstdDecompressor().decompressobj()
    pending = b""
    with path.open("rb") as source:
        while block := source.read(65536):
            require(not decoder.eof, "trailing compressed stream")
            decoded = decoder.decompress(block)
            require(not decoder.unused_data, "concatenated/trailing compressed stream")
            lines = (pending+decoded).split(b"\n")
            pending = lines.pop()
            require(len(pending) < 1024*1024, "oversize observation line")
            for line in lines:
                require(line, "empty observation line")
                yield line+b"\n"
    require(decoder.eof and not pending, "truncated compressed/JSONL stream")


def check_sequence(e, sequence, pid):
    require(type(e["pid"]) is int and e["pid"] == pid, "mixed process identity")
    if "seq" not in e:
        require(e["event"] == "backend_probe" and e["result"] == "distinct_backend"
                and e["error"] == 0, "invalid out-of-band probe")
        return sequence
    require(type(e["seq"]) is int and e["seq"] == sequence+1, "event sequence gap/order")
    require(e["event"] not in ("failure", "gl_error", "fault_injected", "planned_partial_stop"), "failed/partial stream")
    return sequence+1


def stream(path, description):
    checked(path, description["sha256"])
    require(description["format"] == "zstandard-single-frame-jsonl", "stream format")
    digest, size, sequence, pid = hashlib.sha256(), 0, 0, None
    counts, lookups, events = Counter(), Counter(), []
    for line in decoded_lines(path):
        digest.update(line); size += len(line)
        e = ref.load_json(line)
        if pid is None:
            pid = e["pid"]
        sequence = check_sequence(e, sequence, pid)
        counts[e["event"] if "seq" in e else "out_of_band_backend_probe"] += 1
        if e["event"] == "lookup":
            lookups[e["api"]] += 1
            require(e.get("resolved", True) is True, "unresolved lookup")
            if e.get("name") != "glCreateShaderProgramv" and e["api"] != "GetProcAddress":
                continue
        events.append(e)
    require(sequence == description["events"] and dict(counts) == description["event_counts"], "stream coverage")
    require(size == description["decoded_bytes"] and digest.hexdigest() == description["decoded_sha256"], "decoded stream identity")
    require(counts["out_of_band_backend_probe"] == 2, "backend probe coverage")
    return events, counts+lookups


def check_endpoint(events, directory, image):
    g = stage.group(events)
    require(not any(g[k] for k in ("failure", "gl_error", "fault_injected", "planned_partial_stop")), "not a native full end")
    end, forward, full = [one(events, k) for k in ("native_endpoint", "native_exit_forward", "full_run")]
    expected = dict(caller=0x40861e, exit_call=0x408618, exit_code=0, frames=N, queries=N+1,
                    last_present=N-1, terminal_query=N, sample_cursor=19845000, eax=0xffffffff, edi=0,
                    seconds_f32_bits=0x43e10000, beat_f32_bits=0x44160000,
                    original_source_sha256=compat.SOURCE_HASH, dropped_frames=0, dropped_audio_sample_frames=0, errors=[])
    require(all(ref.exact_equal(end[k], v) for k, v in expected.items()), "native endpoint operands/counts")
    require(full["wrapper_stop_enabled"] is False and full["presents"] == N and full["queries"] == N+1
            and full["exit_call"] == 0x408618 and full["exit_slot"] == 0x409030, "endpoint hook configuration")
    require(forward["caller"] == end["caller"] and forward["exit_code"] == 0
            and forward["registers_fp_equal"] is True and forward["tail_jump_original_slot"] is True, "native exit forwarding")
    require(len(g["pre_present"]) == len(g["post_present"]) == N
            and g["post_present"][-1]["n"] == N-1, "terminal present coverage")
    clocks = [e for e in g["clock"] if e["api"] == "waveOutGetPosition"]
    require(len(clocks) == N+1 and clocks[-1]["n"] == N and clocks[-1]["value"] == 19845000
            and clocks[-1]["wType"] == 2 and clocks[-1]["caller"] == "0x00407b97", "terminal native query")
    require(g["post_present"][-1]["seq"] < clocks[-1]["seq"] < end["seq"] < forward["seq"]
            and end["tid"] == forward["tid"] == clocks[-1]["tid"] == one(events, "compat_context")["tid"], "terminal ordering/thread")
    for kind, size in (("gpr", 36), ("fx", 512)):
        a, b = [(directory/f"native-exit-{side}-{kind}.bin").read_bytes() for side in ("before", "after")]
        require(len(a) == size and a == b, "native exit physical restoration")
        if kind == "gpr":
            require(d12.u32(a) == 0 and d12.u32(a, 28) == 0xffffffff, "native exit raw registers")
        else:
            require(d12.u32(a, 176) == 0x44160000 and d12.u32(a, 192) == 0x43e10000, "native exit raw SIMD operands")
    locals_ = (directory/"native-exit-locals.bin").read_bytes()
    require(len(locals_) == 0x38 and d12.u32(locals_, 4) == 0x43e10000, "native exit raw local seconds")
    require(image[0x7c1d:0x7c26].hex() == "83f8ff0f84f1090000"
            and image[0x8617:0x861f].hex() == "57ff1530904000cc", "original native end branch/call")
    terminal = [e for e in g["abi_canary"] if e["api"] == 4 and e["n"] == N]
    require(len(terminal) == 1 and terminal[0]["ordinal"] == N+1
            and clocks[-1]["seq"] < terminal[0]["seq"] < end["seq"], "terminal physical query return")


def check_durable(pre, returned, state, request, m, bundle):
    require(state["phase"] == "complete" and state["exit_code"] == 0
            and state["run_id"] == returned["run_id"] == pre["run_id"] == m["run_id"] == bundle["run_id"], "unclosed/wrong job")
    require(state["pid"] == state["sid"] and request["created_utc"] < pre["started_utc"]
            < returned["finished_utc"] <= m["finished_utc"] < state["updated_utc"], "durable launch/return ordering")
    require(m["status"] == "complete" and m["full_run"] is True and m["first_failed_check"] is None
            and m["launcher_exit"] == returned["launcher_exit"] == 0
            and m["supervisor_timeout"] is returned["supervisor_timeout"] is False, "actual process outcome")
    for k in ("started_utc", "command", "build", "host_runner", "environment", "supervision", "dependency"):
        require(pre[k] == m[k], f"original preflight differs: {k}")
    args, identity = pre["arguments"], m["executed_file_observation"]
    require(args["full"] is True and args["fault"] is None and args["mode"] == "450-compatibility"
            and args["reference_variant"] == m["reference_variant"] == bundle["source"]["kind"] == "D9-restored-native"
            and args["storage"] == m["storage"] == bundle["video"]["storage"], "original launch settings")
    require(identity["path"] == pre["command"][-1] and m["input"] == dict(pre["input"], executed_copy=identity["path"]), "original executable path")
    require(pre["exe_before_sha256"] == identity["before_sha256"] == returned["exe_after_sha256"]
            == identity["after_sha256"] == ref.ORIGINAL_SHA256, "original pre/post executable identity")
    require(pre["fresh_tree_equal"] is True and pre["prefix_inventory_sha256"] == m["prefix_baseline"]["inventory_sha256"], "original fresh prefix")
    require(pre["launcher_sha256"] == bundle["source"]["inputs"]["launcher"], "original launcher identity")
    for k in ("prefix_processes_released", "private_sink_unloaded"):
        require(returned[k] is m["resources"][k] is True, "original resource closure")
    require(returned["errors"] == m["resources"]["errors"] == [], "resource closure errors")
    command = request["command"]
    require(command[:6] == ["setsid", "nohup", "bash", "tools/run", "python", "-u"]
            and command[-1] == "--execute-job"
            and command[command.index("--run-id")+1] == bundle["run_id"]
            and command[command.index("--storage")+1] == bundle["video"]["storage"], "original detached command")


def check_retention(bundle, frames, directory):
    retained = {r["n"] for r in frames if "raw_zst" in r}
    required = set(range(0, N, 60)) | {s[k] for s in bundle["scenes"] for k in ("first", "last")}
    expected = required if bundle["video"]["storage"] == "reference" else set()
    require(retained == expected and len(required) == 510, "full sparse retention")
    actual = [int(line) for line in (directory/"retention.txt").read_text().splitlines()]
    require(actual == sorted(expected), "original retention input differs")
    return retained


def review_run(run_id, roots):
    pins = PINS[run_id]  # An unpublished run is not an input.
    artifacts, directory = roots["checkout"]/"artifacts/reference", roots["data"]/"reference"/run_id
    path = checked(artifacts/f"{run_id}-reference.json", pins["reference"])
    run = ref.load_run(path, directory, roots)
    bundle = run.manifest
    sidecar = load(compat.bound_file(bundle["provenance"]["eligibility"], roots))
    m = load(compat.bound_file(sidecar["run_manifest"], roots))
    job = directory.parent/"jobs"/run_id
    pre, returned = [load(checked(directory/f"{k}.json", pins[k])) for k in ("preflight", "native-return")]
    state, request = [load(checked(job/f"{k}.json", pins[k])) for k in ("state", "request")]
    check_durable(pre, returned, state, request, m, bundle)
    for name, digest in request["inputs"].items():
        p = Path(name)
        checked(p if p.is_absolute() else roots["checkout"]/p, digest)
    stage.check_build(m, roots)
    for name, digest in m["evidence"].items():
        checked(ref.payload_path(roots["data"], name), digest)
    baseline = stage.check_baseline(m["prefix_baseline"])
    image = compat.bound_file(bundle["provenance"]["native_image"], roots).read_bytes()
    events, counts = stream(ref.payload_path(directory, m["ordered_stream"]["path"]), m["ordered_stream"])
    by_seq = {e["seq"]: e for e in events if "seq" in e}
    require(all(e == by_seq.get(e["seq"]) for e in m["observations"]), "invented producer observation")
    d12.check_provenance(bundle, m, events, directory, roots, N)
    calls = short.check_sources(m, events, directory, image, short.original_roles(image))
    require(len(calls) == len(sidecar["calls"]) == 31, "shader ledger coverage")
    for actual, declared in zip(calls, sidecar["calls"]):
        require(all(declared[k] == v for k, v in actual.items()), "shader ledger binding")
    g = stage.group(events)
    require(all(e["forward_calls"] == 1 for e in g["shader_program"]), "shader forwarding count")
    short.check_frames(run.frames, events, bundle["video"], directory, inspect_pixels=False)
    short.check_pcm(bundle, events, directory, artifacts, m, roots)
    stage.check_clock(events, N, terminal_query=True)
    stage.check_state(events, N)
    d12.check_scenes(events, image, N)
    abi = d12.check_abi(events, counts, directory, N, terminal_query=True)
    d12.check_resolver(events)
    d12.check_exception(events, directory)
    d12.check_initial(events, directory, bundle, image)
    nodes = d12.check_nodes(events, directory, image)
    atlas = stage.check_atlas(events, directory)
    # Consumer readbacks are intentionally bounded to the same three D12 anchors;
    # all full-run scene passes are independently checked above.
    anchor_events = [e for e in events if e["event"] != "scene_pass" or 5760 <= e["n"] <= 5762]
    d12.check_consumers(anchor_events, directory)
    require({e["role"] for e in g["loaded_module_bytes"]} == {f"{n}-{r}" for n in ("opengl32", "winmm") for r in ("shim", "backend")}, "loaded module coverage")
    for e in g["loaded_module_bytes"]:
        name, role = e["role"].split("-")
        p = Path(m["build"]["build_directory"])/f"{name}.dll" if role == "shim" else Path(m["build"]["backends"][name]["path"])
        require(e["file_sha256"] == ref.hash_file(p) and e["file_bytes"] == p.stat().st_size, "loaded module identity")
    check_endpoint(events, directory, image)
    terminal = [line.strip() for line in (directory/"runner.log").open(errors="replace") if line.startswith(("WINE_EXIT=", "TIMEOUT"))]
    require(terminal == m["runner_terminal"] and len(terminal) == 1 and terminal[0].startswith("WINE_EXIT=0 "), "native runner terminal")
    retained = check_retention(bundle, run.frames, directory)
    with run.audio_path.open("rb") as pcm:
        pcm.seek(19845000*8); tail = pcm.read()
    require(len(tail) == 956352 and any(tail), "complete nonzero PCM tail")
    return run, {"run_id": run_id, "status": "CLOSED_RUN_VALID", "manifest_sha256": pins["reference"],
                 "frames": N, "raw_frames": len(retained), "scene_rows": len(bundle["scenes"]),
                 "pcm_bytes": 159716352, "tail_bytes": len(tail), "tail_sha256": d12.sha(tail),
                 "ordered_events": m["ordered_stream"]["events"], "decoded_bytes": m["ordered_stream"]["decoded_bytes"],
                 "native_queries": N+1, "abi_raw_pairs": len(g["abi_canary"]), "abi_returns": sum(abi),
                 "physical_resumes": 3, "node_activations": nodes["activations"], "baseline_entries": baseline,
                 "atlas": atlas, "runner_terminal": terminal, "durable_original_provenance": True}


def assess(roots):
    reviewed = [review_run(run_id, roots) for run_id in PINS]
    for other, _ in reviewed[1:]:
        require(not ref.compare_runs(reviewed[0][0], other), "closed runs differ exactly")
    # Pins currently contain only the reference. Future repeats require their own
    # independent closure/source review and corruption checks before final G6.
    return {"status": "PARTIAL", "reference_accepted": False, "g6": "open",
            "closed_runs_verified": len(reviewed), "required_runs": 3, "runs": [r[1] for r in reviewed],
            "pending": ["repeat2 closed independent review", "repeat3 acquisition and closed independent review", "three-run exact comparison"],
            "limitations": ["Pinned D9-restored-native candidate only; historical compiler/bank fidelity unestablished.",
                            "ABI raw snapshots cover first calls, three consumer anchors and terminal query; counters cover remaining returns.",
                            "Gamescope exited139 after native Wine exit0; original cleanup records confirm release."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    roots = {"checkout": args.capture_root.resolve(), "shared": Path(os.environ["EIDOLON_ROOT"]), "data": Path(os.environ["EIDOLON_DATA"])}
    try:
        result = assess(roots)
    except (OSError, ValueError, KeyError, TypeError, IndexError, zstandard.ZstdError) as error:
        print(json.dumps({"status": "FAIL", "reference_accepted": False, "reason": str(error)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
