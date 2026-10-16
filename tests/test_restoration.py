"""D12 contract fixtures: synthetic pixels/PCM/envelopes, real pinned shader files.

Successful metadata checks here are deliberately not native runtime acceptance.
Every mutation is confined to pytest's disposable checkout.
"""

from copy import deepcopy
import json
import os
from pathlib import Path

import pytest
import zstandard

from reference_factory import make_capture
from tools.verify import compatibility as compat, reference as ref, restoration as restored


# Independently checked native row endpoints (T14); inclusive bounds are end-1.
ENDS = [1440, 2160, 2880, 3600, 4320, 5760, 6120, 6570, 7200, 7920,
        8640, 10080, 10620, 11160, 11880, 12600, 12960, 13365, 13545, 13725,
        13905, 14085, 14445, 14715, 15120, 15480, 15840, 16200, 16560, 16920,
        17280, 17460, 18000, 18720, 19080, 19440, 19800, 20160, 20700, 21870,
        22500, 22770, 23040, 23400, 23580, 23760, 25020, 25740, 26280, 27000]


def binding(path, roots, root="checkout"):
    return {"root": root, "path": path.relative_to(roots[root]).as_posix(), "sha256": ref.hash_file(path)}


def publish(capture, sidecar, proof, roots):
    producer = capture.root / "producer.json"
    producer.write_text(json.dumps({"run_id": capture.manifest["run_id"], "reference_eligible": False,
                                    "reference_contract": proof}))
    sidecar["run_manifest"] = binding(producer, roots)
    path = capture.root / "eligibility.json"
    path.write_text(json.dumps(sidecar))
    capture.manifest["provenance"]["eligibility"] = binding(path, roots)
    capture.save()


@pytest.fixture
def factory(tmp_path):
    checkout = Path(__file__).resolve().parents[1]
    capture_root = Path(os.environ.get("EIDOLON_CAPTURE_ROOT", checkout)).resolve()
    roots = {"checkout": tmp_path, "shared": Path(os.environ["EIDOLON_ROOT"]),
             "data": Path(os.environ["EIDOLON_DATA"])}
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/wine-headless").write_bytes((checkout / "tools/wine-headless").read_bytes())
    saved = capture_root / "artifacts/reference/proxy-b-d11-boundary3-20261016-eligibility.json"

    def make(name="fixture", partial=True, storage="reference"):
        c = make_capture(tmp_path / name, name, storage=storage, native_shape=True)
        m = c.manifest
        sidecar = ref.load_json(saved.read_text())
        sidecar["run_id"] = name
        identity = {"decision": "D12", "transformation": "450-compatibility",
                    "raw_shader_sha256": compat.SOURCE_HASH,
                    "effective_shader_sha256": restored.EFFECTIVE_HASH,
                    "shim_sha256": {k: sidecar["build"]["outputs"][k]["sha256"] for k in restored.SHIMS}}
        m["schema"] = ref.PARTIAL_SCHEMA if partial else ref.RESTORED_SCHEMA
        m["source"].update(kind="D9-restored-native", exe_sha256=ref.ORIGINAL_SHA256,
                           restoration=identity)
        m["source"]["inputs"].update({k: compat.INPUT_HASHES[k] for k in ("archive", "bank")})
        m["capture"]["kind"] = "controlled-partial" if partial else "controlled-reference"
        count = 1443 if partial else 27000
        c.records = c.records[:count]
        m["video"]["frame_count"] = count
        m["termination"].update(reason="partial_stop" if partial else "natural_exit", end_tick=count,
                                audio_position=count*735, audio_position_num=count*44100)
        m["completion"].update(finalized=not partial, frames_observed=count, frames_hashed=count)
        m["scenes"] = [{"id": f"row-{i:02d}", "first": start, "last": min(end, count)-1}
                       for i, (start, end) in enumerate(zip([0] + ENDS, ENDS)) if start < count]
        if storage == "reference":
            anchors = {v for s in m["scenes"] for v in (s["first"], s["last"])}
            for n in anchors:
                raw = bytes((n*13 + byte*29) % 256 for byte in range(24))
                path = c.root / f"{n:06d}.raw.zst"
                path.write_bytes(zstandard.ZstdCompressor().compress(raw))
                c.records[n]["raw_zst"] = path.name
        m["provenance"] = {"native_image": binding(
            roots["data"] / "reverse/confirmed-debug/postfix-00400000.bin", roots, "data")}
        c.save()
        evidence = c.root / "fixture-observations.txt"
        evidence.write_text("Synthetic contract fixture; not observed runtime evidence.\n")
        proof = {"schema": m["schema"], "source": deepcopy(m["source"]),
                 "capture_tool_sha256": m["capture"]["tool_sha256"],
                 "video_index_sha256": m["video"]["index_sha256"], "frame_count": count,
                 "audio_sha256": m["audio"]["sha256"], "termination": deepcopy(m["termination"]),
                 "finalized": not partial, "exe_before_sha256": ref.ORIGINAL_SHA256,
                 "exe_after_sha256": ref.ORIGINAL_SHA256, "target_memory_before_sha256": compat.SOURCE_HASH,
                 "target_memory_after_sha256": compat.SOURCE_HASH,
                 "loaded_shim_sha256": deepcopy(identity["shim_sha256"]),
                 "observations": {"fixture": binding(evidence, roots)}}
        publish(c, sidecar, proof, roots)
        return c, sidecar, proof, roots

    return make


def test_full_contract_and_exact_comparison_do_not_accept_runtime(factory, capsys):
    a, _, _, roots = factory("reference", partial=False)
    b, _, _, _ = factory("repeat", partial=False, storage="hashes")
    x, y = [ref.load_run(c.path, provenance_roots=roots) for c in (a, b)]
    assert len(x.manifest["scenes"]) == 50
    assert sum("raw_zst" in frame for frame in x.frames) == 510
    assert ref.compare_runs(x, y) == []
    args = ["validate", str(a.path), "--checkout-root", str(roots["checkout"])]
    assert ref.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "PASS" and result["reference_accepted"] is False
    y.frames[120]["sha256"] = "f"*64
    assert "frame content mismatch" in " ".join(ref.compare_runs(x, y))
    with b.pcm.open("r+b") as stream:
        stream.seek(-1, 2)
        byte = stream.read(1)
        stream.seek(-1, 2)
        stream.write(bytes([byte[0] ^ 1]))
    assert "PCM byte mismatch at offset 159716351" in ref.compare_runs(x, y)
    y.manifest["source"]["restoration"]["shim_sha256"]["opengl32.dll"] = "a"*64
    assert "source mismatch" in ref.compare_runs(x, y)


def test_partial_integrity_never_becomes_full_acceptance(factory, capsys):
    c, _, _, roots = factory()
    run = ref.load_partial(c.path, provenance_roots=roots)
    assert "partial diagnostics cannot pass full comparison" in ref.compare_runs(run, run)
    with pytest.raises(ref.InvalidCapture, match="partial diagnostics"):
        ref.load_run(c.path, provenance_roots=roots)
    assert ref.main(["review-partial", str(c.path), "--checkout-root", str(roots["checkout"])]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "PARTIAL_ONLY" and result["reference_accepted"] is False


def test_existing_stage_sidecar_cannot_attest_a_new_full_reference(factory):
    c, _, _, roots = factory(partial=False)
    checkout = Path(__file__).resolve().parents[1]
    capture_root = Path(os.environ.get("EIDOLON_CAPTURE_ROOT", checkout)).resolve()
    path = capture_root / "artifacts/reference/proxy-b-d11-boundary3-20261016-eligibility.json"
    sidecar = ref.load_json(path.read_text())
    # Point to untouched real stage evidence; only the forged candidate is disposable.
    sidecar["run_manifest"] = binding(capture_root / sidecar["run_manifest"]["path"], roots, "shared")
    c.manifest["run_id"] = sidecar["run_id"]
    local = c.root / "old-sidecar.json"
    local.write_text(json.dumps(sidecar))
    c.manifest["provenance"]["eligibility"] = binding(local, roots)
    c.save()
    with pytest.raises(ref.InvalidCapture, match="expected an object"):
        ref.load_run(c.path, provenance_roots=roots)


@pytest.mark.parametrize("fault,reason", [
    ("unlabeled", "invalid source kind"), ("legacy-schema", "invalid fields"),
    ("missing-identity", "invalid fields"), ("missing-provenance", "invalid fields"),
    ("raw-hash", "raw/effective"), ("effective-hash", "raw/effective"),
    ("fallback", "directive-only"), ("shim", "differs from bound build"),
    ("exe", "not approved native EXE"), ("bank", "pinned bank"),
    ("finalized", "remain unfinalized"), ("natural-exit", "requires partial_stop"),
    ("scene-token", "original row identities"), ("old-run", "expected an object"),
    ("missing-proof", "invalid fields"), ("loaded-shim", "envelope disagrees"),
    ("changed-native-file", "envelope disagrees"), ("changed-native-memory", "envelope disagrees"),
    ("other-run", "run mismatch"), ("truncated-ledger", "incomplete original shader ledger"),
    ("unrelated-edit", "unrelated shader source array changed"),
    ("rewritten-original", "immutable native image"),
    ("missing-observations", "missing restoration runtime observations"),
    ("observation-hash", "bound artifact hash mismatch"),
    ("stop-mismatch", "envelope disagrees"),
])
def test_restoration_fails_closed_with_refreshed_envelope_hashes(factory, fault, reason):
    c, sidecar, proof, roots = factory()
    m = c.manifest
    identity = m["source"]["restoration"]
    if fault == "unlabeled":
        m["source"]["kind"] = "original"
    elif fault == "legacy-schema":
        m["schema"] = ref.SCHEMA
    elif fault == "missing-identity":
        del m["source"]["restoration"]
    elif fault == "raw-hash":
        identity["raw_shader_sha256"] = "a"*64
    elif fault == "effective-hash":
        identity["effective_shader_sha256"] = "a"*64
    elif fault == "fallback":
        identity["transformation"] = "450-explicit-output-0"
    elif fault == "shim":
        identity["shim_sha256"]["winmm.dll"] = "a"*64
    elif fault == "exe":
        m["source"]["exe_sha256"] = "a"*64
    elif fault == "bank":
        m["source"]["inputs"]["bank"] = "a"*64
    elif fault == "finalized":
        m["completion"]["finalized"] = True
    elif fault == "natural-exit":
        m["termination"]["reason"] = "natural_exit"
    elif fault == "scene-token":
        m["scenes"] = [{"id": "token-0", "first": 0, "last": 1442}]
    elif fault == "old-run":
        proof = None
    elif fault == "missing-proof":
        del proof["target_memory_after_sha256"]
    elif fault == "loaded-shim":
        proof["loaded_shim_sha256"]["opengl32.dll"] = "a"*64
    elif fault == "changed-native-file":
        proof["exe_after_sha256"] = "a"*64
    elif fault == "changed-native-memory":
        proof["target_memory_after_sha256"] = restored.EFFECTIVE_HASH
    elif fault == "other-run":
        sidecar["run_id"] = "other"
    elif fault == "truncated-ledger":
        sidecar["calls"].pop()
    elif fault in ("unrelated-edit", "rewritten-original"):
        path = c.root / "wrong.glsl"
        path.write_text("#version 450\n// unauthorized sibling\n")
        sidecar["calls"][2]["forwarded"][0] = binding(path, roots)
        if fault == "rewritten-original":
            sidecar["calls"][2]["input"][0] = binding(path, roots)
    elif fault == "missing-observations":
        proof["observations"] = {}
    elif fault == "observation-hash":
        (c.root / "fixture-observations.txt").write_text("changed")
    elif fault == "stop-mismatch":
        proof["termination"]["reason"] = "natural_exit"
    publish(c, sidecar, proof, roots)
    if fault == "missing-provenance":
        del m["provenance"]
        c.save()
    if fault == "other-run":
        # Keep the sidecar internally consistent to exercise the outer run binding.
        producer = c.root / "producer.json"
        data = json.loads(producer.read_text())
        data["run_id"] = "other"
        producer.write_text(json.dumps(data))
        sidecar["run_manifest"] = binding(producer, roots)
        path = c.root / "eligibility.json"
        path.write_text(json.dumps(sidecar))
        m["provenance"]["eligibility"] = binding(path, roots)
        c.save()
    loader = ref.load_run if fault == "legacy-schema" else ref.load_partial
    with pytest.raises(ref.InvalidCapture, match=reason):
        loader(c.path, provenance_roots=roots)


@pytest.mark.parametrize("fault,reason", [
    ("partial-endpoint", "visual endpoint must be tick 27000"),
    ("trim-pcm", "exactly 19964544"), ("shift", "frame 1 audio_position"),
    ("missing-row-edge", "missing required raw frames"),
])
def test_full_restored_variant_keeps_independent_exactness(factory, fault, reason):
    c, sidecar, proof, roots = factory(partial=False)
    m = c.manifest
    if fault == "partial-endpoint":
        m["video"]["frame_count"] = 1443
        proof["frame_count"] = 1443
    elif fault == "trim-pcm":
        m["audio"]["sample_frames"] = 19845000
    elif fault == "shift":
        c.records[1]["audio_position"] += 1
    else:
        del c.records[1439]["raw_zst"]
    c.save()
    proof["video_index_sha256"] = m["video"]["index_sha256"]
    publish(c, sidecar, proof, roots)
    with pytest.raises(ref.InvalidCapture, match=reason):
        ref.load_run(c.path, provenance_roots=roots)
