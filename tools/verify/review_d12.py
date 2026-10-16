#!/usr/bin/env python3
"""Independent T15 saved-evidence G5 review. No producer imports or execution.

Pins select the immutable bounded pair, not the expected outputs of a future run.
G5_READY authorizes acquisition; partial inputs never become a full reference.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys

if __package__:
    from . import compatibility as compat, reference as ref, review_stage as stage
else:
    import compatibility as compat
    import reference as ref
    import review_stage as stage

short = stage.short
require, checked, load, one = ref.require, short.checked, short.load, short.one
N = 5763
PINS = {
    "proxy-b-d12-volume-20261016": "13a7058f6f3178e7dc2a1597ad597b82c9feb1abb602e452a86b2494f0cd8522",
    "proxy-b-d12-volume-repeat-20261016": "77b2f7c7af97d47217f1faff3654a8b1ce5a2079d3c342ce012f6685c9bb70a3",
}
CONTROL_PIN = "4f99b20f5d291f3c7ae2a0103eb37405d02af2291a186b1bdc950079162db146"
FX_DEFINED = list(range(5)) + list(range(6, 32)) + list(range(160, 288)) + [
    32 + 16*i + j for i in range(8) for j in range(10)]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def u32(raw, offset=0):
    return struct.unpack_from("<I", raw, offset)[0]


def fp_controls(raw):
    require(len(raw) == 512, "FXSAVE extent")
    return {"x87_cw": struct.unpack_from("<H", raw)[0], "mxcsr": u32(raw, 24)}


def check_resume(e, context, gpr, fx, mutation=None):
    require(len(context) == 716 and len(gpr) == 36 and len(fx) == 512, "resume extent")
    expected = [u32(context, i) for i in (156, 160, 180, 196, 164, 168, 172, 176, 192)]
    expected[3] -= 8  # PUSHAD ESP after the fake return and PUSHFD.
    expected[8] &= ~0x10000  # CPU clears RF upon executing the resumed instruction.
    actual = list(struct.unpack("<9I", gpr))
    gpr_diffs = [i for i in range(9) if actual[i] != expected[i]]
    fp_diffs = [i for i in FX_DEFINED if fx[i] != context[204+i]]
    if mutation == "exception-gpr":
        require(gpr_diffs == [7] and actual[7] == expected[7] ^ 1 and not fp_diffs, "live EAX mutation")
    elif mutation == "exception-fp":
        require(not gpr_diffs and fp_diffs == [25] and fx[25] == context[229] ^ 0x20, "live MXCSR mutation")
    else:
        require(not gpr_diffs and not fp_diffs, "physical resume GPR/EFLAGS/FP mismatch")
    require(e["equal"] is (mutation is None) and sha(fx) == e["fx_sha256"], "resume digest/verdict")
    require(e["expected_esp"] == e["observed_esp"] == actual[3]+8 == u32(context, 196), "physical ESP")
    require(fp_controls(fx) == {k: e[k] for k in ("x87_cw", "mxcsr")}
            and e["allowed_eflags_clear"] == 0x10000, "physical FP observation")


def check_exception(events, directory, mutation=None):
    g = stage.group(events)
    require([e["kind"] for e in g["native_resumed"]] == [0, 1, 2], "physical resume coverage")
    require([e["kind"] for e in g["native_resume_arm"]] == [0, 1], "resume arm coverage")
    for name in ("completion",):
        stage.check_context((directory/f"{name}-context-before.bin").read_bytes(),
                            (directory/f"{name}-context-after.bin").read_bytes(), name == "completion")
    for e in g["native_resumed"]:
        k = e["kind"]
        context, gpr, fx = [(directory/f"resume-{k}-{suffix}.bin").read_bytes()
                            for suffix in ("expected-context", "gpr", "fx")]
        check_resume(e, context, gpr, fx, mutation if k == 2 else None)
        if k < 2:
            arm = g["native_resume_arm"][k]
            require(arm["native_pc"] == e["target"] == (0x406379 if k == 0 else 0x40166a)
                    and arm["seq"] < e["seq"] and arm["tid"] == e["tid"], "physical resume attribution")
            before = (directory/f"{'bootstrap' if k == 0 else 'interior'}-context-before.bin").read_bytes()
            expected = bytearray(before)
            struct.pack_into("<I", expected, 184, e["target"])
            require(context == expected, "resume expected context origin")
            struct.pack_into("<I", expected, 184, arm["observer_pc"])
            require(expected == (directory/f"{'bootstrap' if k == 0 else 'interior'}-context-after.bin").read_bytes(), "resumption CONTEXT edit")
            if k == 1:
                require(fp_controls(fx) == {"x87_cw": 0x27f, "mxcsr": 0xffc0}, "native interior FP")
        else:
            arm = one(events, "native_epilogue_arm")
            before = bytearray((directory/"completion-context-after.bin").read_bytes())
            require(arm["native_pc"] == u32(before, 184) == 0x401765
                    and arm["return_slot"] == u32(before, 180)+4
                    and arm["expected_esp"] == u32(before, 180)+8, "native epilogue stack")
            for offset, key in ((156, "saved_edi"), (160, "saved_esi"), (180, "saved_ebp"), (196, "expected_esp")):
                struct.pack_into("<I", before, offset, arm[key])
            require(before == context and arm["original_return"] == e["target"]
                    and arm["seq"] < e["seq"], "native epilogue expected state")
    if mutation is None:
        end = one(events, "native_thread_exit")
        require(end["exit_code"] == end["expected_eax"] == u32(context, 176)
                and end["synth_tid"] == g["native_resumed"][1]["tid"] == g["native_resumed"][2]["tid"]
                and end["seq"] > e["seq"] and end["resumed_epilogue_observed"] is True, "native thread return")


def check_resolver(events):
    calls = [e for e in events if e["event"] == "lookup" and e["api"] == "GetProcAddress"]
    require([(e["ordinal"], e["name"], e["routed"]) for e in calls] == [
        (False, "GetCurrentThreadId", False), (True, "", False), (False, "GetTickCount", True),
        (False, "EidolonDeliberatelyMissingExport", False), (True, "", False)], "resolver route coverage")
    e = one(events, "resolver_control")
    require(e["calls"] == 5 and 0 < e["ordinal"] < 65535 and e["expected"] == e["by_name"] == e["by_ordinal"] != 0
            and e["routed"] == e["expected_routed"] != 0 and e["missing_name"] == e["missing_ordinal"] == 0
            and calls[-1]["seq"] < e["seq"], "resolver return controls")


def check_initial(events, directory, manifest, image):
    g = stage.group(events)
    expected = {("entry", "rng"): (0xb16b800, 0x520), ("prethread", "rng"): (0xb16b800, 0x520),
                ("entry", "tick"): (0xb16bd20, 4), ("prethread", "tick"): (0xb16bd20, 4),
                ("entry", "physics"): (0xb17bdf0, 256), ("first-query", "physics"): (0xb17bdf0, 256),
                ("first-query", "previous-seconds"): (None, 4)}
    require(Counter((e["phase"], e["role"]) for e in g["native_state"]) == Counter({k: 1 for k in expected}),
            "initial observation coverage")
    initial = manifest["conditions"]["settings"]["initial_observations"]
    for e in g["native_state"]:
        key = (e["phase"], e["role"])
        base, size = expected[key]
        raw = checked(directory/e["file"], e["sha256"]).read_bytes()
        require(len(raw) == e["bytes"] == size and (base is None or e["base"] == base), "initial owner/extent")
        require(e["tid"] == one(events, "synth_launch")["tid"], "initial state thread")
        require(initial["-".join(key)] == e["sha256"], "initial metadata binding")
        boundary = one(events, "synth_launch") if key[0] != "first-query" else one(events, "epoch")
        require(e["seq"] < boundary["seq"], "initial observation phase")
    rng = (directory/"native-prethread-rng.bin").read_bytes()
    require(rng[16:32] == image[0x37000:0x37010] == struct.pack("<4I", 1, 0, 31337, 0), "native seed")
    require(struct.unpack_from("<4I", rng, 48) == (16007, 0, 16007, 0)
            and struct.unpack_from("<2d", rng, 64) == (2**-31,)*2, "native RNG multiplier/scale")
    require((directory/"native-entry-tick.bin").read_bytes() == bytes(4)
            and (directory/"native-prethread-tick.bin").read_bytes() == struct.pack("<I", 1)
            and (directory/"native-first-query-previous-seconds.bin").read_bytes() == bytes(4), "initial tick/previous time")
    require(manifest["conditions"]["rng"]["initial_state_sha256"] == sha(rng), "RNG manifest digest")
    for phase in ("entry-main", "prethread-main", "first-query-main"):
        fp = fp_controls((directory/f"native-{phase}-fx.bin").read_bytes())
        require(fp == initial["fp_controls"][phase] and fp["x87_cw"] == 0x27f
                and fp["mxcsr"] & ~0x3f == 0x1f80, "main native FP controls")
    for k in range(3):
        require(initial["fp_controls"][f"physical-resume-{k}"] == fp_controls((directory/f"resume-{k}-fx.bin").read_bytes()),
                "physical FP metadata")
    resources = one(events, "initial_resources")
    require(resources["sha256"] == initial["native_resources"] == sha(image[0x9100:0x3edc0]), "native resources")
    settings = manifest["conditions"]["settings"]
    require(settings["native_state_reset"] is False and initial["prefix_baseline"] == settings["prefix_inventory_sha256"],
            "fresh state settings")
    require(manifest["conditions"]["initial_state_sha256"] == sha((json.dumps(initial, sort_keys=True, indent=2)+"\n").encode()),
            "initial specification digest")


def check_nodes(events, directory, image):
    g = stage.group(events)
    summary = one(events, "node_summary")
    records, restoration, coverage = (g[k] for k in ("node_rng", "node_probe_restoration", "node_coverage"))
    require(summary["nodes"] == 10 and summary["activations"] == 22 and summary["pending"] == 0
            and summary["visits"] == [22, 104, 264448] and summary["retained"] == [22, 1, 1], "node coverage summary")
    require(len(records) == len(restoration) == 24 and sorted(e["activation"] for e in coverage) == list(range(1, 23)),
            "node activation coverage")
    payload, canaries = [(directory/name).read_bytes() for name in ("node-state.bin", "node-canaries.bin")]
    require(len(payload) == 24*48 and len(canaries) == 24*1096, "node payload extent")
    phases, owners = {}, {}
    for i, (e, c) in enumerate(zip(records, restoration)):
        require((e["kind"], e["activation"]) == (c["kind"], c["activation"])
                and e["offset"] == i*48 and c["offset"] == i*1096
                and e["seq"] < c["seq"] and e["tid"] == c["tid"] == one(events, "synth_thread")["synth_tid"], "node probe attribution")
        raw, canary = payload[i*48:(i+1)*48], canaries[i*1096:(i+1)*1096]
        require(sha(raw) == e["sha256"] and sha(canary) == c["sha256"], "node raw digest")
        require(canary[:36] == canary[36:72] and canary[72:584] == canary[584:] and c["equal"] is True, "node probe restoration")
        require(e["native_pc"] == (0x40543e, 0x40563e, 0x40573e)[e["kind"]], "node probe PC")
        key = e["activation"]
        require(e["kind"] not in phases.setdefault(key, {}), "duplicate activation phase")
        phases[key][e["kind"]] = raw
        owner = (e["node_order"], e["esi"], e["input_pointer"])
        require(owners.setdefault(key, owner) == owner, "activation owner changed")
    rng = (directory/"native-prethread-rng.bin").read_bytes()
    for e in coverage:
        p = phases[e["activation"]]
        require(0 in p and (e["node_order"], e["esi"]) == owners[e["activation"]][:2], "node coverage owner")
        raw = p[0]
        if raw[8:16] == bytes(8):
            seed = raw[16:32]
        else:
            value = struct.unpack_from("<d", raw, 8)[0]*32768
            require(math.isfinite(value) and -(2**31) <= math.trunc(value) < 2**31, "node input conversion")
            integer = math.trunc(value)
            seed = struct.pack("<4I", *[(v+b) & 0xffffffff for v, b in zip((integer, 0, integer, 0), struct.unpack_from("<4I", rng))])
        require(raw[32:] == seed, "node native seed derivation")
        swapped = set(p) == {0, 1, 2}
        require(set(p) in ({0}, {0, 1, 2}) and e["first_swap_before"] == e["first_swap_after"] == int(swapped), "node first-swap coverage")
        if swapped:
            require(p[1][16:32] == p[2][16:32], "outer RNG restoration")
            state = p[1][32:]
            for _ in range(2):
                words = struct.unpack("<4i", state)
                state = struct.pack("<2q", words[0]*16007, words[2]*16007)
            require(p[2][32:] == state, "node native PMULDQ advances")
    require(len(g["node_hook"]) == 3, "node hook coverage")
    for e in g["node_hook"]:
        pc, size = e["native_pc"], e["displaced_bytes"]
        original = (directory/f"native-hook-{pc:08x}-original.bin").read_bytes()
        effective = (directory/f"native-hook-{pc:08x}-effective.bin").read_bytes()
        require(original == image[pc-0x400000:pc-0x400000+size] and len(effective) == size
                and effective[0] == 0xe9 and (pc+5+u32(effective, 1)) & 0xffffffff == e["observer_pc"]
                and effective[5:] == b"\x90"*(size-5) and e["continuation_pc"] == pc+size, "node trampoline identity")
    return summary


def check_abi(events, counts, directory, nframes=N, terminal_query=False):
    g = stage.group(events)
    require([e["api"] for e in g["abi_summary"]] == list(range(18)), "ABI summary coverage")
    totals = [e["returned_calls"] for e in g["abi_summary"]]
    require(all(totals[i] > 0 for i in range(17)) and totals[17] == 0, "ABI active routes")
    require(Counter((e["api"], e["ordinal"]) for e in g["abi_canary"] if e["ordinal"] == 1)
            == Counter({(i, 1): 1 for i in range(17)}) and len(g["abi_canary"]) == 74+int(terminal_query), "ABI raw coverage")
    for e in g["abi_canary"]:
        raw = [(directory/f"abi-{e['api']:02d}-{e['ordinal']}-{side}-{kind}.bin").read_bytes()
               for kind in ("gpr", "fx") for side in ("before", "after")]
        stage.check_canary(e, *raw)
        require(e["ordinal"] <= totals[e["api"]], "ABI ordinal")
    queries = nframes+int(terminal_query)
    expected = {0: 1001+2*queries, 1: 2*queries, 2: 2*queries, 3: 2*queries, 4: queries, 6: 1, 7: 1, 8: 1, 9: 1,
                10: 5, 11: counts["wglGetProcAddress"], 12: 31, 13: counts["program_use"], 15: 1, 16: 1, 17: 0}
    require(all(totals[i] == v for i, v in expected.items()), "ABI counters")
    return totals


def f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def bits(value):
    return u32(struct.pack("<f", value))


def check_scenes(events, image, nframes=N):
    g = stage.group(events)
    require([e["n"] for e in g["scene_state"]] == list(range(nframes)), "native scene coverage")
    rows = [struct.unpack_from("<ff", image, 0x2fc50+8*i) for i in range(50)]
    tokens = struct.unpack_from("<50I", image, 0x2fde0)
    for e in g["scene_state"]:
        seconds = f32(f32(e["n"]*735)/44100)
        beat = f32(seconds*f32(80/60))
        row = next(i for i, (_, end) in enumerate(rows) if beat < end)
        require((e["seconds_f32_bits"], e["scene_local_beat_f32_bits"], e["scene_token"])
                == (bits(seconds), bits(f32(beat-rows[row][0])), tokens[row]), "native scene/time interpretation")
    require(Counter(e["n"] for e in g["scene_pass"]) == Counter({n: 19 for n in range(nframes)}), "scene pass coverage")


def check_consumers(events, directory):
    g = stage.group(events)
    volumes, attachments, done, restores = [g[k] for k in ("consumer_volume", "consumer_attachment", "consumer_draw_complete", "consumer_restoration")]
    active = [e for e in g["scene_pass"] if e["cloud_location"] >= 0]
    require([e["n"] for e in active] == [5760, 5761, 5762] == [e["n"] for e in volumes]
            == [e["n"] for e in done] and len(attachments) == 9 and len(restores) == 6, "active cloud coverage")
    files = []
    for e, draw, end in zip(volumes, active, done):
        n = e["n"]
        require((e["caller"], e["program"], e["program_index"], e["source_creation"], e["unit"], e["texture"], e["sampler"], e["draw_fbo"])
                == (0x4085d7, 22, 20, 22, 0, 16, 0, 10) and e["cloud_location"] >= 0 and e["time_location"] >= 0,
                "active cloud route/sampler")
        require(e["dimensions"] == [128]*3 and e["internal_format"] == 0x8814
                and e["filter_wrap"] == [0x2601]*2+[0x2901]*3 and e["bytes"] == 33554432, "cloud texture layout/filter")
        require(e["time_resolution_bits"] == [bits(f32(f32(n*735)/44100)), bits(1920), bits(1080)]
                == draw["time_resolution_bits"] and draw["program"] == 22 and draw["draw_fbo"] == 10
                and draw["cloud_unit"] == 0 and draw["cloud_texture"] == 16 and draw["viewport"] == [0, 0, 1920, 1080], "active draw uniform/routing")
        require(draw["seq"] < e["seq"] < end["seq"] < g["pre_present"][n]["seq"]
                and e["tid"] == draw["tid"] == end["tid"] == g["pre_present"][n]["tid"], "consumer draw order/thread")
        path = checked(directory/e["file"], e["sha256"])
        require(path.stat().st_size == 33554432 and e["sha256"] == e["upload_sha256"] == one(events, "volume_upload")["source_sha256"]
                and ref.first_byte_difference(path, directory/"noise-atlas.rgba32f") is None, "GPU volume differs from atlas")
        files.append(e["file"])
        selected = [a for a in attachments if a["n"] == n]
        require([a["draw_buffer_index"] for a in selected] == [0, 1, 2] and end["attachments"] == 3
                and end["ordinal"] == n-5759, "consumer attachment coverage")
        for i, a in enumerate(selected):
            require((a["program"], a["draw_fbo"], a["texture"], a["attachment"], a["level"], a["component"], a["encoding"], a["read_format"], a["read_type"])
                    == (22, 10, 10+i, 0x8ce0+i, 0, 0x1406, 0x2601, 0x1908, 0x1406)
                    and a["dimensions"] == [1920, 1080] and a["internal_format"] == 0x8814
                    and a["row_order"] == "bottom-up" and a["bytes"] == 33177600
                    and e["seq"] < a["seq"] < end["seq"], "consumer attachment layout/order")
            require(checked(directory/a["file"], a["sha256"]).stat().st_size == a["bytes"], "consumer attachment extent")
            files.append(a["file"])
        phases = [r for r in restores if r["n"] == n]
        require([r["phase"] for r in phases] == ["volume", "attachments"], "consumer restoration coverage")
        for r in phases:
            before, after = [(directory/f"consumer-{n:05d}-{r['phase']}-{side}-state.bin").read_bytes() for side in ("before", "after")]
            require(len(before) == 116 and before == after and r["equal"] is True
                    and sha(before) == r["before_sha256"] == r["after_sha256"], "consumer GL restoration")
            state = struct.unpack("<29i", before)
            require(state[1:5] == (22, 10, 10, 0x8ce0) and state[5:14] == (4, 0, 0, 0, 0, 0, 0, 0, 0)
                    and state[17:25] == (0x8ce0, 0x8ce1, 0x8ce2, 0, 0, 0, 0, 0)
                    and state[25:] == (0, 0, 1920, 1080), "consumer raw GL state")
        require(draw["seq"] < phases[0]["seq"] < e["seq"] and selected[-1]["seq"] < phases[1]["seq"] < end["seq"], "consumer restoration ordering")
        # The 19 actual native draws continue from the consumer through the final default FBO.
        passes = [p for p in g["scene_pass"] if p["n"] == n]
        require([p["program"] for p in passes[9:]] == [22]+list(range(12, 21))
                and [p["draw_fbo"] for p in passes[9:]] == [10, 11, 12, 11, 12, 13, 11, 13, 11, 0], "downstream pass routing")
        witness = [a for a in g["abi_canary"] if a["api"] == 14 and a["n"] == n and end["seq"] < a["seq"] < passes[10]["seq"]]
        require(len(witness) == 1 and witness[0]["return_pc"] == 0x4085d7, "consumer physical return witness")
    return files


def check_provenance(bundle, producer, events, directory, roots, nframes=N):
    acquisition = load(compat.bound_file(producer["acquisition"], roots))
    require(all(producer[k] == v for k, v in acquisition.items()), "producer changed acquisition")
    package = compat.bound_file(producer["package_tool"], roots)
    inputs, build = bundle["source"]["inputs"], producer["build"]
    expected_inputs = dict(build["original_sources"], **build["sources"],
                           archive=compat.INPUT_HASHES["archive"], bank=compat.INPUT_HASHES["bank"],
                           launcher=ref.hash_file(roots["checkout"]/"tools/wine-headless"),
                           host_runner=producer["host_runner"]["sha256"], package=ref.hash_file(package))
    require(inputs == expected_inputs, "source inventory mismatch")
    inventory = load(checked(directory/"capture-tool-inventory.json", bundle["capture"]["tool_sha256"]))
    require(all(inventory[k] == v for k, v in {
        "build_id": build["build_id"], "build_sources": build["sources"], "original_sources": build["original_sources"],
        "outputs": build["outputs"], "host_runner_sha256": inputs["host_runner"], "launcher_sha256": inputs["launcher"],
        "package_sha256": inputs["package"]}.items()), "capture tool inventory mismatch")
    identity = producer["executed_file_observation"]
    require(identity["before_sha256"] == identity["after_sha256"] == ref.ORIGINAL_SHA256
            and identity["path"] == producer["input"]["executed_copy"], "executed-file identity observations")
    anchors = stage.group(events)["scene_anchor_locals"]
    require(anchors and anchors[-1]["n"] == nframes-1 and all(e["original_source_sha256"] == compat.SOURCE_HASH for e in anchors),
            "original shader memory after forwarding")
    context = one(events, "compat_context")
    require(context["profile_mask"] == 2 and context["flags"] == 0 and context["driver_debug"] is False,
            "compatibility context identity")
    environment = bundle["conditions"]["environment"]
    require(environment["graphics_api"] == context["version"]+"; GLSL "+context["glsl"]
            and environment["os"] == producer["environment"]["os"] and environment["wine"] == producer["environment"]["wine"],
            "observed environment mismatch")


def review_run(run_id, roots, image):
    artifacts = roots["checkout"]/"artifacts/reference"
    path = checked(artifacts/f"{run_id}-partial-reference.json", PINS[run_id])
    directory = roots["data"]/"reference"/run_id
    run = ref.load_partial(path, directory, roots)
    bundle = run.manifest
    sidecar = load(compat.bound_file(bundle["provenance"]["eligibility"], roots))
    m = load(compat.bound_file(sidecar["run_manifest"], roots))
    require(m["status"] == "partial" and m["run_id"] == run_id and not m["supervisor_timeout"]
            and m["launcher_exit"] == 0 and m["finalized"] is m["reference_eligible"] is False, "bounded run status")
    stage.check_build(m, roots)
    for name, digest in m["evidence"].items():
        checked(ref.payload_path(roots["data"], name), digest)
    events, counts = stage.stream(directory/"backend.jsonl", ("glCreateShaderProgramv", "GetProcAddress"))
    g = stage.group(events)
    require(all(e in events for e in m["observations"]), "invented producer observation")
    check_provenance(bundle, m, events, directory, roots)
    calls = short.check_sources(m, events, directory, image, short.original_roles(image))
    require(len(calls) == len(sidecar["calls"]) == 31, "shader ledger coverage")
    for call, declared in zip(calls, sidecar["calls"]):
        require(all(declared[k] == v for k, v in call.items()), "observed shader ledger mismatch")
    require(all(e["forward_calls"] == 1 for e in g["shader_program"]), "shader forwarding count")
    require(len(run.frames) == N and len([r for r in run.frames if "raw_zst" in r]) == 111
            and all("raw_zst" in run.frames[n] for n in range(5758, 5763)), "bounded frame/raw coverage")
    short.check_frames(run.frames, events, bundle["video"], directory)
    short.check_pcm(bundle, events, directory, artifacts, m, roots)
    stage.check_clock(events, N)
    stage.check_state(events, N)
    check_scenes(events, image)
    abi = check_abi(events, counts, directory)
    check_resolver(events)
    check_exception(events, directory)
    check_initial(events, directory, bundle, image)
    nodes = check_nodes(events, directory, image)
    atlas = stage.check_atlas(events, directory)
    files = check_consumers(events, directory)
    require({e["role"] for e in g["loaded_module_bytes"]} == {f"{name}-{role}" for name in ("opengl32", "winmm") for role in ("shim", "backend")}, "loaded module coverage")
    for e in g["loaded_module_bytes"]:
        name, role = e["role"].split("-")
        p = Path(m["build"]["build_directory"])/f"{name}.dll" if role == "shim" else Path(m["build"]["backends"][name]["path"])
        require(e["file_sha256"] == ref.hash_file(p) and e["file_bytes"] == p.stat().st_size, "loaded module bytes")
    stop = one(events, "planned_partial_stop")
    require(stop["frames"] == N and stop["exit_code"] == 0 and stop["finalized"] is False
            and stop["dropped_frames"] == stop["dropped_audio_sample_frames"] == 0 and stop["errors"] == []
            and stop["seq"] > g["post_present"][-1]["seq"], "actual partial stop")
    runner = (directory/"runner.log").read_text(errors="replace")
    require(len(m["runner_terminal"]) == 1 and m["runner_terminal"][0] in runner
            and m["runner_terminal"][0].startswith("WINE_EXIT=0 "), "actual native exit")
    require(m["resources"] == {"errors": [], "prefix_processes_released": True, "private_sink_unloaded": True}, "resource release")
    files += [f"frame-{r['n']:05d}.rgba" for r in run.frames if "raw_zst" in r]
    files += ["pcm.f32le", "noise-atlas.rgba32f", "node-state.bin"] + [e["file"] for e in g["native_state"]]
    return run, m, events, files, {"run_id": run_id, "frames": N, "raw_frames": 111, "abi_raw_pairs": 74,
           "abi_return_total": sum(abi), "node_activations": nodes["activations"], "first_swaps": nodes["retained"][1],
           "atlas": atlas, "pcm_bytes": 159716352, "consumer_volumes": 3, "consumer_attachments": 9}


def check_live_faults(roots, build):
    path = roots["checkout"]/"artifacts/reference/proxy-b-d12-exception-controls-20261016.json"
    controls = load(checked(path, CONTROL_PIN))
    checked(Path(controls["host_tool"]["path"]), controls["host_tool"]["sha256"])
    require([e["fault"] for e in controls["results"]] == ["exception-gpr", "exception-fp"], "exception control coverage")
    for row in controls["results"]:
        m = load(checked(roots["checkout"]/row["manifest"], row["sha256"]))
        require(m["build"] == build and m["status"] == "failed" and m["launcher_exit"] == 125, "control build/status")
        directory = roots["data"]/"reference"/m["run_id"]
        for name, digest in m["evidence"].items():
            checked(ref.payload_path(roots["data"], name), digest)
        events, counts = stage.stream(directory/"backend.jsonl", ("GetProcAddress",))
        check_exception(events, directory, row["fault"])
        injected, failed = one(events, "fault_injected"), one(events, "failure")
        resumed = stage.group(events)["native_resumed"][-1]
        require(injected["name"] == row["fault"] and injected["seq"] < resumed["seq"] < failed["seq"]
                and failed["reason"] == "physical_exception_resume_canary" and failed == m["first_failed_check"]
                and not counts["pre_present"] and "WINE_EXIT=125 " in (directory/"runner.log").read_text(), "live rejection evidence")
    return [r["fault"] for r in controls["results"]]


def assess(roots):
    image = checked(roots["data"]/"reverse/confirmed-debug/postfix-00400000.bin", short.IMAGE_HASH).read_bytes()
    a, b = [review_run(run_id, roots, image) for run_id in PINS]
    require(ref.compare_runs(a[0], b[0]) == ["partial diagnostics cannot pass full comparison"], "bounded pair exact comparison")
    for key in ("build", "prefix_baseline", "host_runner", "dependency", "transformation"):
        require(a[1][key] == b[1][key], f"pair {key}")
    require(a[1]["finished_utc"] < b[1]["started_utc"], "independent sequential invocations")
    for event in ("scene_state", "scene_pass", "frame_state", "clock_routes_checked", "abi_summary", "consumer_volume", "consumer_attachment", "node_summary"):
        require(stage.comparable(a[2], event) == stage.comparable(b[2], event), f"pair {event}")
    fields = ("kind", "node_order", "activation", "tick", "sha256")
    nodes = [[tuple(e[k] for k in fields) for e in r[2] if e["event"] == "node_rng"] for r in (a, b)]
    require(nodes[0] == nodes[1], "pair node streams")
    require(a[3] == b[3], "pair file coverage")
    for name in a[3]:
        require(ref.first_byte_difference(a[0].audio_path.parent/name, b[0].audio_path.parent/name) is None, f"pair bytes differ: {name}")
    baseline = stage.check_baseline(a[1]["prefix_baseline"])
    controls = check_live_faults(roots, a[1]["build"])
    legacy_controls = stage.check_controls(roots)
    control, _, _ = short.review_run("control3", roots, image, short.original_roles(image))
    return {"status": "G5_READY", "g5": "accepted-bounded-acquisition", "full_duration_ready": True,
            "reference_accepted": False, "g6": "open", "evidence_blockers": [],
            "runs": [a[4], b[4]], "pair_files_byte_equal": len(a[3]), "baseline_entries_verified": baseline,
            "live_exception_faults": controls, "prior_live_controls": legacy_controls,
            "unchanged_source_control": control["negative_control"],
            "full_run_obligations": ["Implement native endpoint query27000/exit0 with no wrapper stop and retain all27000 hashes.",
                                     "One510-raw reference plus a fresh hash-only/full-PCM repeat; identical source/build/settings.",
                                     "Per-run final-data/restoration provenance, <=30GB and lossless bounded logging; T17 full G6 review."],
            "limitations": ["Physical/ABI witnesses cover instrumented routes; counters are not raw snapshots for every return.",
                            "Only one of22 activations executes a retained first swap;21 have explicit zero-hit coverage.",
                            "Active cloud evidence covers program20 at5760..5762, not all later scenes or historical compiler/bank fidelity."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    roots = {"checkout": args.capture_root.resolve(), "shared": Path(os.environ["EIDOLON_ROOT"]), "data": Path(os.environ["EIDOLON_DATA"])}
    try:
        result = assess(roots)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        print(json.dumps({"status": "FAIL", "reference_accepted": False, "reason": str(error)}))
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
