"""Real T11 evidence and disposable frame faults; no target/GPU execution."""

from copy import deepcopy
import os
from pathlib import Path
import shutil

import pytest
import zstandard

from tools.verify import compatibility as compat, reference as ref, review_short as review


@pytest.fixture(scope="module")
def roots():
    checkout = Path(__file__).resolve().parents[1]
    return {"checkout": Path(os.environ.get("EIDOLON_CAPTURE_ROOT", checkout)).resolve(),
            "shared": Path(os.environ["EIDOLON_ROOT"]), "data": Path(os.environ["EIDOLON_DATA"])}


def test_real_review_preserves_partial_and_failed_verdicts(roots):
    result = review.assess(roots)
    assert result["status"] == "DIAGNOSTIC_ONLY" and result["reference_accepted"] is False
    assert result["g5"] == "partial" and result["g6"] == "open"
    control, primary, repeat, boundary = result["runs"]
    assert control["producer_status"] == boundary["producer_status"] == "failed"
    assert primary["provenance"] == repeat["provenance"] == "PROVENANCE_ONLY"
    assert primary["frames"] == repeat["frames"] == 3
    assert boundary["frames"] == 67 and boundary["actual_stop"]["native_exit_observed"] is False
    assert len(result["pair_files_byte_equal"]) == 5


def test_original_initializer_has_distinct_roles_at_shared_callsite(roots):
    image = (roots["data"] / "reverse/confirmed-debug/postfix-00400000.bin").read_bytes()
    roles = review.original_roles(image)
    assert roles[0] == (0x406442, [0x426c58])
    assert roles[1] == (0x406dce, [0x409918])
    assert roles[2] == (0x406dce, [0x409e38])  # Another single-string call is not D7.
    assert roles[3][0] == 0x406dce and len(roles[3][1]) == 5
    assert sum(a == 0x409918 for _, addresses in roles for a in addresses) == 1
    changed = bytearray(image)
    changed[0x6e01] ^= 1
    with pytest.raises(ref.InvalidCapture, match="original image changed"):
        review.original_roles(changed)


@pytest.mark.parametrize("fault", ["sibling-edit", "sibling-reorder", "missing-target", "duplicate-target"])
def test_real_ledger_rejects_scope_changes(roots, fault):
    sidecar = review.load(roots["checkout"] / "artifacts/reference/proxy-b-d9-primary-20261016-eligibility.json")
    calls = deepcopy(sidecar["calls"])
    if fault == "sibling-edit":
        calls[2]["forwarded"] = calls[1]["forwarded"]
    elif fault == "sibling-reorder":
        calls[3]["forwarded"].reverse()
    elif fault == "missing-target":
        calls.pop(1)
        for sequence, call in enumerate(calls, 1):
            call["sequence"] = sequence
    else:
        duplicate = deepcopy(calls[1])
        duplicate["sequence"] = len(calls) + 1
        calls.append(duplicate)
    with pytest.raises(ref.InvalidCapture):
        compat.verify_calls(calls, sidecar["transformation"], roots)


@pytest.fixture
def frames(roots):
    run = "proxy-b-d9-primary-20261016"
    artifacts = roots["checkout"] / "artifacts/reference"
    bundle = review.load(artifacts / f"{run}-small-capture.json")
    directory = roots["data"] / "reference" / run
    index = [ref.load_json(line) for line in (artifacts / bundle["video"]["index"]).read_text().splitlines()]
    events = [ref.load_json(line) for line in (directory / "backend.jsonl").read_text().splitlines()]
    return index, events, bundle["video"], directory


@pytest.mark.parametrize("fault", ["missing", "duplicate", "reorder", "time-shift", "audio-shift", "missing-raw"])
def test_real_frame_records_detect_missing_and_shifted_data(frames, fault):
    index, events, video, directory = frames
    if fault == "missing":
        index.pop()
    elif fault == "duplicate":
        index[1] = deepcopy(index[0])
    elif fault == "reorder":
        index.reverse()
    elif fault == "time-shift":
        index[0]["clock_tick"] += 1
    elif fault == "audio-shift":
        index[0]["audio_position"] += 735
    else:
        index[0]["raw_zst"] = "absent-frame.raw.zst"
    with pytest.raises(ref.InvalidCapture):
        review.check_frames(index, events, video, directory)


@pytest.mark.parametrize("fault", ["alpha-bit", "truncated", "trailing", "concatenated"])
def test_real_pixel_payload_corruption_is_rejected(frames, tmp_path, fault):
    index, _, _, directory = frames
    row = index[0]
    packed = (directory / row["raw_zst"]).read_bytes()
    if fault == "alpha-bit":
        pixels = bytearray(zstandard.ZstdDecompressor().decompress(packed))
        pixels[3] ^= 1
        packed = zstandard.ZstdCompressor().compress(pixels)
    elif fault == "truncated":
        packed = packed[:-1]
    elif fault == "trailing":
        packed += b"trailing"
    else:
        packed += packed
    changed = tmp_path / "changed.raw.zst"
    changed.write_bytes(packed)
    with pytest.raises(ref.InvalidCapture):
        ref.verify_raw(changed, 1920*1080*4, row["sha256"])


@pytest.mark.parametrize("fault", ["first-byte", "retained-tail-byte", "sample-shift"])
def test_t11_pcm_changes_fail_even_after_refreshing_hash(roots, tmp_path, fault):
    pcm = roots["data"] / "reference/proxy-b-d9-primary-20261016/pcm.f32le"
    changed = tmp_path / "changed.pcm"
    try:
        if fault == "sample-shift":
            with pcm.open("rb") as source, changed.open("wb") as target:
                first = source.read(8)
                shutil.copyfileobj(source, target)
                target.write(first)
        else:
            shutil.copyfile(pcm, changed)
            offset = 0 if fault == "first-byte" else review.PCM_BYTES - 1
            with changed.open("r+b") as stream:
                stream.seek(offset)
                byte = stream.read(1)
                stream.seek(offset)
                stream.write(bytes([byte[0] ^ 1]))
        with pytest.raises(ref.InvalidCapture, match="PCM SHA-256 mismatch"):
            ref.verify_pcm_file(changed, review.PCM_BYTES, ref.hash_file(pcm))
        ref.verify_pcm_file(changed, review.PCM_BYTES, ref.hash_file(changed))
        difference = ref.first_byte_difference(pcm, changed)
        assert difference is not None
        if fault != "sample-shift":
            assert difference == offset
    finally:
        changed.unlink(missing_ok=True)
