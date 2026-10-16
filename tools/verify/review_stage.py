#!/usr/bin/env python3
"""Independent, file-only T13 review of the immutable D11 boundary pair.

Producer check/package programs are never imported or executed. This adapter
reuses Verification's byte/format/provenance primitives, not producer verdicts.
Pins identify these diagnostics; they are not criteria for future references.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

import numpy as np

if __package__:
    from . import compatibility as compat, reference as ref, review_short as short
else:
    import compatibility as compat
    import reference as ref
    import review_short as short


PINS = {
    "boundary3": (
        "9cfb4bf3d74d5518628ff73af91ea3190bf10cb4da53b9b450b99c84e224044f",
        "cc19efb1e95bab89ed4f627dc196676f5e54ae9974080b629c00945a859c6c21",
        "5e1f4da0f885474feabaf462bc44aab91a655c7d0856767a1f2419c81b074c37"),
    "boundary-repeat": (
        "6f4017f5ef72a4612c87bc383830731a31ea66227a6bae32b72fcbed174e831f",
        "9b08756dd958d8bd7f09d69faa026a855ecd08a8a22b38082a99b76787f87be1",
        "57248b327ed298f348e53acaa9a8abf119726b1450366280e0e08873f731c8a7"),
}
CONTROLS = "40b53d22e24b714b6f6d403680957657527823722fbe63b89fb8683c11525358"
N = 1443
RAW = sorted(set(range(0, N, 60)) | {0, 1, 2, 1438, 1439, 1440, 1441, 1442})
ARGBYTES = [0, 0, 4, 4, 12, 4, 24, 24, 12, 12, 8, 4, 12, 4, 16, 20, 40]
STATE = [0, 0, 0x405, 4] + [0]*8 + [8]*4 + [0, 0]
checked, load, one = short.checked, short.load, short.one
require = ref.require


def stream(path, retain_lookups=("glCreateShaderProgramv",)):
    """Check every line; retain only relevant lookups to bound memory."""
    events, counts, pids, sequence = [], Counter(), set(), 0
    with path.open() as source:
        for line in source:
            e = ref.load_json(line)
            pids.add(e["pid"])
            if "seq" in e:
                sequence += 1
                require(type(e["seq"]) is int and e["seq"] == sequence, "event sequence gap/order")
            else:
                require(e["event"] == "backend_probe", "unsequenced observation")
            counts[e["event"]] += 1
            if e["event"] == "lookup":
                counts[e["api"]] += 1
                require(e.get("resolved", True) is True, "unresolved lookup")
                if e.get("name") not in retain_lookups and e["api"] not in retain_lookups:
                    continue
            events.append(e)
    require(len(pids) == 1, "mixed run identity")
    return events, counts


def group(events):
    result = defaultdict(list)
    for e in events:
        result[e["event"]].append(e)
    return result


def check_build(m, roots):
    build = m["build"]
    directory = Path(build["build_directory"])
    for name, digest in build["outputs"].items():
        checked(directory / name, digest)
    for name, digest in dict(build["original_sources"], **build["sources"]).items():
        checked(directory / "source-snapshot" / name, digest)
    for backend in build["backends"].values():
        checked(Path(backend["path"]), backend["sha256"])
    checked(Path(m["host_runner"]["path"]), m["host_runner"]["sha256"])
    for name in ("opengl32.dll", "winmm.dll"):
        checked(Path(m["stage"]) / name, build["outputs"][name])
    checked(Path(m["input"]["executed_copy"]), compat.INPUT_HASHES["exe"])
    checked(roots["shared"] / m["input"]["archive"], compat.INPUT_HASHES["archive"])
    checked(roots["data"] / "reference/dependencies/gm.dls", compat.INPUT_HASHES["bank"])


def check_baseline(baseline):
    inventory = load(checked(Path(baseline["inventory"]), baseline["inventory_sha256"]))
    root = Path(baseline["directory"])
    actual = {}
    for p in root.rglob("*"):
        if p.is_symlink():
            actual[p.relative_to(root).as_posix()] = "link:" + os.readlink(p)
        elif p.is_file():
            actual[p.relative_to(root).as_posix()] = ref.hash_file(p)
    require(actual == inventory and baseline["fresh_tree_equal"] is True, "baseline inventory mismatch")
    return len(actual)


def check_clock(events, nframes=N):
    clocks = [e for e in events if e["event"] == "clock"]
    startup = [e for e in clocks if e.get("timeline") is False]
    require([e["value"] for e in startup] == list(range(1001)), "startup schedule")
    clocks = [e for e in clocks if e.get("timeline") is not False]
    require(len(clocks) == nframes*9, "clock route coverage")
    epoch = one(events, "epoch")
    require(epoch["E"] == 1001 and epoch["seq"] < clocks[0]["seq"], "clock epoch")
    expected_apis = ["waveOutGetPosition"] + ["GetTickCount", "timeGetTime",
                    "QueryPerformanceCounter", "QueryPerformanceFrequency"]*2
    g = group(events)
    require(len(g["clock_routes_checked"]) == nframes, "clock canary coverage")
    for n in range(nframes):
        chunk = clocks[n*9:(n+1)*9]
        require([e["api"] for e in chunk] == expected_apis, "clock route order")
        values = [735*n] + [1001+n*1000//60, 1001+n*1000//60,
                            60060000+n*1000000, 60000000]*2
        require([e["value"] for e in chunk] == values, "clock route value")
        require(all(e.get("n", n) == n for e in chunk), "clock route tick")
        canary = g["clock_routes_checked"][n]
        require((canary["n"], canary["epoch_ms"], canary["milliseconds"], canary["qpc"],
                 canary["qpf"], canary["repeats"], canary["sample_cursor"])
                == (n, 1001, values[1], values[3], 60000000, 2, 735*n), "clock canary mismatch")
        require(chunk[-1]["seq"] < canary["seq"] < g["pre_present"][n]["seq"], "clock/pre-present order")


def check_state(events, nframes=N):
    g = group(events)
    context = one(events, "compat_context")
    require(len(g["frame_state"]) == len(g["pre_present"]) == nframes, "frame state coverage")
    for n, (state, frame) in enumerate(zip(g["frame_state"], g["pre_present"])):
        require(state["n"] == n and state["seq"] < frame["seq"], "frame state order")
        require(state["before"] == state["after"] == STATE, "GL restoration/layout mismatch")
        require((state["hdc"], state["hglrc"], state["tid"])
                == (context["hdc"], context["hglrc"], context["tid"]), "frame owning context")
        digest = hashlib.sha256(struct.pack("<18i", *state["before"])).hexdigest()
        require(digest == frame["before_state_sha256"] == frame["after_state_sha256"], "GL state digest")
    for use in g["program_use"]:
        require(use["pre_error"] == use["post_error"] == 0 and use["after_program"] == use["program"],
                "program use/error")
        require((use["hdc"], use["hglrc"], use["tid"])
                == (context["hdc"], context["hglrc"], context["tid"]), "program owning context")
    require(not g["failure"] and not g["gl_error"], "runtime failure")


def check_canary(e, before_gpr, after_gpr, before_fx, after_fx):
    require(len(before_gpr) == len(after_gpr) == 36 and len(before_fx) == len(after_fx) == 512,
            "canary raw extent")
    a, b = struct.unpack("<9I", before_gpr), struct.unpack("<9I", after_gpr)
    require(all(a[i] == b[i] for i in (0, 1, 2, 4, 5, 6, 8)), "canary GPR/EFLAGS")
    require(e["argbytes"] == ARGBYTES[e["api"]] and e["return_esp"] == e["entry_esp"]+4+e["argbytes"]
            and a[3] == e["entry_esp"]-4 and b[3] == e["return_esp"]-8, "canary stack cleanup")
    require(b[7] == e["expected_eax"] == e["observed_eax"] and e["equal"] is True, "canary return value")
    require(before_fx == after_fx and hashlib.sha256(before_fx).hexdigest() == e["before_fx_sha256"]
            == e["after_fx_sha256"], "canary FP/SIMD")


def check_context(before, after, completion=False):
    require(len(before) == len(after) == 716, "CONTEXT extent")
    expected = bytearray(before)
    if completion:
        struct.pack_into("<I", expected, 184, 0x401765)
    require(expected == after, "CONTEXT change beyond authorized EIP")


def check_canaries(events, counts, directory):
    g = group(events)
    summaries = g["abi_summary"]
    require([e["api"] for e in summaries] == list(range(18)), "ABI summary coverage")
    totals = [e["returned_calls"] for e in summaries]
    active = [i for i, total in enumerate(totals) if total]
    require(active == [i for i in range(17) if i != 10], "ABI unobserved route changed")
    require(sorted(e["api"] for e in g["abi_canary"]) == active, "ABI first-snapshot coverage")
    for e in g["abi_canary"]:
        require(e["ordinal"] == 1, "unexpected failed/repeated canary snapshot")
        prefix = directory / f"abi-{e['api']:02d}-1"
        raw = [(prefix.with_name(prefix.name + f"-{side}-{kind}.bin")).read_bytes()
               for kind in ("gpr", "fx") for side in ("before", "after")]
        check_canary(e, *raw)
    expected = {0: 1001+2*N, 1: 2*N, 2: 2*N, 3: 2*N, 4: N, 6: 1, 7: 1, 8: 1, 9: 1,
                10: 0, 11: counts["wglGetProcAddress"], 12: counts["shader_program"],
                13: counts["program_use"], 15: 1, 16: 1, 17: 0}
    require(all(totals[k] == v for k, v in expected.items()) and sum(totals) == 626647,
            "ABI counters/observation reconciliation")
    for name in ("bootstrap", "completion"):
        before, after = [(directory / f"{name}-context-{side}.bin").read_bytes() for side in ("before", "after")]
        check_context(before, after, name == "completion")
        if name == "completion":
            e = one(events, "completion_canary")
            require(hashlib.sha256(before).hexdigest() == e["before_sha256"] and
                    hashlib.sha256(after).hexdigest() == e["after_sha256"], "CONTEXT hash")
    return totals


def check_atlas(events, directory):
    draw, atlas, volume = [one(events, name) for name in ("first_draw_state", "noise_atlas", "volume_upload")]
    require(draw["program"] == 2 and draw["fbo_status"] == 0x8cd5 and draw["viewport"] == [0, 0, 16384, 128]
            and draw["draw_buffers"] == [0x8ce0]+[0]*7 and draw["color_mask"] == [1]*4
            and draw["blend"] == draw["srgb"] == 0 and draw["clamp_fragment_color"] == 0x891d
            and draw["vertex_path"] == "glRecti", "atlas draw state")
    require((atlas["width"], atlas["height"], atlas["internal_format"], atlas["bytes"])
            == (16384, 128, 0x8814, 33554432) and atlas["pack"] == [4]+[0]*7, "atlas layout")
    path = checked(directory / "noise-atlas.rgba32f", atlas["sha256"])
    require(path.stat().st_size == 33554432, "atlas extent")
    pixels = np.fromfile(path, dtype="<f4").reshape(-1, 4)
    require(np.isfinite(pixels).all() and (pixels[:, 3] == 0).all(), "atlas finite/alpha diagnostic")
    require(volume["source_sha256"] == atlas["sha256"] and volume["source"] == int(atlas["pointer"], 16)
            and volume["dimensions"] == [128]*3 and volume["internal_format"] == 0x8814
            and volume["unpack"] == [4]+[0]*8 and volume["texture"] == 16
            and volume["caller"] == "0x00407a5a" and draw["seq"] < atlas["seq"] < volume["seq"],
            "volume source/layout/order")
    return {"unique_rgb": int(len(np.unique(pixels[:, :3], axis=0))), "alpha_zero": True,
            "rgb_range": [float(pixels[:, :3].min()), float(pixels[:, :3].max())]}


def review_run(mode, roots, image, roles):
    artifact_root = roots["checkout"] / "artifacts/reference"
    run = f"proxy-b-d11-{mode}-20261016"
    paths = [checked(artifact_root / f"{run}{suffix}.json", digest)
             for suffix, digest in zip(("", "-small-capture", "-eligibility"), PINS[mode])]
    m, bundle, sidecar = map(load, paths)
    directory = roots["data"] / "reference" / run
    require(m["run_id"] == bundle["run_id"] == run and m["status"] == bundle["status"] == "partial",
            "run/partial identity")
    require(m["reference_eligible"] is m["finalized"] is bundle["reference_eligible"]
            is bundle["finalized"] is bundle["completion"]["finalized"] is False, "diagnostic relabeled")
    require(bundle["schema"] == "eidolon-small-real-capture-diagnostic-2", "diagnostic version")
    check_build(m, roots)
    for name, digest in m["evidence"].items():
        checked(ref.payload_path(roots["data"], name), digest)
    for name in ("package_tool", "original_package_tool", "state_observations", "run_manifest"):
        compat.bound_file(bundle[name], roots)
    events, counts = stream(directory / "backend.jsonl")
    require(all(e in events for e in m["observations"]), "invented manifest observation")
    calls = short.check_sources(m, events, directory, image, roles)
    require(compat.assess(paths[2], roots)["status"] == "PROVENANCE_ONLY", "D9 provenance")
    for call, declared in zip(calls, sidecar["calls"]):
        require(all(declared[k] == v for k, v in call.items()), "sidecar call mismatch")
    require(all(e["forward_calls"] == 1 for e in events if e["event"] == "shader_program"), "forward count")
    video = bundle["video"]
    require((video["width"], video["height"], video["row_stride"], video["pixel_format"], video["row_order"],
             video["frame_count"]) == (1920, 1080, 7680, "rgba8", "bottom-up", N), "final layout/count")
    index = [ref.load_json(line) for line in checked(artifact_root / video["index"], video["index_sha256"]).read_text().splitlines()]
    require([r["n"] for r in index if "raw_zst" in r] == RAW, "sparse/boundary raw coverage")
    raw_stats = short.check_frames(index, events, video, directory)
    short.check_pcm(bundle, events, directory, artifact_root, m, roots)
    check_clock(events)
    check_state(events)
    totals = check_canaries(events, counts, directory)
    atlas = check_atlas(events, directory)
    for e in group(events)["loaded_module_bytes"]:
        name, role = e["role"].split("-")
        p = Path(m["build"]["build_directory"]) / f"{name}.dll" if role == "shim" else Path(m["build"]["backends"][name]["path"])
        require(e["file_bytes"] == p.stat().st_size and e["file_sha256"] == ref.hash_file(p), "loaded module identity")
    require({e["role"] for e in group(events)["loaded_module_bytes"]}
            == {f"{name}-{role}" for name in ("opengl32", "winmm") for role in ("shim", "backend")}, "loaded module coverage")
    stop = one(events, "planned_partial_stop")
    require(stop == bundle["actual_stop"] and stop["frames"] == N and stop["finalized"] is False
            and stop["exit_code"] == m["launcher_exit"] == 0 and m["supervisor_timeout"] is False
            and stop["seq"] > group(events)["post_present"][-1]["seq"], "partial exit evidence")
    require(bundle["completion"]["frames_observed"] == bundle["completion"]["frames_hashed"] == N
            and bundle["completion"]["audio_sample_frames"] == 19964544, "publication count")
    for e in (stop, bundle["completion"]):
        require(e["dropped_frames"] == e["dropped_audio_sample_frames"] == 0 and e["errors"] == [], "capture loss/error")
    require(bundle["publication"] == {"payloads_closed": True, "index_closed": True}, "publication incomplete")
    runner = (directory / "runner.log").read_text(errors="replace")
    require(len(m["runner_terminal"]) == 1 and m["runner_terminal"][0] in runner
            and m["runner_terminal"][0].startswith("WINE_EXIT=0 "), "native exit log")
    try:
        ref.load_run(paths[1], directory)
    except ref.InvalidCapture:
        pass
    else:
        raise ref.InvalidCapture("partial bundle accepted as full reference")
    scenes = group(events)["scene_state"]
    require([s["n"] for s in scenes] == list(range(N)), "scene observation coverage")
    passes = group(events)["scene_pass"]
    require(Counter(e["n"] for e in passes) == Counter({n: 19 for n in range(N)}), "scene pass coverage")
    result = {"run_id": run, "frames": N, "raw_frames": len(RAW), "pcm_bytes": short.PCM_BYTES,
              "atlas": atlas, "abi_return_totals": totals, "first_return_snapshots": 16,
              "active_cloud_draws": sum(e["cloud_location"] >= 0 for e in passes),
              "anchor_pixels": [r for r in raw_stats if r["n"] in (0, 1, 1439, 1440, 1442)],
              "stop": "planned_partial_stop", "full_reference_rejected": True}
    return result, m, index, events


def check_controls(roots):
    path = roots["checkout"] / "artifacts/reference/proxy-b-d11-negative-controls-20261016.json"
    controls = load(checked(path, CONTROLS))
    checked(Path(controls["host_tool"]["path"]), controls["host_tool"]["sha256"])
    require(len(controls["results"]) == 12 and len({r["fault"] for r in controls["results"]}) == 12,
            "control coverage")
    for row in controls["results"]:
        m = load(checked(roots["checkout"] / row["manifest"], row["sha256"])) if "manifest" in row else row
        for name, digest in m["evidence"].items():
            checked(ref.payload_path(roots["data"], name), digest)
        backend = next(name for name in m["evidence"] if name.endswith("/backend.jsonl"))
        events, counts = stream(roots["data"] / backend)
        require(m["launcher_exit"] == 125 and not counts["pre_present"], "negative control accepted frame/exit")
        runner = (roots["data"] / backend).with_name("runner.log").read_text(errors="replace")
        require("WINE_EXIT=125 " in runner, "control exit log")
        if "manifest" in row:
            failure = one(events, "failure")
            require(failure == m["first_failed_check"] and failure["reason"] == row["observed"], "control attribution")
            require(m["build"] == controls["build"] and m["status"] == "failed", "control build/status")
            if row["fault"] != "fingerprint":
                injection = one(events, "fault_injected")
                require(injection["name"] == row["fault"] and injection["seq"] < failure["seq"], "control injection order")
                if row["fault"] == "wrong-thread":
                    require(injection["tid"] != failure["tid"], "wrong thread not exercised")
        else:
            require(events == row["observations"], "backend control observations")
            first = events[0]
            expected = {"backend-missing": "backend_load_failed", "backend-wrong": "backend_symbol_missing_or_self",
                        "backend-self": "backend_is_proxy"}[row["fault"]]
            require(first["result"] == expected, "backend rejection reason")
    return [r["fault"] for r in controls["results"]]


def comparable(events, name):
    # Only execution identities are removed; no samples, state, clocks or pixels.
    return [{k: v for k, v in e.items() if k not in ("seq", "pid", "tid", "hdc", "hglrc")}
            for e in events if e["event"] == name]


def assess(roots):
    image = checked(roots["data"] / "reverse/confirmed-debug/postfix-00400000.bin", short.IMAGE_HASH).read_bytes()
    roles = short.original_roles(image)
    a, b = [review_run(mode, roots, image, roles) for mode in PINS]
    for key in ("build", "prefix_baseline", "host_runner", "transformation", "dependency"):
        require(a[1][key] == b[1][key], f"pair {key} mismatch")
    for key in ("os", "wine", "packages", "gpu", "display"):
        require(a[1]["environment"][key] == b[1]["environment"][key], f"pair environment {key}")
    path_keys = {"XDG_CACHE_HOME", "__GL_SHADER_DISK_CACHE_PATH", "EIDOLON_B_LOG", "EIDOLON_B_OUTPUT"}
    settings = [{k: v for k, v in m["environment"]["settings"].items() if k not in path_keys} for m in (a[1], b[1])]
    require(settings[0] == settings[1] and a[1]["run_id"] != b[1]["run_id"] and a[2] == b[2], "pair settings/index/identity")
    for name in ("scene_state", "scene_pass", "frame_state", "clock_routes_checked", "initial_resources", "abi_summary"):
        require(comparable(a[3], name) == comparable(b[3], name), f"pair {name} mismatch")
    dirs = [roots["data"] / "reference" / run[1]["run_id"] for run in (a, b)]
    files = ["pcm.f32le", "noise-atlas.rgba32f"] + [f"frame-{n:05d}.rgba" for n in RAW]
    for name in files:
        require(ref.first_byte_difference(dirs[0] / name, dirs[1] / name) is None, f"pair bytes differ: {name}")
    # Compare only defined x87 control/MXCSR fields across fresh bootstrap contexts,
    # not process-specific registers, pointers or undefined FXSAVE bytes.
    contexts = [(d / "bootstrap-context-before.bin").read_bytes() for d in dirs]
    require(contexts[0][28:32] == contexts[1][28:32] and contexts[0][228:232] == contexts[1][228:232], "initial FP control")
    baseline = check_baseline(a[1]["prefix_baseline"])
    controls = check_controls(roots)
    control, _, _ = short.review_run("control3", roots, image, roles)
    return {"status": "STAGED_G5_PARTIAL", "reference_accepted": False, "full_duration_ready": False,
            "g6": "open", "runs": [a[0], b[0]], "pair_files_byte_equal": len(files),
            "baseline_entries_verified": baseline, "live_rejection_controls": controls,
            "unchanged_source_control": control["negative_control"],
            "limitations": ["Canary raw snapshots cover 16 first returns; 626647 total returns are source-enforced counters.",
                            "Exception CONTEXT equality does not observe physical post-resume epilogue/return; lookup ID 10 uninvoked.",
                            "Runtime RNG/physics snapshots, interior synth FP and active cloud sampling remain absent; native interpretation is in T14's handoff.",
                            "D12's explicit restoration contract does not accept these incomplete runs; live G5/G6 and full endpoint/repeat await T15."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    roots = {"checkout": args.capture_root.resolve(), "shared": Path(os.environ["EIDOLON_ROOT"]),
             "data": Path(os.environ["EIDOLON_DATA"])}
    try:
        result = assess(roots)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        print(json.dumps({"status": "FAIL", "reference_accepted": False, "reason": str(error)}))
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
