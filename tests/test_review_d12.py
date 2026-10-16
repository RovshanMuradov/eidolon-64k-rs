"""D12 real evidence, independently mutated on copies; no target/GPU execution."""
from copy import deepcopy
import os
from pathlib import Path
import shutil

import pytest
import zstandard

from tools.verify import reference as ref, review_d12 as review


@pytest.fixture(scope="module")
def roots():
    return {"checkout": Path(__file__).resolve().parents[1], "shared": Path(os.environ["EIDOLON_ROOT"]),
            "data": Path(os.environ["EIDOLON_DATA"])}


@pytest.fixture(scope="module")
def saved(roots):
    run = next(iter(review.PINS))
    directory = roots["data"]/"reference"/run
    artifacts = roots["checkout"]/"artifacts/reference"
    bundle = review.load(artifacts/f"{run}-partial-reference.json")
    events, _ = review.stage.stream(directory/"backend.jsonl", ("GetProcAddress", "glCreateShaderProgramv"))
    index = [ref.load_json(line) for line in (artifacts/bundle["video"]["index"]).read_text().splitlines()]
    image = (roots["data"]/"reverse/confirmed-debug/postfix-00400000.bin").read_bytes()
    return bundle, directory, events, index, image


def test_g5_ready_not_g6(roots):
    result = review.assess(roots)
    assert result["status"] == "G5_READY" and result["full_duration_ready"] is True
    assert result["reference_accepted"] is False and result["g6"] == "open"
    assert result["evidence_blockers"] == [] and result["pair_files_byte_equal"] == 133
    assert result["baseline_entries_verified"] == 1875 and len(result["live_exception_faults"]) == 2
    assert all(r["frames"] == 5763 and r["raw_frames"] == 111 and r["abi_raw_pairs"] == 74 for r in result["runs"])


def changed_event(events, event, field, value, **select):
    result = list(events)
    i = next(i for i, e in enumerate(result) if e["event"] == event and all(e.get(k) == v for k, v in select.items()))
    result[i] = deepcopy(result[i])
    result[i][field] = value
    return result


@pytest.mark.parametrize("kind,offset", [(kind, offset) for kind in range(3) for offset in (0, 12, 28, 32, 36, 60, 196)])
def test_physical_resume_faults_with_refreshed_hash(saved, kind, offset):
    directory = saved[1]
    e = deepcopy(next(e for e in saved[2] if e["event"] == "native_resumed" and e["kind"] == kind))
    context = (directory/f"resume-{kind}-expected-context.bin").read_bytes()
    gpr = bytearray((directory/f"resume-{kind}-gpr.bin").read_bytes())
    fx = bytearray((directory/f"resume-{kind}-fx.bin").read_bytes())
    if offset < 36:
        gpr[offset] ^= 1
    else:
        fx[offset-36] ^= 1  # x87 CW, MXCSR, XMM0.
    e["fx_sha256"] = review.sha(fx)
    with pytest.raises(ref.InvalidCapture):
        review.check_resume(e, context, gpr, fx)


@pytest.mark.parametrize("event,field,value", [("resolver_control", "by_ordinal", 0), ("resolver_control", "missing_name", 1),
                                               ("lookup", "routed", True)])
def test_resolver_faults(saved, event, field, value):
    events = changed_event(saved[2], event, field, value, **({"api": "GetProcAddress"} if event == "lookup" else {}))
    with pytest.raises(ref.InvalidCapture):
        review.check_resolver(events)


@pytest.mark.parametrize("event,field,value", [
    ("consumer_volume", "unit", 1), ("consumer_volume", "cloud_location", -1),
    ("consumer_volume", "filter_wrap", [0x2600]*5), ("consumer_volume", "dimensions", [64]*3),
    ("consumer_volume", "time_resolution_bits", [0, 0, 0]), ("consumer_volume", "seq", 0),
    ("consumer_attachment", "texture", 99), ("consumer_attachment", "read_type", 0x1401),
    ("consumer_draw_complete", "attachments", 2), ("consumer_restoration", "after_sha256", "0"*64),
])
def test_consumer_semantic_faults(saved, event, field, value):
    events = changed_event(saved[2], event, field, value, n=5760)
    with pytest.raises(ref.InvalidCapture):
        review.check_consumers(events, saved[1])


@pytest.mark.parametrize("event,field,value", [("node_coverage", "first_swap_before", 1), ("node_rng", "native_pc", 0),
                                               ("node_summary", "pending", 1)])
def test_node_attribution_faults(saved, event, field, value):
    events = changed_event(saved[2], event, field, value)
    with pytest.raises(ref.InvalidCapture):
        review.check_nodes(events, saved[1], saved[4])


@pytest.mark.parametrize("fault", ["seed", "outer", "advance", "probe-fp"])
def test_node_bytes_with_refreshed_digest(saved, tmp_path, fault):
    # Link immutable inputs read-only; replace only the disposable mutated file.
    for p in saved[1].glob("*.bin"):
        (tmp_path/p.name).symlink_to(p)
    events = list(saved[2])
    kind = 0 if fault in ("seed", "probe-fp") else 2
    event = "node_probe_restoration" if fault == "probe-fp" else "node_rng"
    i = next(i for i, e in enumerate(events) if e["event"] == event and e["kind"] == kind)
    e = deepcopy(events[i]); events[i] = e
    path = tmp_path/e["file"]
    raw = bytearray(path.read_bytes())
    path.unlink()
    relative = 584+24 if fault == "probe-fp" else 16 if fault == "outer" else 32
    raw[e["offset"]+relative] ^= 1
    path.write_bytes(raw)
    size = 1096 if fault == "probe-fp" else 48
    e["sha256"] = review.sha(raw[e["offset"]:e["offset"]+size])
    with pytest.raises(ref.InvalidCapture):
        review.check_nodes(events, tmp_path, saved[4])


@pytest.mark.parametrize("fault", ["missing", "duplicate", "reorder", "clock-shift", "sample-shift"])
def test_consumer_frame_faults(saved, fault):
    index = deepcopy(saved[3])
    if fault == "missing":
        index.pop(5760)
    elif fault == "duplicate":
        index[5760] = deepcopy(index[5759])
    elif fault == "reorder":
        index[5759], index[5760] = index[5760], index[5759]
    else:
        index[0]["clock_tick" if fault == "clock-shift" else "audio_position"] += 1
    with pytest.raises(ref.InvalidCapture):
        review.short.check_frames(index, saved[2], saved[0]["video"], saved[1])


@pytest.mark.parametrize("fault", ["alpha", "truncated", "trailing", "concatenated"])
def test_consumer_raw_faults(saved, tmp_path, fault):
    row = saved[3][5760]
    packed = (saved[1]/row["raw_zst"]).read_bytes()
    if fault == "alpha":
        pixels = bytearray(zstandard.ZstdDecompressor().decompress(packed))
        pixels[3] ^= 1
        packed = zstandard.ZstdCompressor().compress(pixels)
    elif fault == "truncated":
        packed = packed[:-1]
    elif fault == "trailing":
        packed += b"extra"
    else:
        packed += packed
    path = tmp_path/"changed.raw.zst"; path.write_bytes(packed)
    with pytest.raises(ref.InvalidCapture):
        ref.verify_raw(path, 8294400, row["sha256"])
    if fault == "alpha":
        raw = tmp_path/"changed.rgba"; raw.write_bytes(pixels)
        ref.verify_raw(path, 8294400, ref.hash_file(raw))
        assert ref.first_byte_difference(saved[1]/"frame-05760.rgba", raw) == 3


@pytest.mark.parametrize("fault", ["pcm-first", "pcm-tail", "pcm-shift", "trim-tail", "volume", "attachment"])
def test_exact_bytes_with_refreshed_hashes(saved, tmp_path, fault):
    name = "consumer-05760-volume.rgba32f" if fault == "volume" else "consumer-05760-attachment-0.rgba32f" if fault == "attachment" else "pcm.f32le"
    source = saved[1]/name
    path = tmp_path/"changed.bin"
    if fault == "pcm-shift":
        with source.open("rb") as src, path.open("wb") as dst:
            first = src.read(8); shutil.copyfileobj(src, dst); dst.write(first)
    else:
        shutil.copyfile(source, path)
        with path.open("r+b") as out:
            if fault == "trim-tail":
                out.truncate(19845000*8)
            else:
                offset = source.stat().st_size-1 if fault == "pcm-tail" else 0
                out.seek(offset); value = out.read(1); out.seek(offset); out.write(bytes([value[0] ^ 1]))
    if fault == "trim-tail":
        with pytest.raises(ref.InvalidCapture):
            ref.verify_pcm_file(path, 159716352, ref.hash_file(path))
    elif fault.startswith("pcm"):
        ref.verify_pcm_file(path, 159716352, ref.hash_file(path))
    assert ref.first_byte_difference(source, path) is not None
    path.unlink()


@pytest.mark.parametrize("field,value", [("final_tick", 19964544), ("final_cursor_offset", 159716344),
                                        ("stable_sha256", "0"*64)])
def test_completion_faults(saved, field, value, roots):
    proof = deepcopy(saved[0]["completion"]["pcm"]); proof[field] = value
    with pytest.raises(ref.InvalidCapture):
        ref.verify_pcm_completion(proof, saved[0]["audio"], 159716352, roots["checkout"]/"artifacts/reference", True)


@pytest.mark.parametrize("field,value", [("decision", "D9"), ("transformation", "450-explicit-output-0"),
                                        ("effective_shader_sha256", "0"*64)])
def test_restoration_identity_faults(saved, field, value):
    from tools.verify import restoration
    source = deepcopy(saved[0]["source"]); source["restoration"][field] = value
    with pytest.raises(ref.InvalidCapture):
        restoration.check_identity(source)


def test_partial_cannot_be_full(saved, roots):
    path = roots["checkout"]/"artifacts/reference"/f"{saved[0]['run_id']}-partial-reference.json"
    with pytest.raises(ref.InvalidCapture, match="schema"):
        ref.load_run(path, saved[1], roots)
