"""Fault injection against complete synthetic files; never runs Wine or a demo."""

import json
from pathlib import Path
import subprocess
import sys

import pytest
import zstandard

from reference_factory import make_capture, sha
from tools.verify.reference import load_run, main


@pytest.fixture
def pair(tmp_path):
    return (make_capture(tmp_path / "reference", "reference"),
            make_capture(tmp_path / "repeat", "repeat", storage="hashes"))


def check(pair, capsys, expected=None):
    code = main(["compare", str(pair[0].path), str(pair[1].path)])
    result = json.loads(capsys.readouterr().out)
    assert code == (1 if expected else 0), result
    assert result["status"] == ("FAIL" if expected else "PASS"), result
    assert result["draft"] is True
    if expected:
        assert expected in "\n".join(result["reasons"]), result
    else:
        assert result["source_kinds"] == ["synthetic"]
        assert result["reasons"] == []
    return result


def test_exact_synthetic_pair_and_fractional_phase(pair, capsys):
    run = load_run(pair[0].path)
    assert run.frames[1]["audio_position"] == 367
    assert run.frames[1]["audio_position_num"] / run.frames[1]["audio_position_den"] == 367.5
    assert {r["n"] for r in run.frames if "raw_zst" in r} == {0, 7, 8, 42, 43, 60, 64}
    check(pair, capsys)


def test_valid_authoritative_timeline_end(pair, capsys):
    for capture in pair:
        capture.manifest["termination"].update(
            reason="timeline_end", timeline_end_tick=65, exit_code=None,
            evidence="synthetic independent endpoint")
        capture.save()
    check(pair, capsys)


@pytest.mark.parametrize("key,value,reason", [
    ("n", 2, "frame 1 n"),
    ("tick", 2, "frame 1 tick"),
    ("clock_tick", 2, "frame 1 clock_tick"),
    ("audio_position", 368, "frame 1 audio_position"),
    ("audio_position_num", 22051, "frame 1 audio_position_num"),
    ("audio_position_den", 59, "frame 1 audio_position_den"),
    ("tick", True, "expected integer"),
    ("tick", 1.0, "expected integer"),
    ("sha256", "not-a-hash", "expected lowercase SHA-256"),
])
def test_frame_metadata_faults(pair, capsys, key, value, reason):
    pair[1].records[1][key] = value
    pair[1].save()  # Refreshing index hash must not hide timeline corruption.
    check(pair, capsys, reason)


@pytest.mark.parametrize("fault,reason", [
    ("missing-middle", "frame 8 n"),
    ("missing-last", "missing frame records"),
    ("duplicate", "frame 9 n"),
    ("reorder", "frame 8 n"),
    ("extra", "extra records"),
])
def test_missing_duplicated_reordered_extra_records(pair, capsys, fault, reason):
    records = pair[1].records
    if fault == "missing-middle":
        del records[8]
    elif fault == "missing-last":
        records.pop()
    elif fault == "duplicate":
        records.insert(9, records[8].copy())
    elif fault == "reorder":
        records[8], records[9] = records[9], records[8]
    else:
        records.append(records[-1].copy())
    pair[1].save()
    check(pair, capsys, reason)


@pytest.mark.parametrize("fault", ["changed", "duplicated", "shifted"])
def test_well_formed_but_wrong_frame_content(pair, capsys, fault):
    records = pair[1].records
    if fault == "changed":
        records[4]["sha256"] = "f" * 64
    elif fault == "duplicated":
        records[4]["sha256"] = records[3]["sha256"]
    else:
        hashes = [record["sha256"] for record in records]
        for record, checksum in zip(records, hashes[1:] + hashes[:1]):
            record["sha256"] = checksum
    pair[1].save()
    load_run(pair[1].path)  # Internally consistent; equality must still fail.
    check(pair, capsys, "frame content mismatch")


@pytest.mark.parametrize("n", [0, 7, 8, 60, 64])
def test_missing_sparse_selection(pair, capsys, n):
    del pair[0].records[n]["raw_zst"]
    pair[0].save()
    check(pair, capsys, "missing required raw frames")


@pytest.mark.parametrize("fault,reason", [
    ("missing", "missing payload"),
    ("changed-pixels", "raw frame SHA-256 mismatch"),
    ("wrong-length", "raw frame size"),
    ("truncated-zstd", "truncated Zstandard"),
    ("trailing-bytes", "trailing compressed data"),
    ("concatenated-zstd", "trailing compressed data"),
])
def test_sparse_raw_integrity(pair, capsys, fault, reason):
    path = pair[0].root / pair[0].records[0]["raw_zst"]
    packed = path.read_bytes()
    compressor = zstandard.ZstdCompressor(write_checksum=True)
    if fault == "missing":
        path.unlink()
    elif fault == "changed-pixels":
        raw = bytearray(zstandard.ZstdDecompressor().decompress(packed))
        raw[3] ^= 1  # Alpha is significant too.
        path.write_bytes(compressor.compress(raw))
    elif fault == "wrong-length":
        path.write_bytes(compressor.compress(b"wrong size"))
    elif fault == "truncated-zstd":
        path.write_bytes(packed[:-1])  # Missing footer after all pixels decoded.
    elif fault == "trailing-bytes":
        path.write_bytes(packed + b"junk")
    else:
        path.write_bytes(packed + compressor.compress(b""))
    check(pair, capsys, reason)


@pytest.mark.parametrize("fault,reason", [
    ("bit-flip", "PCM SHA-256 mismatch"),
    ("truncate", "PCM byte length"),
    ("append", "PCM byte length"),
    ("missing", "missing payload"),
])
def test_pcm_integrity(pair, capsys, fault, reason):
    path = pair[1].pcm
    data = bytearray(path.read_bytes())
    if fault == "missing":
        path.unlink()
    else:
        if fault == "bit-flip":
            data[-1] ^= 1
        elif fault == "truncate":
            del data[-4:]
        else:
            data += b"\0\0\0\0"
        path.write_bytes(data)
    check(pair, capsys, reason)


@pytest.mark.parametrize("fault", ["bit-flip", "one-sample-shift", "channel-swap", "generated-tail"])
def test_pcm_changes_even_with_updated_hash(pair, capsys, fault):
    data = bytearray(pair[1].pcm.read_bytes())
    if fault == "bit-flip":
        data[11] ^= 1
    elif fault == "one-sample-shift":
        data = data[4:] + b"\0\0\0\0"
    elif fault == "channel-swap":
        for n in range(0, len(data), 4):
            data[n:n + 4] = data[n + 2:n + 4] + data[n:n + 2]
    else:
        data[-1] ^= 1
    pair[1].update_pcm(data)
    load_run(pair[1].path)
    check(pair, capsys, "PCM byte mismatch")


def test_pcm_comparison_reads_beyond_first_chunk(pair, capsys):
    for capture in pair:
        data = capture.pcm.read_bytes() + bytes(range(256)) * 8192
        capture.manifest["audio"]["sample_frames"] = len(data) // 4
        capture.manifest["completion"]["audio_sample_frames"] = len(data) // 4
        capture.update_pcm(data)
    data = bytearray(pair[1].pcm.read_bytes())
    data[1048577] ^= 1
    pair[1].update_pcm(data)
    check(pair, capsys, "PCM byte mismatch at offset 1048577")


@pytest.mark.parametrize("key,value,reason", [
    ("reason", "timeout", "not a successful end"),
    ("reason", "crash", "not a successful end"),
    ("reason", "manual_abort", "not a successful end"),
    ("end_tick", 64, "end_tick must equal frame_count"),
    ("audio_position", 23888, "audio position is shifted"),
    ("audio_position_num", 1433251, "rational audio position is shifted"),
    ("exit_code", 1, "exit_code=0"),
    ("timeline_end_tick", 65, "no timeline cutoff"),
    ("evidence", "", "termination evidence"),
])
def test_invalid_termination(pair, capsys, key, value, reason):
    pair[1].manifest["termination"][key] = value
    pair[1].save()
    check(pair, capsys, reason)


@pytest.mark.parametrize("key,value", [
    ("finalized", False), ("frames_observed", 64), ("frames_hashed", 64),
    ("audio_sample_frames", 1), ("dropped_frames", 1), ("dropped_audio_sample_frames", 1),
    ("errors", ["readback failed"]),
])
def test_completion_and_loss_checks(pair, capsys, key, value):
    pair[1].manifest["completion"][key] = value
    pair[1].save()
    check(pair, capsys, "candidate:")


def test_both_runs_share_same_bad_clock_still_fail(pair, capsys):
    for capture in pair:
        capture.manifest["conditions"]["clock"]["denominator"] = 59
        capture.save()
    result = check(pair, capsys, "clock must use exact 1/60 s ticks")
    assert len(result["reasons"]) == 2


def test_consistently_shortened_repeat_fails_comparison(pair, capsys):
    capture = pair[1]
    capture.records.pop()
    capture.manifest["video"]["frame_count"] = 64
    capture.manifest["scenes"][-1]["last"] = 63
    capture.manifest["termination"].update(end_tick=64, audio_position=23520,
                                           audio_position_num=1411200)
    capture.manifest["completion"].update(frames_observed=64, frames_hashed=64)
    capture.save()
    load_run(capture.path)
    check(pair, capsys, "termination mismatch")


@pytest.mark.parametrize("field,value,reason", [
    ("row_order", "top-down", "video layout/count mismatch"),
    ("pixel_format", "bgra8", "video layout/count mismatch"),
    ("row_stride", 16, "row stride must be width * 4"),
    ("frame_count", 0, "frame_count: expected integer"),
])
def test_video_layout(pair, capsys, field, value, reason):
    pair[1].manifest["video"][field] = value
    pair[1].save()
    check(pair, capsys, reason)


@pytest.mark.parametrize("fault,reason", [
    ("driver", "conditions mismatch"), ("rng", "conditions mismatch"),
    ("state", "conditions mismatch"), ("tool", "capture tool SHA-256 mismatch"),
    ("input", "source mismatch"), ("settings-type", "conditions mismatch"),
    ("channel-order", "audio layout/count mismatch"),
    ("smoke", "capture kind"), ("wrong-exe", "not approved native EXE"),
    ("scene-gap", "scene partition has a gap"),
    ("scene-tail", "scene partition does not cover all frames"),
])
def test_identity_and_completeness_metadata(pair, capsys, fault, reason):
    m = pair[1].manifest
    if fault == "driver":
        m["conditions"]["environment"]["driver"] = "other driver"
    elif fault == "rng":
        m["conditions"]["rng"]["initial_state_sha256"] = "f" * 64
    elif fault == "state":
        m["conditions"]["initial_state_sha256"] = "f" * 64
    elif fault == "tool":
        m["capture"]["tool_sha256"] = "f" * 64
    elif fault == "input":
        m["source"]["inputs"]["fixture-seed"] = "f" * 64
    elif fault == "settings-type":
        m["conditions"]["settings"]["fixture_version"] = True
    elif fault == "channel-order":
        m["audio"]["channels"] = ["R", "L"]
    elif fault == "smoke":
        m["capture"]["kind"] = "compatibility-smoke"
    elif fault == "wrong-exe":
        m["source"]["kind"] = "original"
    elif fault == "scene-gap":
        m["scenes"][1]["first"] += 1
    else:
        m["scenes"][-1]["last"] -= 1
    pair[1].save()
    check(pair, capsys, reason)


def test_pcm_must_cover_terminal_cursor(pair, capsys):
    capture = pair[1]
    capture.manifest["audio"]["sample_frames"] = 23886
    capture.manifest["completion"]["audio_sample_frames"] = 23886
    capture.update_pcm(capture.pcm.read_bytes()[:23886 * 4])
    check(pair, capsys, "PCM does not cover the controlled timeline")


def test_unchanged_index_hash_catches_edit(pair, capsys):
    path = pair[1].root / "frames.jsonl"
    path.write_bytes(path.read_bytes().replace(b'"n": 0', b'"n":  0'))
    check(pair, capsys, "frame index SHA-256 mismatch")


@pytest.mark.parametrize("json_text,reason", [
    ('{"schema": 1, "schema": 2}', "duplicate JSON key"),
    ('{"value": NaN}', "non-finite JSON number"),
    ('{"value": 1e999}', "non-finite JSON number"),
    ('{"schema":', "Expecting value"),
    ('{}', "invalid fields"),
])
def test_malformed_json_is_fail_not_pass(pair, capsys, json_text, reason):
    pair[1].path.write_text(json_text)
    check(pair, capsys, reason)


@pytest.mark.parametrize("relative", ["../audio.pcm", "/audio.pcm", "a\\audio.pcm"])
def test_payload_path_must_stay_in_root(pair, capsys, relative):
    pair[1].manifest["audio"]["path"] = relative
    pair[1].save()
    check(pair, capsys, "payload path must be root-relative")


def test_symlink_escape_rejected(pair, capsys):
    capture = pair[1]
    (capture.root / "external.pcm").symlink_to(pair[0].pcm)
    capture.manifest["audio"]["path"] = "external.pcm"
    capture.save()
    check(pair, capsys, "payload path escapes root")


def test_same_run_cannot_prove_repeatability(pair, capsys):
    check((pair[0], pair[0]), capsys, "distinct run IDs and manifests")


def test_left_requires_reference_pixels(pair, capsys):
    check((pair[1], pair[0]), capsys, "left run must contain")


def test_external_data_roots_and_cli_exit_codes(pair, tmp_path):
    manifests = []
    for n, capture in enumerate(pair):
        metadata = tmp_path / f"metadata-{n}"
        metadata.mkdir()
        manifest = metadata / "manifest.json"
        manifest.write_bytes(capture.path.read_bytes())
        (metadata / "frames.jsonl").write_bytes((capture.root / "frames.jsonl").read_bytes())
        manifests.append(manifest)
    script = Path(__file__).resolve().parents[1] / "tools/verify/reference.py"
    args = [sys.executable, str(script), "compare", *map(str, manifests),
            "--reference-data", str(pair[0].root), "--candidate-data", str(pair[1].root)]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "PASS"
    assert not result.stderr
    pair[1].pcm.write_bytes(b"broken")
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert json.loads(result.stdout)["status"] == "FAIL"
    assert not result.stderr
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 2


def test_validate_command(pair, capsys):
    assert main(["validate", str(pair[0].path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "PASS"
    assert result["operation"] == "validate"
