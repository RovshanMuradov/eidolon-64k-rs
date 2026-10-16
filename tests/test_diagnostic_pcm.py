"""Faults in immutable B's recorded evidence; all edits are in-memory copies."""

from copy import deepcopy
import os
from pathlib import Path

import pytest

from tools.verify import diagnostic_pcm as diagnostic
from tools.verify import reference


@pytest.fixture
def observed():
    root = Path(os.environ.get("EIDOLON_ROOT", Path(__file__).resolve().parents[1]))
    manifest = root / ".worktrees/T2/artifacts/reference/proxy-b-g1-20261016.json"
    data = Path(os.environ.get("EIDOLON_DATA", root / "data"))
    if not manifest.is_file():
        pytest.skip("immutable B diagnostic not present")
    assert reference.hash_file(manifest) == diagnostic.B_MANIFEST_SHA256
    m = reference.load_json(manifest.read_text())
    evidence = f'reference/{m["run_id"]}/backend.jsonl'
    backend = data / evidence
    assert reference.hash_file(backend) == m["evidence"][evidence]
    rows = [reference.load_json(line) for line in backend.read_text().splitlines()]
    checksum = m["evidence"][f'reference/{m["run_id"]}/pcm.f32le']
    return rows, checksum, evidence, m["evidence"][evidence], data


def test_actual_completion_projection_keeps_native_extent(observed):
    rows, checksum, evidence, evidence_hash, root = observed
    proof, audio = diagnostic.completion_from_events(rows, checksum, evidence, evidence_hash)
    reference.verify_pcm_completion(proof, audio, diagnostic.PCM_BYTES, root, True)
    assert proof["final_cursor_offset"] == 159716352
    assert proof["final_tick"] - proof["initial_tick"] == 19964544
    assert proof["events"] == dict(synth_complete=5878, readback_begin=5880,
                                   readback_end=5881, stability_check=5882)


@pytest.mark.parametrize("fault,reason", [
    ("missing-completion", "gap, duplicate or reordering"),
    ("duplicated-completion", "gap, duplicate or reordering"),
    ("read-before-completion", "gap, duplicate or reordering"),
    ("unsequenced-completion", "gap, duplicate or reordering"),
    ("completion-on-main", "inconsistent thread"),
    ("other-process", "mixed observation processes"),
    ("wrong-completion-site", "unexpected synthesis/completion location"),
    ("wrong-read-base", "readback base differs"),
    ("short-stability-range", "extent is incomplete"),
    ("acquisition-hash", "acquisition hash differs"),
    ("wrong-synthesis-start", "inconsistent synthesis identity/tick"),
    ("audio-api-failed", "wave_write failed"),
    ("wrong-audio-format", "layout is not native"),
])
def test_corrupt_observed_event_history_fails(observed, fault, reason):
    rows, checksum, evidence, evidence_hash, _ = observed
    rows = deepcopy(rows)
    complete = diagnostic.one(rows, "synth_complete")
    if fault == "missing-completion":
        rows.remove(complete)
    elif fault == "duplicated-completion":
        rows.insert(rows.index(complete), deepcopy(complete))
    elif fault == "read-before-completion":
        a, b = rows.index(complete), rows.index(diagnostic.one(rows, "readback_begin"))
        rows[a], rows[b] = rows[b], rows[a]
    elif fault == "unsequenced-completion":
        del complete["seq"]
    elif fault == "completion-on-main":
        complete["tid"] = diagnostic.one(rows, "hooks_installed")["main_tid"]
    elif fault == "other-process":
        complete["pid"] += 1
    elif fault == "wrong-completion-site":
        complete["site"] = "0x00401764"
    elif fault == "wrong-read-base":
        diagnostic.one(rows, "readback_begin")["base"] = "0x00f02078"
    elif fault == "short-stability-range":
        diagnostic.one(rows, "stability_check")["bytes"] -= 8
    elif fault == "acquisition-hash":
        diagnostic.one(rows, "readback_end")["sha256"] = "0" * 64
    elif fault == "wrong-synthesis-start":
        diagnostic.one(rows, "synth_launch")["initial_tick"] = 0
    elif fault == "audio-api-failed":
        diagnostic.one(rows, "wave_write")["result"] = 1
    elif fault == "wrong-audio-format":
        diagnostic.one(rows, "wave_open")["format"] = "s32le"
    with pytest.raises(reference.InvalidCapture, match=reason):
        diagnostic.completion_from_events(rows, checksum, evidence, evidence_hash)
