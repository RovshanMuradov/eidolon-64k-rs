#!/usr/bin/env python3
"""Read-only assessment of immutable B evidence; never accepts a reference."""

import argparse
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

import numpy as np

if __package__:
    from . import reference as ref
else:
    import reference as ref


# Pins the diagnostic reviewed by T10, not an expected future audio reference.
B_MANIFEST_SHA256 = "21fdd559b26651474bee6c3b0820630dd71f2d0e85b452b85b97f3fa992fdf13"
PCM_BYTES = ref.ORIGINAL_AUDIO_FRAMES * 8
VISUAL_END_SAMPLE = ref.ORIGINAL_VISUAL_END_TICK * 44100 // 60


def one(rows, event):
    matches = [r for r in rows if r["event"] == event]
    ref.require(len(matches) == 1, f"expected one {event}, got {len(matches)}")
    return matches[0]


def pointer(value):
    ref.require(isinstance(value, str) and re.fullmatch(r"0x[0-9a-f]{8}", value),
                "expected observed 32-bit pointer")
    return int(value, 16)


def completion_from_events(rows, checksum, evidence, evidence_hash):
    """Project observed fields into the existing PCM primitive, not a run manifest."""
    numbered = [r for r in rows if "seq" in r]
    for row in numbered:
        ref.integer(row["seq"], "observation sequence", 1)
        ref.integer(row["pid"], "observation process", 1)
        ref.integer(row["tid"], "observation thread", 1)
    ref.require([r["seq"] for r in numbered] == list(range(1, len(numbered) + 1)),
                "observation sequence has a gap, duplicate or reordering")
    ref.require(len({r["pid"] for r in rows}) == 1, "mixed observation processes")
    ref.require(all("seq" in r or r["event"] == "backend_probe" for r in rows),
                "unsequenced acquisition event")
    names = ("bootstrap_before_synth", "hooks_installed", "synth_launch", "synth_thread",
             "wave_open", "wave_prepare", "wave_write", "timeline_gate_enter",
             "synth_complete", "hook_context", "readback_begin", "readback_end",
             "stability_check", "epoch", "failure")
    events = {name: one(rows, name) for name in names}
    ref.require(all(events[a]["seq"] < events[b]["seq"] for a, b in zip(names, names[1:])),
                "B diagnostic event ordering changed")
    main_tid = events["hooks_installed"]["main_tid"]
    synth_tid = events["synth_thread"]["synth_tid"]
    ref.require(main_tid != synth_tid, "synthesis must have a distinct observed thread")
    for name, event in events.items():
        expected = synth_tid if name in ("synth_complete", "hook_context") else main_tid
        ref.require(event["tid"] == expected, f"{name}: inconsistent thread")
    start, end = events["synth_launch"], events["synth_complete"]
    ref.require(events["hooks_installed"]["synth_not_launched"] is True,
                "hooks were not installed before synthesis")
    ref.require(start["entry"] == "0x00401636" and end["site"] == "0x00401765",
                "unexpected synthesis/completion location")
    ref.require(end["synth_tid"] == synth_tid and start["initial_tick"] == end["initial_tick"],
                "inconsistent synthesis identity/tick")
    opened = events["wave_open"]
    ref.require((opened["format"], opened["channels"], opened["rate"]) == ("f32le", 2, 44100),
                "observed PCM layout is not native")
    for name in ("wave_open", "wave_prepare", "wave_write"):
        ref.require(events[name]["result"] == 0, f"{name} failed")
    submitted, begin = events["wave_write"], events["readback_begin"]
    ref.require(submitted["bytes"] == begin["bytes"] == events["stability_check"]["bytes"] == PCM_BYTES,
                "observed acquisition/stability extent is incomplete")
    ref.require(submitted["base"] == begin["base"], "readback base differs from submission")
    ref.require(events["readback_end"]["sha256"] == checksum, "acquisition hash differs from PCM")
    proof = {
        "submitted_bytes": submitted["bytes"], "initial_tick": end["initial_tick"],
        "final_tick": end["final_tick"],
        "final_cursor_offset": pointer(end["final_cursor"]) - pointer(submitted["base"]),
        "events": {name: events[name]["seq"] for name in
                   ("synth_complete", "readback_begin", "readback_end", "stability_check")},
        "stable_sha256": events["stability_check"]["sha256"],
        "evidence": evidence, "evidence_sha256": evidence_hash,
    }
    # Only fields used by the PCM primitive; no synthetic frame/end/identity fields.
    audio = {"sample_frames": submitted["bytes"] // 8, "sha256": checksum}
    return proof, audio


def content_summary(path):
    pcm = np.memmap(path, mode="r", dtype="<f4").reshape(-1, 2)
    nonzero = np.any(pcm != 0, axis=1)
    indices = np.flatnonzero(nonzero)
    finite = np.isfinite(pcm)
    tail = pcm[VISUAL_END_SAMPLE:]
    result = {
        "sample_frames": len(pcm), "nonfinite_scalars": int(np.count_nonzero(~finite)),
        "nonzero_frames": int(np.count_nonzero(nonzero)),
        "first_nonzero_frame": int(indices[0]) if len(indices) else None,
        "last_nonzero_frame": int(indices[-1]) if len(indices) else None,
        "nonzero_scalars_per_channel": np.count_nonzero(pcm, axis=0).tolist(),
        "unequal_stereo_frames": int(np.count_nonzero(pcm[:, 0] != pcm[:, 1])),
        "min_per_channel": pcm.min(axis=0).tolist() if finite.all() else None,
        "max_per_channel": pcm.max(axis=0).tolist() if finite.all() else None,
        "tail_sample_frames": len(tail),
        "tail_nonzero_scalars_per_channel": np.count_nonzero(tail, axis=0).tolist(),
    }
    # Content statistics are descriptive, never a silence/clipping tolerance.
    return result


def expect_rejected(action, reason):
    try:
        action()
    except ref.InvalidCapture as error:
        ref.require(reason in str(error), f"wrong corruption rejection: {error}")
        return str(error)
    raise ref.InvalidCapture(f"corruption escaped detection: {reason}")


def corruption_checks(pcm, checksum, proof, audio, root):
    """Mutate disposable copies; compare bytes even after updating their hashes."""
    results = {}
    parent = Path("/tmp/opencode/eidolon/T10")
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pcm-corruption-", dir=parent) as temporary:
        changed = Path(temporary) / "pcm.f32le"
        for name, offset in (("first-byte", 0), ("retained-tail-byte", PCM_BYTES - 1)):
            shutil.copyfile(pcm, changed)
            with changed.open("r+b") as stream:
                stream.seek(offset)
                byte = stream.read(1)
                stream.seek(offset)
                stream.write(bytes([byte[0] ^ 1]))
            results[name] = expect_rejected(
                lambda: ref.verify_pcm_file(changed, PCM_BYTES, checksum), "PCM SHA-256 mismatch")
            ref.verify_pcm_file(changed, PCM_BYTES, ref.hash_file(changed))
            difference = ref.first_byte_difference(pcm, changed)
            ref.require(difference == offset, "updated-hash byte comparison missed corruption")
            results[name + "-updated-hash"] = {"first_differing_byte": difference}
        for name, size in (("trim-one-frame", PCM_BYTES - 8),
                           ("trim-to-visual-end", VISUAL_END_SAMPLE * 8),
                           ("append-one-frame", PCM_BYTES + 8)):
            shutil.copyfile(pcm, changed)
            with changed.open("r+b") as stream:
                stream.truncate(size)
            results[name] = expect_rejected(
                lambda: ref.verify_pcm_file(changed, PCM_BYTES, checksum), "PCM byte length")
        changed.unlink()
        results["missing-pcm"] = expect_rejected(
            lambda: ref.verify_pcm_file(changed, PCM_BYTES, checksum), "missing PCM payload")
        with pcm.open("rb") as source, changed.open("wb") as target:
            first = source.read(8)
            shutil.copyfileobj(source, target)
            target.write(first)
        ref.verify_pcm_file(changed, PCM_BYTES, ref.hash_file(changed))
        difference = ref.first_byte_difference(pcm, changed)
        ref.require(difference is not None, "one-sample-frame shift escaped exact comparison")
        results["one-sample-frame-shift-updated-hash"] = {"first_differing_byte": difference}
    faults = (
        ("final_tick", proof["final_tick"] - 1, "PCM synthesis tick delta"),
        ("final_cursor_offset", PCM_BYTES - 8, "PCM final synthesis cursor"),
        ("stable_sha256", "0" * 64, "PCM post-readback stability hash mismatch"),
        ("evidence_sha256", "0" * 64, "PCM completion evidence SHA-256 mismatch"),
    )
    for key, value, reason in faults:
        bad = deepcopy(proof)
        bad[key] = value
        results[key] = expect_rejected(
            lambda: ref.verify_pcm_completion(bad, audio, PCM_BYTES, root, True), reason)
    bad = deepcopy(proof)
    bad["events"]["readback_begin"] = bad["events"]["synth_complete"]
    results["premature-read"] = expect_rejected(
        lambda: ref.verify_pcm_completion(bad, audio, PCM_BYTES, root, True),
        "PCM acquisition must follow")
    ref.verify_pcm_file(pcm, PCM_BYTES, checksum)
    ref.verify_pcm_completion(proof, audio, PCM_BYTES, root, True)
    return results


def assess(manifest_path, data_root, source_root, corruptions=False):
    ref.require(ref.hash_file(manifest_path) == B_MANIFEST_SHA256, "immutable B manifest changed")
    manifest = ref.load_json(manifest_path.read_text())
    ref.require(manifest["reference_eligible"] is False and manifest["diagnostic_incomplete"] is True,
                "expected incomplete, ineligible B diagnostic")
    ref.require(manifest["input"]["exe_sha256"] == ref.ORIGINAL_SHA256, "unexpected original identity")
    paths = {}
    for relative, checksum in manifest["evidence"].items():
        path = ref.payload_path(data_root, relative)
        ref.require(ref.hash_file(path) == checksum, f"diagnostic evidence SHA-256 mismatch: {relative}")
        paths[path.name] = (path, relative, checksum)
    for relative, checksum in manifest["build"]["sources"].items():
        path = ref.payload_path(source_root, relative)
        ref.require(ref.hash_file(path) == checksum, f"reviewed capture source changed: {relative}")
    backend, evidence, evidence_hash = paths["backend.jsonl"]
    pcm, _, checksum = paths["pcm.f32le"]
    runner, _, _ = paths["runner.log"]
    rows = [ref.load_json(line) for line in backend.read_text().splitlines()]
    for event in manifest["observations"]:
        ref.require(event in rows, "manifest observation absent from original stream")
    proof, audio = completion_from_events(rows, checksum, evidence, evidence_hash)
    ref.verify_pcm_completion(proof, audio, PCM_BYTES, data_root, True)
    ref.verify_pcm_file(pcm, PCM_BYTES, checksum)
    starts = [r for r in rows if r["event"] == "clock" and r.get("timeline") is False]
    ref.require([r["value"] for r in starts] == list(range(1001)), "startup schedule differs")
    positions = [r for r in rows if r["event"] == "clock" and r["api"] == "waveOutGetPosition"]
    ref.require(len(positions) == 1 and positions[0]["n"] == positions[0]["value"] == 0
                and positions[0]["wType"] == 2, "missing observed frame-zero sample cursor")
    epoch, failure = one(rows, "epoch"), one(rows, "failure")
    ref.require(epoch["E"] == 1001 and proof["events"]["stability_check"] < epoch["seq"]
                < positions[0]["seq"] < failure["seq"], "invalid startup/acquisition order")
    terminals = [line for line in runner.read_text().splitlines() if line.startswith("WINE_EXIT=")]
    ref.require(terminals == manifest["runner_terminal"], "runner terminal disagrees with manifest")
    counts = Counter(r["event"] for r in rows)
    ref.require(counts["pre_present"] == counts["post_present"] == 0, "unexpected B frame observations")
    rejected = expect_rejected(lambda: ref.load_run(manifest_path, data_root), "invalid fields")
    result = {
        "status": "DIAGNOSTIC_ONLY", "reference_accepted": False,
        "run_id": manifest["run_id"], "manifest_sha256": B_MANIFEST_SHA256,
        "checks": "PCM file, observed completion, bound evidence and capture-source hashes agree",
        "pcm_bytes": PCM_BYTES, "completion_events": proof["events"],
        "initial_tick": proof["initial_tick"], "final_tick": proof["final_tick"],
        "final_cursor_offset": proof["final_cursor_offset"],
        "content": content_summary(pcm), "epoch": epoch["E"],
        "observed_sample_positions": len(positions), "pre_present_frames": counts["pre_present"],
        "failure": failure, "terminal": terminals,
        "full_reference_rejected": rejected,
        "limitations": [
            "One failed B invocation; no independent repeatability or A gate evidence.",
            "No real pixels, layout/read-buffer validation, scene anchors or controlled visual endpoint.",
            "Source review supports EBP+8 cursor, locked event ordering and separate source-memory hashes; runtime instrumentation claims are not authenticated by hashes alone.",
            "The B manifest binds source/run/dependency identity; backend.jsonl alone lacks that envelope for draft-3 completion evidence.",
            "The context event repeats one hash; it does not establish complete hook/FP/ABI preservation.",
            "GL_initial_error records GetLastError=183, not a GL enum; preexisting/query error cause is unresolved.",
        ],
    }
    if corruptions:
        result["corruption_checks"] = corruption_checks(pcm, checksum, proof, audio, data_root)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--data-root", type=Path, default=Path(os.environ.get("EIDOLON_DATA", "data")))
    parser.add_argument("--source-root", type=Path, help="B checkout containing manifest-pinned capture sources")
    parser.add_argument("--corruptions", action="store_true", help="exercise faults on disposable PCM copies")
    args = parser.parse_args(argv)
    try:
        result = assess(args.manifest, args.data_root,
                        args.source_root or args.manifest.resolve().parents[2], args.corruptions)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "FAIL", "reference_accepted": False, "reason": str(error)}))
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0  # Successful diagnostic assessment, never full-reference PASS.


if __name__ == "__main__":
    sys.exit(main())
