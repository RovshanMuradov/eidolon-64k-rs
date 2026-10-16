"""Native-backed, disposable faults. No GPU, Wine, Windows EXE or port oracle."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile

import pytest
import zstandard

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/verify/rust"))
import conformance as c
from check_partials import probes


@pytest.fixture(scope="session")
def native():
    return c.Native()


@pytest.fixture(scope="session")
def vectors(native):
    result = native.times()
    digest = hashlib.sha256(b"".join(struct.pack("<5I", *r) for r in result)).hexdigest()
    assert digest == "363ca20b3e537f57da1d0dd937a3e1fc9f3c92e3377af9c7d8d12706186cf406"
    return result


@pytest.fixture(scope="session")
def streams(tmp_path_factory):
    return probes(tmp_path_factory.mktemp("probe"))[1]


def test_native_self_integrity(native):
    assert c.compare_frames(native, native.frames, native.directory)["retained_raws"] == 510
    assert c.exact_files(native.pcm, native.pcm, c.PCM_BYTES) == c.PCM_BYTES


@pytest.mark.parametrize("kind", ["raw", "state"])
def test_cpu_native_time_and_initial_state(native, vectors, streams, kind):
    assert c.compare_probe(native, streams[kind], vectors)["native_time_frames"] == c.N


def test_effective_shader_bytes(native, streams):
    assert c.compare_shaders(native, streams["shader"])["native_effective_shader_elements"] == 235


@pytest.mark.parametrize("fault", ["missing", "truncated", "extra", "reorder", "time", "alpha", "boolean"])
def test_frame_faults(native, fault):
    records = [{k: v for k, v in r.items() if k != "raw_zst"} for r in native.frames]
    if fault == "missing": records.pop(1)
    elif fault == "truncated": records.pop()
    elif fault == "extra": records.append(records[-1])
    elif fault == "reorder": records[0], records[1] = records[1], records[0]
    elif fault == "time": records[1]["audio_position"] += 1
    elif fault == "alpha": records[-1]["sha256"] = "0" * 64
    else: records[0]["n"] = False
    with pytest.raises(ValueError):
        c.compare_frames(native, records, native.directory, require_raw=False)


def test_missing_raw_rejected(native):
    records = [{k: v for k, v in r.items() if k != "raw_zst"} for r in native.frames]
    with pytest.raises(ValueError, match="missing retained"):
        c.compare_frames(native, records, native.directory)


@pytest.mark.parametrize("fault", ["alpha", "short", "trailing", "concatenated"])
def test_actual_rgba_faults(native, tmp_path, fault):
    source = (native.directory / native.frames[0]["raw_zst"]).read_bytes()
    raw = bytearray(zstandard.ZstdDecompressor().decompress(source, max_output_size=8294400))
    if fault == "alpha": raw[3] ^= 1
    if fault == "short": raw.pop()
    data = zstandard.ZstdCompressor().compress(raw)
    if fault == "trailing": data += b"X"
    if fault == "concatenated": data += source
    p = tmp_path / "frame.zst"; p.write_bytes(data)
    with pytest.raises(ValueError):
        c.ref.verify_raw(p, 8294400, native.frames[0]["sha256"])


@pytest.mark.parametrize("fault", ["first", "tail", "short", "extra", "shift", "visual_trim", "missing"])
def test_actual_pcm_faults(native, tmp_path, fault):
    p = tmp_path / "candidate.f32le"
    if fault != "missing": shutil.copyfile(native.pcm, p)
    try:
        if fault in ("first", "tail"):
            with p.open("r+b") as f:
                f.seek(0 if fault == "first" else c.PCM_BYTES - 1)
                offset = f.tell(); value = f.read(1)[0]; f.seek(offset); f.write(bytes([value ^ 1]))
        elif fault in ("short", "visual_trim"):
            with p.open("r+b") as f: f.truncate(c.PCM_BYTES - 8 if fault == "short" else 19845000 * 8)
        elif fault == "extra":
            with p.open("ab") as f: f.write(b"\0" * 8)
        elif fault == "shift":
            with native.pcm.open("rb") as a, p.open("wb") as b:
                a.seek(8); shutil.copyfileobj(a, b); b.write(b"\0" * 8)
        # The candidate supplies a refreshed hash; it still cannot evade native byte comparison.
        if p.exists(): c.checked(p, c.sha(p))
        with pytest.raises((ValueError, OSError)):
            c.exact_files(native.pcm, p, c.PCM_BYTES)
    finally:
        p.unlink(missing_ok=True)


@pytest.mark.parametrize("offset", [8, 12, 16, 20, 24, 28, 32])
def test_time_word_faults(native, vectors, streams, tmp_path, offset):
    raw = bytearray(streams["raw"].read_bytes()); raw[offset] ^= 1
    p = tmp_path / "probe.bin"; p.write_bytes(raw)
    with pytest.raises(ValueError): c.compare_probe(native, p, vectors)


@pytest.mark.parametrize("fault", ["truncated", "extra", "magic", "state"])
def test_probe_extent_and_state_faults(native, vectors, streams, tmp_path, fault):
    raw = bytearray(streams["state"].read_bytes())
    if fault == "truncated": raw.pop()
    elif fault == "extra": raw += b"\0"
    elif fault == "magic": raw[0] ^= 1
    else:
        count = struct.unpack_from("<I", raw, 36)[0]; at = 40
        for _ in range(count): at += 8 + 4 * struct.unpack_from("<I", raw, at + 4)[0]
        raw[at] ^= 1
    p = tmp_path / "state.bin"; p.write_bytes(raw)
    with pytest.raises(ValueError): c.compare_probe(native, p, vectors)


@pytest.mark.parametrize("fault", ["change", "truncate", "append"])
def test_shader_faults(native, streams, tmp_path, fault):
    raw = bytearray(streams["shader"].read_bytes())
    if fault == "change": raw[24] ^= 1
    elif fault == "truncate": raw.pop()
    else: raw += b"\0"
    p = tmp_path / "shader.bin"; p.write_bytes(raw)
    with pytest.raises(ValueError): c.compare_shaders(native, p)


@pytest.fixture
def metadata(native):
    # Only metadata fixture: it is never presented as a production capture.
    return dict(schema="eidolon-rust-candidate-1", kind="production-rust-capture", reference_sha256=c.PIN,
                executable={}, inputs={}, runtime={}, frames={}, pcm={},
                video={k: v for k, v in native.manifest["video"].items() if k not in ("index", "index_sha256", "storage")},
                audio={k: v for k, v in native.manifest["audio"].items() if k not in ("path", "sha256")},
                state=dict.fromkeys(native.states, {}),
                completion=dict(finalized=True, frames_observed=c.N, frames_hashed=c.N, audio_sample_frames=19964544,
                                dropped_frames=0, dropped_audio_sample_frames=0, errors=[]),
                endpoint=dict(reason="natural_exit", exit_code=0, queries=c.N+1, frames=c.N, last_present=c.N-1,
                              terminal_cursor=19845000, wrapper_stop=False),
                pcm_completion=dict(rendered_sample_frames=19964544, submitted_bytes=c.PCM_BYTES,
                                    stable_sha256=native.manifest["audio"]["sha256"],
                                    events=dict(render_complete=1, readback_begin=2, readback_end=3, stability_check=4)),
                observations=dict.fromkeys("identity clock state pcm_completion endpoint".split(), {}))


def test_metadata_is_not_production_acceptance(native, metadata, tmp_path):
    c.candidate_metadata(native, metadata)
    path = tmp_path / "candidate.json"; path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError): c.full_run(native, path)


@pytest.fixture
def linked_root():
    root = c.DATA / "verification/rust"
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="T24-fixture-", dir=root) as directory:
        yield Path(directory)


def test_full_file_contract_still_cannot_certify_runtime(native, metadata, linked_root):
    # Native byte-clone fixture tests plumbing, never genuine candidate execution.
    # Hardlinked originals are only read; mutations use separate copied files elsewhere.
    def bind(source, name):
        target = linked_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(source, target)
        return dict(path=name, sha256=c.sha(target))
    exe = c.DATA / "builds/T22/cross/i686-pc-windows-gnu/release/eidolon-engine.exe"
    metadata["executable"] = bind(exe, "candidate.exe")
    metadata["inputs"] = {"fixture": bind(native.path, "native-input.json")}
    metadata["frames"] = bind(native.path.parent / native.manifest["video"]["index"], "frames.jsonl")
    for frame in native.frames:
        if "raw_zst" in frame: bind(native.directory / frame["raw_zst"], frame["raw_zst"])
    metadata["pcm"] = bind(native.pcm, "pcm.f32le")
    for key, source in native.states.items(): metadata["state"][key] = bind(source, "state/" + source.name)
    observation = metadata["inputs"]["fixture"]
    metadata["observations"] = dict.fromkeys(metadata["observations"], observation)
    metadata["runtime"] = dict(environment=native.manifest["conditions"]["environment"],
                               exe_before_sha256=metadata["executable"]["sha256"],
                               exe_after_sha256=metadata["executable"]["sha256"],
                               command=["fixture-never-executed"], capture_tool=observation)
    path = linked_root / "candidate.json"; path.write_text(json.dumps(metadata))
    result = c.full_run(native, path)
    assert result["frames"] == 27000 and result["pcm_bytes"] == c.PCM_BYTES
    assert result["production_accepted"] is False and result["runtime_evidence_authenticated"] is False


@pytest.mark.parametrize("group,key,value", [
    ("endpoint", "reason", "timeout"), ("endpoint", "queries", 27000),
    ("endpoint", "last_present", 27000), ("endpoint", "wrapper_stop", True),
    ("endpoint", "exit_code", False), ("completion", "finalized", False),
    ("completion", "dropped_frames", 1), ("completion", "errors", ["capture failed"]),
    ("audio", "sample_frames", 19845000), ("audio", "sample_format", "s16le"),
    ("video", "row_order", "top-down"), ("pcm_completion", "submitted_bytes", c.PCM_BYTES-8),
    ("pcm_completion", "stable_sha256", "0"*64),
])
def test_full_run_metadata_faults(native, metadata, group, key, value):
    metadata[group][key] = value
    with pytest.raises(ValueError): c.candidate_metadata(native, metadata)


def test_missing_state_and_early_pcm(native, metadata):
    metadata["state"].pop("prethread/rng")
    with pytest.raises(ValueError, match="state coverage"): c.candidate_metadata(native, metadata)
    metadata["state"]["prethread/rng"] = {}
    metadata["pcm_completion"]["events"]["readback_begin"] = 1
    with pytest.raises(ValueError, match="acquisition order"): c.candidate_metadata(native, metadata)


@pytest.mark.parametrize("fault", ["kind", "reference", "field"])
def test_candidate_identity_scope(native, metadata, fault):
    if fault == "kind": metadata["kind"] = "hybrid-source-oracle-diagnostic"
    elif fault == "reference": metadata["reference_sha256"] = "0"*64
    else: metadata["reference_accepted"] = True
    with pytest.raises(ValueError): c.candidate_metadata(native, metadata)


def test_duplicate_nonfinite_and_escaped_payload(tmp_path):
    for raw in (b'{"a":1,"a":2}', b'{"a":NaN}'):
        with pytest.raises(ValueError): c.ref.load_json(raw)
    with pytest.raises(ValueError): c.binding(tmp_path, dict(path="../outside", sha256="0"*64))


def test_changed_native_manifest_is_not_repinable(native, tmp_path):
    path = tmp_path / "artifacts/reference" / native.path.name
    path.parent.mkdir(parents=True)
    value = copy.deepcopy(native.manifest); value["run_id"] = "replacement"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="identity mismatch"):
        c.Native(capture=tmp_path)


def test_pe_static_identity_and_fault(tmp_path):
    original = c.DATA / "builds/T22/cross/i686-pc-windows-gnu/release/eidolon-engine.exe"
    result = c.pe_identity(original)
    assert result["machine"] == 332 and "KERNEL32.dll" in result["imports"]
    raw = bytearray(original.read_bytes()); pe = struct.unpack_from("<I", raw, 60)[0]
    struct.pack_into("<H", raw, pe+4, 0x8664)
    p = tmp_path / "wrong-machine.exe"; p.write_bytes(raw)
    with pytest.raises(ValueError, match="i386 PE32"): c.pe_identity(p)
