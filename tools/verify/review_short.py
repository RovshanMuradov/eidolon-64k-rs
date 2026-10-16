#!/usr/bin/env python3
"""File-only recheck of T11's pinned diagnostics; never full-reference acceptance."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

import numpy as np

if __package__:
    from . import compatibility as compat, reference as ref
    from .diagnostic_pcm import one, content_summary
else:
    import compatibility as compat
    import reference as ref
    from diagnostic_pcm import one, content_summary


# Immutable review inputs, not hashes/criteria for any future reference.
PINS = {
    "control3": {"": "d7036a6494f1dad72907799f794f0ea9f96aba42510cf3f8e23f6fd09054d627"},
    "primary": {
        "": "bb467b21f1fc6e3af9b88a95bc79dd85e2314c6cd8b6f0e2558dbe876c419c23",
        "-small-capture": "4b39040936cd95143fdcda791f759b084f55a31d5e03cd91c90688fb693ddbb5",
        "-eligibility": "d4846f3fb8a652fe35c688c919015b7ab320982c0f30fb5335110247f87e8bf0",
    },
    "repeat": {
        "": "2b773c817d5895a4f85f32b60f349114b843ebafee93a1e1656f0b35f3396760",
        "-small-capture": "818e05f28f60d97a2e65491ed82cb32ba11e953dc6a51f8c9a2adb0de3d05496",
        "-eligibility": "6f07cd4a41ecd4553773fdfaf87c7c0829e74eacea1fb7a8d8b1c4cfb41be7ac",
    },
    "boundary": {
        "": "7ece95df55b281eb9e2ba211e71a96008f9cb406297e7aeb2bfeca8c012951b9",
        "-small-capture": "aa5f81ace7bea25f1dee64108c86f750719e2f646604a531c7445500d8a36940",
    },
}
IMAGE_HASH = "da9cc65b64aa7d322807d93cb4361bc864a10f00ed47246f5df96fb5b9ecf504"
PCM_BYTES = ref.ORIGINAL_AUDIO_FRAMES * 8


def checked(path, digest):
    ref.require(ref.hash_file(path) == digest, f"review input hash mismatch: {path}")
    return path


def load(path):
    return ref.load_json(path.read_text())


def original_roles(image):
    """Decode ONLY the pinned straight-line MOV initializer; no target execution.

    Original 0x406dad indexes EBP-0x408 by [ESI+4], pushes [ESI] and
    GL_FRAGMENT_SHADER, calls at 0x406dcc, then advances ESI by 8 until EDI.
    This reconstructs ordered arrays independently of the runtime ledger.
    """
    ref.require(hashlib.sha256(image).hexdigest() == IMAGE_HASH, "original image changed")
    registers, locals_ = {}, {}
    pc = 0x64e7
    while pc < 0x6da6:
        op = image[pc]
        if op == 0xa1:  # MOV EAX,[absolute]
            address, = struct.unpack_from("<I", image, pc + 1)
            registers[0], = struct.unpack_from("<I", image, address - 0x400000)
            pc += 5
        elif op == 0x8b and image[pc + 1] & 0xc7 == 5:  # MOV reg,[absolute]
            address, = struct.unpack_from("<I", image, pc + 2)
            registers[(image[pc + 1] >> 3) & 7], = struct.unpack_from("<I", image, address - 0x400000)
            pc += 6
        elif op == 0x89 and image[pc + 1] & 0xc7 in (0x45, 0x85):
            modrm = image[pc + 1]
            size = 1 if modrm & 0xc0 == 0x40 else 4
            displacement, = struct.unpack_from("<b" if size == 1 else "<i", image, pc + 2)
            locals_[displacement] = registers[(modrm >> 3) & 7]
            pc += 2 + size
        elif 0xb8 <= op <= 0xbf:  # MOV reg,immediate
            registers[op - 0xb8], = struct.unpack_from("<I", image, pc + 1)
            pc += 5
        else:
            raise ref.InvalidCapture(f"unreviewed source initializer instruction at {pc:#x}")
    ref.require(pc == 0x6da6 and registers[6] == 0x4357e0 and registers[7] == 0x4358d0,
                "original creation loop bounds changed")
    ref.require(image[0x6dad:0x6dce].hex() ==
                "8b46048d8df8fbffff8d048150ff3668308b000068a4f84100ff1550904000ffd0",
                "original creation call changed")
    ref.require(image[0x6dfc:0x6e03].hex() == "83c6083bf77caa", "original loop branch changed")
    roles = [(0x406442, [0x426c58])]
    for address in range(registers[6], registers[7], 8):
        count, offset = struct.unpack_from("<II", image, address - 0x400000)
        roles.append((0x406dce, [locals_[-0x408 + 4 * (offset + i)] for i in range(count)]))
    ref.require(len(roles) == 31 and sum(len(a) for _, a in roles) == 235, "source role extent changed")
    return roles


def check_sources(manifest, events, directory, image, roles):
    sources = [e for e in events if e["event"] == "shader_source"]
    programs = [e for e in events if e["event"] == "shader_program"]
    ref.require(sources == manifest["source_provenance"], "manifest ledger differs from stream")
    ref.require([p["creation"] for p in programs] == list(range(1, 32)), "creation coverage changed")
    lookups = [e for e in events if e["event"] == "lookup" and e.get("name") == "glCreateShaderProgramv"]
    ref.require(len(lookups) == 31, "creation lookup coverage changed")
    modified = manifest["transformation"] == "450-compatibility"
    edits = 0
    calls = []
    for creation, ((ret, addresses), program) in enumerate(zip(roles, programs), 1):
        array = [e for e in sources if e["creation"] == creation]
        ref.require([e["index"] for e in array] == list(range(len(addresses))), "source array order changed")
        ref.require(image[ret - 0x400002:ret - 0x400000] == b"\xff\xd0", "original call opcode changed")
        call = dict(sequence=creation, stage=0x8b30, count=len(array), caller=f"0x{ret-2:08x}",
                    source_addresses=[f"0x{a:08x}" for a in addresses], program=program["program"],
                    **{"return": f"0x{ret:08x}"})
        for e, address in zip(array, addresses):
            ref.require(e["stage"] == 0x8b30 and e["count"] == len(array)
                        and int(e["caller"], 16) == ret and int(e["pointer"], 16) == address,
                        "observed call differs from original role")
            prefix = directory / f"shader-{creation:03d}-{e['index']:03d}"
            raw = checked(prefix.with_name(prefix.name + "-raw.glsl"), e["raw_sha256"]).read_bytes()
            effective = checked(prefix.with_name(prefix.name + "-effective.glsl"), e["effective_sha256"]).read_bytes()
            ref.require(len(raw) == e["raw_bytes"] and len(effective) == e["effective_bytes"], "source size changed")
            offset = address - 0x400000
            ref.require(image[offset:offset + len(raw) + 1] == raw + b"\0", "raw source differs from original image")
            target = address == int(compat.SOURCE_ADDRESS, 16)
            ref.require(e["transformed"] is (target and modified), "incorrect substitution attribution")
            expected = compat.authorized_source(raw, manifest["transformation"]) if target and modified else raw
            ref.require(effective == expected, "unauthorized source bytes")
            edits += int(target and modified)
            ref.require(e["seq"] < program["seq"], "source evidence follows creation result")
        log = checked(directory / f"shader-{creation:03d}-program-{program['program']}-link.log",
                      program["log_sha256"]).read_bytes()
        ref.require(len(log) == program["log_bytes"] and program["api_error"] == 0, "creation error/log extent")
        ref.require(program["link_status"] == (0 if creation == 2 and not modified else 1), "unexpected link status")
        if creation == 2 and not modified:
            ref.require(b"error C7616" in log and b"gl_FragColor" in log, "missing unchanged-source failure")
        calls.append(call)
    ref.require(edits == manifest["substitutions"] == int(modified), "substitution count changed")
    return calls


def check_frames(index, events, video, directory):
    frames = [e for e in events if e["event"] == "pre_present"]
    presents = [e for e in events if e["event"] == "post_present"]
    clocks = [e for e in events if e["event"] == "clock" and e["api"] == "waveOutGetPosition"]
    ref.require(len(index) == len(frames) == len(presents) == video["frame_count"], "frame coverage mismatch")
    ref.require(len(clocks) in (len(index), len(index) + 1), "clock coverage mismatch")
    raw_frames = []
    for n, (row, frame, present, clock) in enumerate(zip(index, frames, presents, clocks)):
        ref.fields(row, ("n", "tick", "clock_tick", "audio_position", "audio_position_num",
                         "audio_position_den", "sha256"), ("raw_zst",))
        for field, value in dict(n=n, tick=n, clock_tick=n, audio_position=735*n,
                                 audio_position_num=44100*n, audio_position_den=60).items():
            ref.integer(row[field], field)
            ref.require(row[field] == value, f"frame time/order mismatch: {field}")
        ref.require(frame["n"] == frame["clock_tick"] == present["n"] == clock["n"] == n,
                    "observed frame order mismatch")
        ref.require(frame["audio_position"] == clock["value"] == 735*n and clock["wType"] == 2
                    and clock["caller"] == "0x00407b97", "observed clock mismatch")
        ref.require(clock["seq"] < frame["seq"] < present["seq"] and present["result"] is True,
                    "readback/present ordering mismatch")
        if n:
            ref.require(presents[n-1]["seq"] < clock["seq"], "clock advanced before prior present")
        ref.require(row["sha256"] == frame["sha256"], "frame hash disagrees with observation")
        ref.require((frame["width"], frame["height"], frame["format"], frame["row_order"], frame["encoding"],
                     frame["component"], frame["samples"], frame["sRGB_enabled"])
                    == (1920, 1080, "rgba8", "bottom-up", 0x2601, 0x8c17, 0, 0), "final layout changed")
        ref.require(frame["state_equal"] is True and frame["before_state_sha256"] == frame["after_state_sha256"],
                    "declared state restoration mismatch")
        if "raw_zst" in row:
            ref.verify_raw(ref.payload_path(directory, row["raw_zst"]), 1920*1080*4, row["sha256"])
            raw = checked(directory / f"frame-{n:05d}.rgba", row["sha256"])
            ref.require(raw.stat().st_size == 1920*1080*4, "raw frame extent mismatch")
            pixels = np.fromfile(raw, dtype=np.uint8).reshape(-1, 4)
            raw_frames.append({"n": n, "unique_rgba": int(len(np.unique(pixels.view("<u4")))),
                               "alpha_min": int(pixels[:, 3].min()), "alpha_max": int(pixels[:, 3].max())})
    return raw_frames


def check_pcm(bundle, events, directory, artifact_root, manifest, roots):
    audio, proof = bundle["audio"], bundle["completion"]["pcm"]
    ref.require((audio["sample_format"], audio["sample_rate"], audio["channels"], audio["layout"],
                 audio["sample_frames"], audio["start_sample"]) ==
                ("f32le", 44100, ["L", "R"], "interleaved", 19964544, 0), "native PCM layout changed")
    ref.verify_pcm_completion(proof, audio, PCM_BYTES, artifact_root, True)
    ref.verify_pcm_file(ref.payload_path(directory, audio["path"]), PCM_BYTES, audio["sha256"])
    envelope = load(ref.payload_path(artifact_root, proof["evidence"]))
    ref.require(envelope["run_id"] == manifest["run_id"] and envelope["reference_eligible"] is False
                and envelope["input"] == manifest["input"] and envelope["dependency"] == manifest["dependency"]
                and envelope["build_id"] == manifest["build"]["build_id"], "PCM evidence identity mismatch")
    if isinstance(envelope["run_manifest"], dict):
        compat.bound_file(envelope["run_manifest"], roots)
        ref.require(compat.bound_file(envelope["backend"], roots) == directory / "backend.jsonl", "PCM backend path mismatch")
    else:
        checked(artifact_root / envelope["run_manifest"], envelope["run_manifest_sha256"])
        checked(directory / "backend.jsonl", envelope["backend_sha256"])
    ref.require(all(e in events for e in envelope["observations"]), "invented PCM envelope observation")
    named = {name: one(events, name) for name in ("synth_launch", "synth_thread", "synth_complete",
             "wave_open", "wave_prepare", "wave_write", "readback_begin", "readback_end", "stability_check", "epoch")}
    complete, begin, submitted = (named[k] for k in ("synth_complete", "readback_begin", "wave_write"))
    main_tid, synth_tid = named["synth_launch"]["tid"], named["synth_thread"]["synth_tid"]
    ref.require(main_tid != synth_tid and complete["tid"] == complete["synth_tid"] == synth_tid,
                "PCM completion thread mismatch")
    ref.require(complete["site"] == "0x00401765" and named["synth_launch"]["entry"] == "0x00401636",
                "PCM completion location mismatch")
    ref.require(named["synth_launch"]["initial_tick"] == complete["initial_tick"] == proof["initial_tick"] == 1
                and complete["final_tick"] == proof["final_tick"], "PCM tick mismatch")
    for name in ("wave_open", "wave_prepare", "wave_write"):
        ref.require(named[name]["result"] == 0, "PCM submission failed")
    ref.require((named["wave_open"]["format"], named["wave_open"]["rate"], named["wave_open"]["channels"])
                == ("f32le", 44100, 2), "observed PCM format mismatch")
    ref.require(submitted["base"] == begin["base"] and submitted["bytes"] == begin["bytes"]
                == named["stability_check"]["bytes"] == PCM_BYTES, "PCM range mismatch")
    ref.require(int(complete["final_cursor"], 16) - int(begin["base"], 16) == proof["final_cursor_offset"],
                "PCM observed cursor mismatch")
    for name, seq in proof["events"].items():
        ref.require(named[name]["seq"] == seq and named[name] in envelope["observations"], "PCM event mismatch")
        if name != "synth_complete":
            ref.require(named[name]["tid"] == main_tid, "PCM acquisition thread mismatch")
    ref.require(named["readback_end"]["sha256"] == named["stability_check"]["sha256"] == audio["sha256"],
                "PCM memory hashes mismatch")
    ref.require(named["stability_check"]["seq"] < named["epoch"]["seq"]
                and named["epoch"]["E"] == 1001, "PCM/clock epoch ordering mismatch")


def review_run(mode, roots, image, roles):
    artifact_root = roots["checkout"] / "artifacts/reference"
    run_id = f"proxy-b-d9-{mode}-20261016"
    paths = {suffix: checked(artifact_root / f"{run_id}{suffix}.json", digest)
             for suffix, digest in PINS[mode].items()}
    manifest = load(paths[""])
    ref.require(manifest["run_id"] == run_id and manifest["reference_eligible"] is False
                and manifest["finalized"] is False, "diagnostic label changed")
    directory = roots["data"] / "reference" / run_id
    for name, digest in manifest["evidence"].items():
        checked(ref.payload_path(roots["data"], name), digest)
    build = manifest["build"]
    for name, digest in build["outputs"].items():
        checked(Path(build["build_directory"]) / name, digest)
    for name, digest in dict(build["original_sources"], **build["sources"]).items():
        checked(Path(build["build_directory"]) / "source-snapshot" / name, digest)
    for backend in build["backends"].values():
        checked(Path(backend["path"]), backend["sha256"])
    for name in ("opengl32.dll", "winmm.dll"):
        checked(Path(manifest["stage"]) / name, build["outputs"][name])
    checked(Path(manifest["stage"]) / manifest["input"]["exe"], compat.INPUT_HASHES["exe"])
    checked(roots["shared"] / manifest["input"]["archive"], compat.INPUT_HASHES["archive"])
    checked(roots["data"] / "reference/dependencies/gm.dls", compat.INPUT_HASHES["bank"])
    checked(Path(manifest["prefix_baseline"]["inventory"]), manifest["prefix_baseline"]["inventory_sha256"])
    events = [ref.load_json(line) for line in (directory / "backend.jsonl").read_text().splitlines()]
    numbered = [e for e in events if "seq" in e]
    ref.require([e["seq"] for e in numbered] == list(range(1, len(numbered)+1)), "event sequence changed")
    ref.require(len({e["pid"] for e in events}) == 1, "mixed run processes")
    calls = check_sources(manifest, events, directory, image, roles)
    context = one(events, "compat_context")
    ref.require((context["version"], context["profile_mask"], context["flags"], context["driver_debug"])
                == ("4.6.0 NVIDIA 610.57.04", 2, 0, False), "context identity changed")
    uses = [e for e in events if e["event"] == "program_use"]
    for e in uses:
        ref.require((e["hdc"], e["hglrc"], e["tid"]) == (context["hdc"], context["hglrc"], context["tid"]),
                    "program use context changed")
    result = {"run_id": run_id, "producer_status": manifest["status"], "shader_calls": len(calls),
              "original_strings_checked": 235, "reference_accepted": False}
    if mode == "control3":
        failed = [e for e in uses if e["post_error"]]
        ref.require(len(failed) == 1 and failed[0]["caller"] == "0x004076aa"
                    and failed[0]["program"] == calls[1]["program"] and failed[0]["pre_error"] == 0
                    and failed[0]["post_error"] == 0x502, "negative control attribution changed")
        ref.require(manifest["status"] == "failed" and manifest["launcher_exit"] == 125
                    and not any(e["event"] == "pre_present" for e in events), "negative control stop changed")
        result["negative_control"] = "C7616/link=false/original-use 0x0502"
        return result, manifest, None
    ref.require(all(e["pre_error"] == e["post_error"] == 0 and e["after_program"] == e["program"] for e in uses)
                and not any(e["event"] in ("gl_error", "failure") for e in events), "remedy runtime error")
    if "-eligibility" in paths:
        sidecar = load(paths["-eligibility"])
        result["provenance"] = compat.assess(paths["-eligibility"], roots)["status"]
        ref.require(len(sidecar["calls"]) == len(calls), "sidecar coverage mismatch")
        for call, observed in zip(sidecar["calls"], calls):
            ref.require(all(call[k] == v for k, v in observed.items()), "sidecar call attribution mismatch")
            for index, (before, after) in enumerate(zip(call["input"], call["forwarded"])):
                prefix = f"shader-{call['sequence']:03d}-{index:03d}"
                ref.require(compat.bound_file(before, roots) == directory / f"{prefix}-raw.glsl"
                            and compat.bound_file(after, roots) == directory / f"{prefix}-effective.glsl",
                            "sidecar source binding mismatch")
    bundle = load(paths["-small-capture"])
    ref.require(bundle["run_id"] == run_id and bundle["reference_eligible"] is False
                and bundle["finalized"] is bundle["completion"]["finalized"] is False
                and bundle["scene_boundaries_observed"] is False, "small-capture label changed")
    if isinstance(bundle["run_manifest"], dict):
        ref.require(compat.bound_file(bundle["run_manifest"], roots) == paths[""], "bundle run binding mismatch")
        compat.bound_file(bundle["package_tool"], roots)
    else:
        ref.require(checked(artifact_root / bundle["run_manifest"], bundle["run_manifest_sha256"]) == paths[""],
                    "bundle run binding mismatch")
        checked(roots["checkout"] / bundle["package_tool"]["path"], bundle["package_tool"]["sha256"])
    video = bundle["video"]
    ref.require((video["width"], video["height"], video["row_stride"], video["pixel_format"], video["row_order"])
                == (1920, 1080, 7680, "rgba8", "bottom-up"), "bundle layout mismatch")
    index_path = checked(ref.payload_path(artifact_root, video["index"]), video["index_sha256"])
    index = [ref.load_json(line) for line in index_path.read_text().splitlines()]
    result["raw_frames"] = check_frames(index, events, video, directory)
    ref.require(bundle["completion"]["frames_observed"] == bundle["completion"]["frames_hashed"] == len(index),
                "bundle completion counters mismatch")
    check_pcm(bundle, events, directory, artifact_root, manifest, roots)
    starts = [e for e in events if e["event"] == "clock" and e.get("timeline") is False]
    ref.require([e["value"] for e in starts] == list(range(1001)), "startup clock schedule changed")
    first_clock = next(e for e in events if e["event"] == "clock" and e["api"] == "waveOutGetPosition")
    ref.require(one(events, "epoch")["seq"] < first_clock["seq"], "timeline begins before epoch")
    draw, atlas = one(events, "first_draw_state"), one(events, "noise_atlas")
    ref.require(draw["program"] == calls[1]["program"] and draw["fbo_status"] == 0x8cd5
                and draw["viewport"] == [0, 0, 16384, 128] and draw["draw_buffers"] == [0x8ce0] + [0]*7
                and draw["color_mask"] == [1]*4 and draw["blend"] == draw["srgb"] == 0
                and draw["clamp_fragment_color"] == 0x891d
                and draw["vertex_path"] == "glRecti", "first-pass state changed")
    ref.require((atlas["caller"], atlas["width"], atlas["height"], atlas["internal_format"], atlas["bytes"])
                == ("0x004079dc", 16384, 128, 0x8814, 33554432) and atlas["pack"] == [4] + [0]*7,
                "atlas acquisition layout changed")
    atlas_path = checked(directory / "noise-atlas.rgba32f", atlas["sha256"])
    ref.require(atlas_path.stat().st_size == atlas["bytes"], "atlas extent changed")
    pixels = np.fromfile(atlas_path, dtype="<f4").reshape(-1, 4)
    result["atlas"] = {"bytes": atlas["bytes"], "finite": bool(np.isfinite(pixels).all()),
                       "alpha_zero": bool((pixels[:, 3] == 0).all()),
                       "rgb_range": [float(pixels[:, :3].min()), float(pixels[:, :3].max())],
                       "unique_rgb": int(len(np.unique(pixels[:, :3], axis=0)))}
    result.update(frames=len(index), pcm_bytes=PCM_BYTES, actual_stop=bundle["actual_stop"])
    if mode == "boundary":
        recovery = load(directory / "supervisor-recovery.json")
        ref.require(manifest["status"] == "failed" and manifest["launcher_exit"] is None
                    and bundle["actual_stop"] == recovery["failure"] == manifest["first_failed_check"]
                    and recovery["failure"]["native_exit_observed"] is False and len(index) == 67
                    and not any(e["event"] == "planned_partial_stop" for e in events), "failed boundary relabeled")
        ref.require([r["n"] for r in result["raw_frames"]] == [0, 1, 2, 60], "boundary sparse coverage changed")
    else:
        ref.require(bundle["actual_stop"] == one(events, "planned_partial_stop") and len(index) == 3
                    and manifest["status"] == "partial" and manifest["launcher_exit"] == 0,
                    "planned diagnostic stop changed")
        ref.require([r["n"] for r in result["raw_frames"]] == [0, 1, 2], "short raw coverage changed")
    try:
        ref.load_run(paths["-small-capture"], directory)
    except ref.InvalidCapture:
        result["full_reference_rejected"] = True
    else:
        raise ref.InvalidCapture("diagnostic incorrectly accepted as full reference")
    return result, manifest, index


def assess(roots):
    image = checked(roots["data"] / "reverse/confirmed-debug/postfix-00400000.bin", IMAGE_HASH).read_bytes()
    roles = original_roles(image)
    reviewed = {mode: review_run(mode, roots, image, roles) for mode in PINS}
    _, a, ai = reviewed["primary"]
    _, b, bi = reviewed["repeat"]
    ref.require(a["run_id"] != b["run_id"] and a["prefix_baseline"] == b["prefix_baseline"]
                and a["build"] == b["build"] and ai == bi, "short pair identity/frame mismatch")
    for field in ("os", "wine", "packages", "gpu", "display"):
        ref.require(a["environment"][field] == b["environment"][field], "short pair environment mismatch")
    path_settings = {"XDG_CACHE_HOME", "__GL_SHADER_DISK_CACHE_PATH", "EIDOLON_B_LOG", "EIDOLON_B_OUTPUT"}
    ref.require({k: v for k, v in a["environment"]["settings"].items() if k not in path_settings}
                == {k: v for k, v in b["environment"]["settings"].items() if k not in path_settings},
                "short pair behavioral settings mismatch")
    directories = [roots["data"] / "reference" / m["run_id"] for m in (a, b)]
    files = ["pcm.f32le", "noise-atlas.rgba32f"] + [f"frame-{n:05d}.rgba" for n in range(3)]
    for name in files:
        ref.require(ref.first_byte_difference(directories[0] / name, directories[1] / name) is None,
                    f"short pair byte mismatch: {name}")
    return {"status": "DIAGNOSTIC_ONLY", "reference_accepted": False, "g5": "partial", "g6": "open",
            "runs": [r[0] for r in reviewed.values()], "pair_files_byte_equal": files,
            "pcm_content": content_summary(directories[0] / "pcm.f32le"),
            "limitations": ["Saved observations and pinned source review do not authenticate all runtime behavior.",
                            "G1 ABI/canaries/negative controls, G4 boundaries/end and downstream scene identity remain open.",
                            "Primary/repeat forward counts are source-derived; state hashes duplicate the guarded before digest.",
                            "No full capture/repeatability, historical fidelity or restoration acceptance is established."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--data-root", type=Path, default=Path(os.environ.get("EIDOLON_DATA", "data")))
    parser.add_argument("--shared-root", type=Path, default=Path(os.environ.get("EIDOLON_ROOT", ".")))
    args = parser.parse_args(argv)
    try:
        result = assess({"checkout": args.capture_root.resolve(), "data": args.data_root.resolve(),
                         "shared": args.shared_root.resolve()})
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "FAIL", "reference_accepted": False, "reason": str(error)}))
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
