"""New repeat2 exact-pair and original-launch faults; reuse prior reference review."""
from copy import deepcopy
from dataclasses import replace
import os
from pathlib import Path
import shutil

import pytest

from tools.verify import review_full as full

ref = full.ref
REPEAT = "proxy-b-d13-detached-20261016-2"


@pytest.fixture(scope="module")
def pair():
    shared = Path(os.environ["EIDOLON_ROOT"])
    roots = {"checkout": Path(os.environ.get("EIDOLON_CLOSED_CAPTURE_ROOT", str(shared/".worktrees/T16"))),
             "shared": shared, "data": Path(os.environ["EIDOLON_DATA"])}
    a, reused = full.reuse_reference(roots)
    path = full.checked(roots["checkout"]/f"artifacts/reference/{REPEAT}-reference.json", full.PINS[REPEAT]["reference"])
    b = ref.load_run(path, roots["data"]/"reference"/REPEAT, roots)
    return a, b, roots, reused


def test_real_pair_exact_and_distinct(pair):
    a, b, roots, reused = pair
    result = full.check_pair(a, b, roots)
    assert result["status"] == "EXACT_PAIR_PASS" and result["frame_hashes_equal"] == 27000
    assert result["pcm_bytes_equal"] == 159716352 and result["tail_bytes_equal"] == 956352
    assert result["original_preflight_behavior_equal"] and result["separate_sequential_invocations"]
    assert reused["review_reused_from_commit"] == "14c82b1" and reused["evidence_bindings_rehashed"] == 1380
    assert b.manifest["video"]["storage"] == "hashes" and not any("raw_zst" in r for r in b.frames)
    assert "proxy-b-d13-detached-20261016-3" not in full.PINS


@pytest.mark.parametrize("n,field,value", [(1,"sha256","0"*64),(13365,"sha256","f"*64),
    (26999,"sha256","0"*64),(13365,"clock_tick",13366),(26999,"audio_position_num",0)])
def test_real_pair_frame_or_time_changes(pair, n, field, value):
    a, b, roots, _ = pair
    frames = list(b.frames); frames[n] = dict(frames[n], **{field:value})
    with pytest.raises(ref.InvalidCapture, match="frame content mismatch"):
        full.check_pair(a, replace(b, frames=frames), roots)


@pytest.mark.parametrize("fault", ["first", "tail", "one-sample-shift"])
def test_repeat_pcm_with_refreshed_hash(pair, tmp_path, fault):
    a, b, roots, _ = pair
    path = tmp_path/"changed.f32le"
    if fault == "one-sample-shift":
        with b.audio_path.open("rb") as src, path.open("wb") as dst:
            first = src.read(8); shutil.copyfileobj(src, dst); dst.write(first)
    else:
        shutil.copyfile(b.audio_path, path)
        with path.open("r+b") as out:
            offset = 0 if fault == "first" else 159716351
            out.seek(offset); value = out.read(1); out.seek(offset); out.write(bytes([value[0]^1]))
    manifest = deepcopy(b.manifest)
    manifest["audio"]["sha256"] = manifest["completion"]["pcm"]["stable_sha256"] = ref.hash_file(path)
    ref.verify_pcm_file(path, 159716352, manifest["audio"]["sha256"])
    with pytest.raises(ref.InvalidCapture, match="PCM byte mismatch"):
        full.check_pair(a, replace(b, manifest=manifest, audio_path=path), roots)


@pytest.mark.parametrize("field", ["build", "arguments", "environment", "hidden-setting"])
def test_original_launch_mismatch(pair, field):
    a, b, roots, _ = pair
    first, second = [full.load(roots["data"]/"reference"/r.manifest["run_id"]/"preflight.json") for r in (a,b)]
    if field == "build": second["build"]["build_id"] = "0"*64
    elif field == "arguments": second["arguments"]["fault"] = "exception-fp"
    elif field == "environment": second["environment"]["settings"]["WINEDEBUG"] = "+all"
    else: second["environment"]["settings"]["UNREVIEWED_BEHAVIOR"] = "1"
    with pytest.raises(ref.InvalidCapture, match="original"):
        full.check_preflight_pair(first, second)


def test_reuse_rejects_changed_reference_pin(tmp_path):
    artifacts = tmp_path/"artifacts/reference"; artifacts.mkdir(parents=True)
    (artifacts/f"{full.REFERENCE_ID}-reference.json").write_text("{}\n")
    with pytest.raises(ref.InvalidCapture, match="hash mismatch"):
        full.reuse_reference({"checkout":tmp_path,"data":tmp_path,"shared":tmp_path})


def test_hash_only_run_rejects_raw_pointer(pair):
    a, b, _, _ = pair
    frames = list(b.frames); frames[0] = dict(frames[0], raw_zst=a.frames[0]["raw_zst"])
    with pytest.raises(ref.InvalidCapture, match="retention"):
        full.check_retention(b.manifest, frames, b.audio_path.parent)
