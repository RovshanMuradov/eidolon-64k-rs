"""Closed T16 reference faults on copies; no active acquisition or target access."""
import os
from pathlib import Path
import shutil

import pytest
import zstandard

from tools.verify import review_full as full

ref = full.ref


@pytest.fixture(scope="module")
def saved():
    shared = Path(os.environ["EIDOLON_ROOT"])
    checkout = Path(os.environ.get("EIDOLON_CLOSED_CAPTURE_ROOT", str(shared/".worktrees/T16")))
    roots = {"checkout": checkout, "shared": shared, "data": Path(os.environ["EIDOLON_DATA"])}
    run_id = next(iter(full.PINS))
    artifacts = checkout/"artifacts/reference"
    bundle = full.load(full.checked(artifacts/f"{run_id}-reference.json", full.PINS[run_id]["reference"]))
    sidecar = full.load(full.compat.bound_file(bundle["provenance"]["eligibility"], roots))
    producer = full.load(full.compat.bound_file(sidecar["run_manifest"], roots))
    directory = roots["data"]/"reference"/run_id
    events, _ = full.stream(directory/producer["ordered_stream"]["path"], producer["ordered_stream"])
    # Keep complete frame/query accounting plus endpoint witnesses, not lookup bulk.
    names = {"pre_present", "post_present", "native_endpoint", "native_exit_forward", "full_run", "compat_context", "abi_canary"}
    selected = [e for e in events if e["event"] in names or e["event"] == "clock" and e["api"] == "waveOutGetPosition"]
    index = [ref.load_json(line) for line in (artifacts/bundle["video"]["index"]).read_text().splitlines()]
    image = full.compat.bound_file(bundle["provenance"]["native_image"], roots).read_bytes()
    return bundle, producer, directory, selected, index, image, roots


def test_real_endpoint(saved):
    full.check_endpoint(saved[3], saved[2], saved[5])


@pytest.mark.parametrize("field,value", [("frames",26999),("queries",27000),("last_present",26998),
    ("terminal_query",26999),("sample_cursor",19844999),("exit_call",0x408617),("exit_code",1),
    ("eax",0),("edi",1),("seconds_f32_bits",0),("beat_f32_bits",0),("dropped_frames",1),("seq",1)])
def test_false_endpoint(saved, field, value):
    events = [dict(e) if e["event"] == "native_endpoint" else e for e in saved[3]]
    next(e for e in events if e["event"] == "native_endpoint")[field] = value
    with pytest.raises(ref.InvalidCapture):
        full.check_endpoint(events, saved[2], saved[5])


@pytest.mark.parametrize("event", ["native_endpoint", "native_exit_forward", "post_present"])
def test_missing_end_evidence(saved, event):
    events = list(saved[3])
    i = max(i for i,e in enumerate(events) if e["event"] == event)
    events.pop(i)
    with pytest.raises(ref.InvalidCapture):
        full.check_endpoint(events, saved[2], saved[5])


@pytest.mark.parametrize("file,offset", [("after-gpr",28),("after-fx",24),("after-fx",160),("locals",4)])
def test_raw_endpoint_corruption(saved, tmp_path, file, offset):
    for p in saved[2].glob("native-exit-*.bin"):
        shutil.copyfile(p, tmp_path/p.name)
    path = tmp_path/f"native-exit-{file}.bin"
    raw = bytearray(path.read_bytes()); raw[offset] ^= 1; path.write_bytes(raw)
    with pytest.raises(ref.InvalidCapture):
        full.check_endpoint(saved[3], tmp_path, saved[5])


@pytest.mark.parametrize("fault", ["missing", "duplicate", "reorder", "time", "sample", "hash"])
def test_full_frame_completeness(saved, fault):
    index = list(saved[4])
    index[0] = dict(index[0])
    if fault == "missing":
        index.pop()
    elif fault == "duplicate":
        index[0] = index[1]
    elif fault == "reorder":
        index[0], index[1] = index[1], index[0]
    else:
        key = {"time":"clock_tick", "sample":"audio_position", "hash":"sha256"}[fault]
        index[0][key] = "0"*64 if fault == "hash" else index[0][key]+1
    with pytest.raises(ref.InvalidCapture):
        full.short.check_frames(index, saved[3], saved[0]["video"], saved[2], inspect_pixels=False)


@pytest.mark.parametrize("fault", ["alpha", "truncated", "trailing", "concatenated"])
def test_final_raw_corruption(saved, tmp_path, fault):
    row = saved[4][-1]
    packed = (saved[2]/row["raw_zst"]).read_bytes()
    if fault == "alpha":
        raw = bytearray(zstandard.ZstdDecompressor().decompress(packed)); raw[3] ^= 1
        packed = zstandard.ZstdCompressor().compress(raw)
    elif fault == "truncated":
        packed = packed[:-1]
    elif fault == "trailing":
        packed += b"x"
    else:
        packed += packed
    path = tmp_path/"frame.raw.zst"; path.write_bytes(packed)
    with pytest.raises(ref.InvalidCapture):
        ref.verify_raw(path, 8294400, row["sha256"])
    if fault == "alpha":
        changed = tmp_path/"changed.rgba"; changed.write_bytes(raw)
        ref.verify_raw(path, 8294400, ref.hash_file(changed))
        assert ref.first_byte_difference(saved[2]/"frame-26999.rgba", changed) == 3


@pytest.mark.parametrize("fault", ["first", "tail", "shift", "trim-tail", "extra", "missing"])
def test_full_pcm_faults(saved, tmp_path, fault):
    source, path = saved[2]/"pcm.f32le", tmp_path/"pcm.bin"
    if fault == "missing":
        with pytest.raises((OSError, ref.InvalidCapture)):
            ref.verify_pcm_file(path, 159716352, saved[0]["audio"]["sha256"])
        return
    if fault == "shift":
        with source.open("rb") as src, path.open("wb") as dst:
            first = src.read(8); shutil.copyfileobj(src, dst); dst.write(first)
    else:
        shutil.copyfile(source, path)
        with path.open("r+b") as out:
            if fault in ("trim-tail", "extra"):
                out.truncate(19845000*8 if fault == "trim-tail" else 159716360)
            else:
                offset = 159716351 if fault == "tail" else 0
                out.seek(offset); value = out.read(1); out.seek(offset); out.write(bytes([value[0]^1]))
    with pytest.raises(ref.InvalidCapture):
        ref.verify_pcm_file(path, 159716352, saved[0]["audio"]["sha256"])
    if fault not in ("trim-tail", "extra"):
        ref.verify_pcm_file(path, 159716352, ref.hash_file(path))
    assert ref.first_byte_difference(source, path) is not None


@pytest.mark.parametrize("fault", ["truncate", "append", "concatenate", "no-newline"])
def test_lossless_stream_completeness(tmp_path, fault):
    line = b'{"event":"clock","pid":244,"seq":1}\n'
    packed = zstandard.ZstdCompressor().compress(line[:-1] if fault == "no-newline" else line)
    packed = packed[:-1] if fault == "truncate" else packed+b"x" if fault == "append" else packed+packed if fault == "concatenate" else packed
    path = tmp_path/"stream.zst"; path.write_bytes(packed)
    with pytest.raises((ref.InvalidCapture,zstandard.ZstdError)):
        list(full.decoded_lines(path))


@pytest.mark.parametrize("fault", ["gap", "duplicate", "pid", "unsequenced", "partial"])
def test_stream_order_faults(fault):
    event = dict(event="clock", pid=244, seq=2)
    if fault == "gap": event["seq"] = 3
    elif fault == "duplicate": event["seq"] = 1
    elif fault == "pid": event["pid"] = 248
    elif fault == "unsequenced": del event["seq"]
    else: event["event"] = "planned_partial_stop"
    with pytest.raises(ref.InvalidCapture): full.check_sequence(event, 1, 244)


@pytest.mark.parametrize("fault", ["launch", "return", "prefix", "identity", "state", "timeout"])
def test_durable_original_provenance(saved, fault):
    directory = saved[2]; job = directory.parent/"jobs"/saved[0]["run_id"]
    pre, returned = [full.load(directory/f"{k}.json") for k in ("preflight", "native-return")]
    state, request = [full.load(job/f"{k}.json") for k in ("state", "request")]
    if fault == "launch": pre["started_utc"] = returned["finished_utc"]
    elif fault == "return": returned["launcher_exit"] = 124
    elif fault == "prefix": pre["fresh_tree_equal"] = False
    elif fault == "identity": pre["exe_before_sha256"] = "0"*64
    elif fault == "state": state["phase"] = "acquiring"
    else: returned["supervisor_timeout"] = True
    with pytest.raises(ref.InvalidCapture):
        full.check_durable(pre, returned, state, request, saved[1], saved[0])


def test_no_repeat_inferred_from_reference(saved):
    # Copying the reference to another path does not create a distinct run.
    run = ref.Run(Path("reference.json"), saved[0], saved[4], saved[2]/"pcm.f32le")
    assert ref.compare_runs(run, run)


@pytest.mark.parametrize("n", [0, 60, 13365, 26999])
def test_missing_required_sample(saved, n):
    index = list(saved[4]); index[n] = dict(index[n]); del index[n]["raw_zst"]
    with pytest.raises(ref.InvalidCapture, match="retention"):
        full.check_retention(saved[0], index, saved[2])


def test_wrong_original_retention_input(saved, tmp_path):
    (tmp_path/"retention.txt").write_text("0\n")
    with pytest.raises(ref.InvalidCapture, match="original retention"):
        full.check_retention(saved[0], saved[4], tmp_path)
