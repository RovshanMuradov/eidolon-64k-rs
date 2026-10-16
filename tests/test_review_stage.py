"""Real D11 evidence and independently injected faults; no target/GPU execution."""

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import shutil

import pytest
import zstandard

from tools.verify import reference as ref, review_stage as review


@pytest.fixture(scope="module")
def roots():
    checkout = Path(__file__).resolve().parents[1]
    return {"checkout": Path(os.environ.get("EIDOLON_CAPTURE_ROOT", checkout)).resolve(),
            "shared": Path(os.environ["EIDOLON_ROOT"]), "data": Path(os.environ["EIDOLON_DATA"])}


@pytest.fixture(scope="module")
def saved(roots):
    run = "proxy-b-d11-boundary3-20261016"
    artifacts = roots["checkout"] / "artifacts/reference"
    bundle = review.load(artifacts / f"{run}-small-capture.json")
    directory = roots["data"] / "reference" / run
    events, counts = review.stream(directory / "backend.jsonl")
    index = [ref.load_json(line) for line in (artifacts / bundle["video"]["index"]).read_text().splitlines()]
    return bundle, directory, events, counts, index


def test_independent_staged_verdict(roots):
    result = review.assess(roots)
    assert result["status"] == "STAGED_G5_PARTIAL"
    assert result["reference_accepted"] is result["full_duration_ready"] is False
    assert result["g6"] == "open" and result["pair_files_byte_equal"] == 33
    assert len(result["live_rejection_controls"]) == 12
    for run in result["runs"]:
        assert run["frames"] == 1443 and run["raw_frames"] == 31
        assert run["active_cloud_draws"] == 0 and run["first_return_snapshots"] == 16
        assert sum(run["abi_return_totals"]) == 626647 and run["full_reference_rejected"]


@pytest.mark.parametrize("fault", ["missing", "duplicate", "reordered", "clock-shift", "sample-shift"])
def test_boundary_record_faults(saved, fault):
    bundle, directory, events, _, original = saved
    index = deepcopy(original)
    if fault == "missing":
        index.pop(1439)
    elif fault == "duplicate":
        index[1440] = deepcopy(index[1439])
    elif fault == "reordered":
        index[1439], index[1440] = index[1440], index[1439]
    else:
        index[1440]["clock_tick" if fault == "clock-shift" else "audio_position"] += 1
    with pytest.raises(ref.InvalidCapture):
        review.short.check_frames(index, events, bundle["video"], directory)


@pytest.mark.parametrize("event,field", [("clock", "value"), ("clock_routes_checked", "qpc"),
                                       ("frame_state", "after")])
def test_observed_clock_and_restoration_faults(saved, event, field):
    events = list(saved[2])
    i = next(i for i, e in enumerate(events) if e["event"] == event and e.get("n") == 1440)
    events[i] = deepcopy(events[i])
    if field == "after":
        events[i][field][3] = 1
        check = review.check_state
    else:
        events[i][field] += 1
        check = review.check_clock
    with pytest.raises(ref.InvalidCapture):
        check(events)


@pytest.mark.parametrize("fault", ["gpr", "flags", "stack", "return", "x87", "mxcsr", "xmm"])
def test_raw_canary_faults_despite_refreshed_hashes(saved, fault):
    e = deepcopy(next(e for e in saved[2] if e["event"] == "abi_canary" and e["api"] == 6))
    directory = saved[1]
    raw = [bytearray((directory / f"abi-06-1-{side}-{kind}.bin").read_bytes())
           for kind in ("gpr", "fx") for side in ("before", "after")]
    offsets = {"gpr": 0, "flags": 32, "return": 28, "x87": 0, "mxcsr": 24, "xmm": 160}
    if fault == "stack":
        e["return_esp"] += 4
    else:
        raw[3 if fault in ("x87", "mxcsr", "xmm") else 1][offsets[fault]] ^= 1
    e["after_fx_sha256"] = hashlib.sha256(raw[3]).hexdigest()
    with pytest.raises(ref.InvalidCapture):
        review.check_canary(e, *raw)


@pytest.mark.parametrize("offset", [28, 184, 196, 228])
def test_exception_context_faults(saved, offset):
    directory = saved[1]
    before = (directory / "completion-context-before.bin").read_bytes()
    after = bytearray((directory / "completion-context-after.bin").read_bytes())
    after[offset] ^= 1
    with pytest.raises(ref.InvalidCapture):
        review.check_context(before, after, completion=True)


@pytest.mark.parametrize("fault", ["alpha", "truncated", "trailing", "concatenated"])
def test_boundary_zstandard_faults(saved, tmp_path, fault):
    directory, row = saved[1], saved[4][1439]
    packed = (directory / row["raw_zst"]).read_bytes()
    if fault == "alpha":
        pixels = bytearray(zstandard.ZstdDecompressor().decompress(packed))
        pixels[3] ^= 1
        packed = zstandard.ZstdCompressor().compress(pixels)
    elif fault == "truncated":
        packed = packed[:-1]
    elif fault == "trailing":
        packed += b"unexpected"
    else:
        packed += packed
    changed = tmp_path / "changed.raw.zst"
    changed.write_bytes(packed)
    with pytest.raises(ref.InvalidCapture):
        ref.verify_raw(changed, 8294400, row["sha256"])
    if fault == "alpha":
        # Refreshed declarations cannot make a changed alpha byte equal its peer.
        raw = tmp_path / "changed.rgba"
        raw.write_bytes(pixels)
        ref.verify_raw(changed, 8294400, ref.hash_file(raw))
        assert ref.first_byte_difference(directory / "frame-01439.rgba", raw) == 3


@pytest.mark.parametrize("fault", ["first", "tail", "shift", "trim-tail", "atlas"])
def test_full_extent_bytes_and_refreshed_hash_faults(saved, tmp_path, fault):
    source = saved[1] / ("noise-atlas.rgba32f" if fault == "atlas" else "pcm.f32le")
    changed = tmp_path / "changed.bin"
    try:
        if fault == "shift":
            with source.open("rb") as src, changed.open("wb") as dst:
                first = src.read(8)
                shutil.copyfileobj(src, dst)
                dst.write(first)
        else:
            shutil.copyfile(source, changed)
            with changed.open("r+b") as dst:
                if fault == "trim-tail":
                    dst.truncate(19845000*8)
                else:
                    offset = source.stat().st_size-1 if fault == "tail" else 0
                    dst.seek(offset)
                    value = dst.read(1)
                    dst.seek(offset)
                    dst.write(bytes([value[0] ^ 1]))
        if fault == "trim-tail":
            with pytest.raises(ref.InvalidCapture):
                ref.verify_pcm_file(changed, 159716352, ref.hash_file(changed))
        elif fault != "atlas":
            ref.verify_pcm_file(changed, 159716352, ref.hash_file(changed))
        assert ref.first_byte_difference(source, changed) is not None
    finally:
        changed.unlink(missing_ok=True)
