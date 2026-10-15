"""Fault injection against complete synthetic files; never runs Wine or a demo."""

import hashlib
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
    assert result["schema"] == "eidolon-reference-draft-3"
    if expected:
        assert expected in "\n".join(result["reasons"]), result
    else:
        assert result["source_kinds"] == ["synthetic"]
        assert result["reasons"] == []
    return result


def test_exact_synthetic_pair_and_fractional_phase(pair, capsys):
    run = load_run(pair[0].path)
    display = run.manifest["conditions"]["environment"]["display"]
    assert (display["width"], display["height"]) == (1920, 1080)
    assert (run.manifest["video"]["width"], run.manifest["video"]["height"]) == (3, 2)
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
        capture.manifest["completion"]["pcm"].update(
            submitted_bytes=len(data), final_tick=len(data) // 4 + 1,
            final_cursor_offset=len(data))
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


@pytest.mark.parametrize("key,value,reason", [
    ("kind", "wine-virtual-desktop", "display.kind must be gamescope-headless"),
    ("kind", "gamescope-nested", "display.kind must be gamescope-headless"),
    ("width", 1280, "display must be 1920x1080"),
    ("height", 720, "display must be 1920x1080"),
    ("width", 1920.0, "display.width: expected integer"),
    ("height", 1080.0, "display.height: expected integer"),
    ("width", True, "display.width: expected integer"),
    ("launcher", "wine", "display.launcher must be tools/wine-headless"),
    ("wine_virtual_desktop", True, "Wine virtual desktop must be disabled"),
    ("wine_virtual_desktop", 0, "Wine virtual desktop must be disabled"),
])
def test_matching_unapproved_displays_fail_independently(pair, capsys, key, value, reason):
    for capture in pair:
        capture.manifest["conditions"]["environment"]["display"][key] = value
        capture.save()
    result = check(pair, capsys, reason)
    assert len(result["reasons"]) == 2


@pytest.mark.parametrize("field", ["gamescope", "display", "kind", "width", "height",
                                  "launcher", "wine_virtual_desktop"])
def test_display_metadata_cannot_be_omitted(pair, capsys, field):
    environment = pair[1].manifest["conditions"]["environment"]
    target = environment if field in ("gamescope", "display") else environment["display"]
    del target[field]
    pair[1].save()
    check(pair, capsys, "invalid fields")


@pytest.mark.parametrize("version", ["", "  ", None, 3])
def test_gamescope_version_must_be_recorded(pair, capsys, version):
    pair[1].manifest["conditions"]["environment"]["gamescope"] = version
    pair[1].save()
    check(pair, capsys, "environment.gamescope: expected nonempty text")


@pytest.mark.parametrize("schema,reason", [
    ("eidolon-reference-draft-1", "unsupported reference schema"),
    ("eidolon-reference-draft-2", "unsupported reference schema"),
    ("eidolon-reference-draft-3", "invalid fields"),
])
def test_legacy_desktop_manifest_requires_explicit_revision(pair, capsys, schema, reason):
    capture = pair[1]
    capture.manifest["schema"] = schema
    environment = capture.manifest["conditions"]["environment"]
    del environment["gamescope"], environment["display"]
    environment["desktop"] = [1920, 1080]
    capture.save()
    check(pair, capsys, reason)


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
    ("driver", "conditions mismatch"), ("gamescope", "conditions mismatch"),
    ("rng", "conditions mismatch"),
    ("state", "conditions mismatch"), ("tool", "capture tool SHA-256 mismatch"),
    ("input", "source mismatch"), ("settings-type", "conditions mismatch"),
    ("channel-order", "audio layout/count mismatch"),
    ("smoke", "capture kind"), ("wrong-exe", "not approved native EXE"),
    ("scene-gap", "scene partition has a gap"),
    ("scene-tail", "scene partition does not cover all frames"),
])
def test_identity_and_completeness_metadata(pair, capsys, fault, reason):
    m = pair[1].manifest
    if fault in ("driver", "gamescope"):
        m["conditions"]["environment"][fault] = f"other {fault}"
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
        (metadata / "pcm-completion.txt").write_bytes((capture.root / "pcm-completion.txt").read_bytes())
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


@pytest.mark.parametrize("fault,reason", [
    ("missing", "invalid fields"),
    ("short-submission", "PCM submitted extent"),
    ("raw-tick-as-count", "PCM synthesis tick delta"),
    ("short-cursor", "PCM final synthesis cursor"),
    ("read-at-submission", "PCM acquisition must follow"),
    ("simultaneous-read", "PCM acquisition must follow"),
    ("incomplete-read", "PCM acquisition must follow"),
    ("early-stability", "PCM acquisition must follow"),
    ("fractional-event", "expected integer"),
    ("changed-after-read", "PCM post-readback stability hash mismatch"),
    ("no-evidence", "missing payload"),
    ("empty-evidence", "empty PCM completion evidence"),
    ("changed-evidence", "PCM completion evidence SHA-256 mismatch"),
])
def test_matching_incomplete_pcm_evidence_fails_independently(pair, capsys, fault, reason):
    for capture in pair:
        proof = capture.manifest["completion"]["pcm"]
        if fault == "missing":
            del capture.manifest["completion"]["pcm"]
        elif fault == "short-submission":
            proof["submitted_bytes"] -= 4
        elif fault == "raw-tick-as-count":
            proof["final_tick"] -= 1
        elif fault == "short-cursor":
            proof["final_cursor_offset"] -= 4
        elif fault == "read-at-submission":
            proof["events"]["readback_begin"] = 1
        elif fault == "simultaneous-read":
            proof["events"]["readback_begin"] = proof["events"]["synth_complete"]
        elif fault == "incomplete-read":
            proof["events"]["readback_end"] = proof["events"]["readback_begin"]
        elif fault == "early-stability":
            proof["events"]["stability_check"] = proof["events"]["readback_end"]
        elif fault == "fractional-event":
            proof["events"]["readback_begin"] = 3.0
        elif fault == "changed-after-read":
            proof["stable_sha256"] = "f" * 64
        else:
            path = capture.root / proof["evidence"]
            if fault == "no-evidence":
                path.unlink()
            elif fault == "empty-evidence":
                path.write_bytes(b"")
                proof["evidence_sha256"] = sha(b"")
            else:
                path.write_bytes(b"changed evidence")
        capture.save()
    result = check(pair, capsys, reason)
    assert len(result["reasons"]) == 2


def test_run_specific_pcm_event_sequences_and_evidence(pair, capsys):
    capture = pair[1]
    proof = capture.manifest["completion"]["pcm"]
    proof["events"] = {key: value + 100 for key, value in proof["events"].items()}
    proof["evidence"] = "repeat-observations.txt"
    data = b"Different synthetic observation IDs; same bytes and completion semantics.\n"
    (capture.root / proof["evidence"]).write_bytes(data)
    proof["evidence_sha256"] = sha(data)
    capture.save()
    check(pair, capsys)


@pytest.mark.parametrize("key,shift", [
    ("clock_tick", 1), ("audio_position", 1), ("audio_position_num", 1),
])
def test_matching_timing_shifts_fail_independently(pair, capsys, key, shift):
    for capture in pair:
        for record in capture.records:
            record[key] += shift
        capture.save()
    result = check(pair, capsys, f"frame 0 {key}")
    assert len(result["reasons"]) == 2


@pytest.fixture
def native_pair(tmp_path):
    # All bytes are synthetic, even though the extents model T1's native findings.
    return (make_capture(tmp_path / "reference", "reference", native_shape=True),
            make_capture(tmp_path / "repeat", "repeat", storage="hashes", native_shape=True))


def claim_original_for_rejection(capture):
    # Deliberately forged identity exercises independent native rejection criteria.
    capture.manifest["source"].update(
        kind="original", exe_sha256="376b476c358a969da7d5d45c091355520453086ee8cd22625fdbb4fa3a9fd6be")
    capture.manifest["capture"]["kind"] = "controlled-reference"
    capture.save()


def test_native_sized_synthetic_pcm_tail_is_independent_of_visual_end(native_pair, capsys):
    capture = native_pair[0]
    assert capture.manifest["video"]["frame_count"] == 27000
    assert capture.manifest["termination"]["audio_position"] == 19845000
    assert capture.manifest["audio"]["sample_frames"] == 19964544
    assert capture.pcm.stat().st_size == 159716352
    assert capture.manifest["completion"]["pcm"]["final_tick"] == 19964545
    assert capture.records[-1]["audio_position"] == 19844265
    check(native_pair, capsys)


@pytest.mark.parametrize("samples", [19845000, 19964543, 19964545])
def test_matching_native_pcm_trim_or_extra_frame_cannot_redefine_extent(native_pair, capsys, samples):
    for capture in native_pair:
        with capture.pcm.open("r+b") as stream:
            stream.truncate(samples * 8)
        with capture.pcm.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        capture.manifest["audio"].update(sample_frames=samples, sha256=checksum)
        capture.manifest["completion"]["audio_sample_frames"] = samples
        capture.manifest["completion"]["pcm"].update(
            submitted_bytes=samples * 8, final_tick=samples + 1,
            final_cursor_offset=samples * 8, stable_sha256=checksum)
        capture.save()
        load_run(capture.path)  # Internally consistent synthetic payload, counts and hashes.
        claim_original_for_rejection(capture)
    result = check(native_pair, capsys, "original PCM must contain exactly 19964544")
    assert len(result["reasons"]) == 2


def test_matching_native_visual_truncation_cannot_redefine_endpoint(native_pair, capsys):
    for capture in native_pair:
        capture.records.pop()
        capture.manifest["video"]["frame_count"] = 26999
        capture.manifest["scenes"][-1]["last"] = 26998
        capture.manifest["termination"].update(end_tick=26999, audio_position=19844265,
                                               audio_position_num=1190655900)
        capture.manifest["completion"].update(frames_observed=26999, frames_hashed=26999)
        if capture.manifest["video"]["storage"] == "reference":
            raw = bytes((26998 * 13 + byte * 29) % 256 for byte in range(24))
            (capture.root / "026998.raw.zst").write_bytes(zstandard.ZstdCompressor().compress(raw))
            capture.records[-1]["raw_zst"] = "026998.raw.zst"
        capture.save()
        load_run(capture.path)
        claim_original_for_rejection(capture)
    result = check(native_pair, capsys, "original visual endpoint must be tick 27000")
    assert len(result["reasons"]) == 2


@pytest.mark.parametrize("fault,reason", [
    ("integer-pcm", "original PCM must retain native float32le"),
    ("zero-based-tick", "original synthesis tick must start at 1"),
    ("off-by-one-tick", "PCM synthesis tick delta"),
])
def test_native_completion_interpretation(native_pair, capsys, fault, reason):
    for capture in native_pair:
        if fault == "integer-pcm":
            capture.manifest["audio"]["sample_format"] = "s32le"
        elif fault == "zero-based-tick":
            capture.manifest["completion"]["pcm"].update(initial_tick=0, final_tick=19964544)
        else:
            capture.manifest["completion"]["pcm"]["final_tick"] = 19964544
        claim_original_for_rejection(capture)
    result = check(native_pair, capsys, reason)
    assert len(result["reasons"]) == 2
