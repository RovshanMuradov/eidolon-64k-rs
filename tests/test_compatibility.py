"""D9 file-only checks with real pinned shader/input bytes and synthetic run/shim fixtures."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import zipfile

import pytest

from reference_factory import make_capture
from tools.verify import compatibility as compat
from tools.verify import reference as ref


def bind(roots, root, path):
    return {"root": root, "path": path, "sha256": ref.hash_file(roots[root] / path)}


def save(roots, path, content):
    (roots["data"] / path).write_bytes(content)
    return bind(roots, "data", path)


@pytest.fixture
def experiment(tmp_path):
    checkout = Path(__file__).resolve().parents[1]
    shared = Path(os.environ["EIDOLON_ROOT"])
    roots = {"checkout": checkout, "shared": shared, "data": tmp_path}
    archive = "eidolon_-_poo-brain_-_revision2017_64k_-_rc4.zip"
    with zipfile.ZipFile(checkout / archive) as source:
        exe, = [name for name in source.namelist() if name.endswith("Eidolon - Poo-Brain (native).exe")]
        exe_binding = save(roots, "native.exe", source.read(exe))
    original = (Path(os.environ["EIDOLON_DATA"]) /
                "reference/proxy-b-gl-shader-20261016/program-source-0.glsl").read_bytes()
    replacement = b"#version 450 compatibility\n" + original.split(b"\n", 1)[1]
    original_binding = save(roots, "original.glsl", original)
    replacement_binding = save(roots, "replacement.glsl", replacement)
    # Deliberately incomplete runtime evidence: passing provenance must not accept it.
    run = {"run_id": "synthetic-D9-fixture", "reference_eligible": False, "frames": []}
    m = {
        "schema": compat.SCHEMA, "kind": "compatibility-modified-diagnostic", "decision": "D9",
        "run_id": run["run_id"], "reference_eligible": False,
        "run_manifest": save(roots, "run.json", json.dumps(run).encode()),
        "inputs": {
            "exe": exe_binding, "archive": bind(roots, "checkout", archive),
            "bank": bind(roots, "shared", "data/reference/dependencies/gm.dls"),
            "launcher": bind(roots, "checkout", "tools/wine-headless"),
        },
        "build": {
            "inputs": {"core.c": bind(roots, "checkout", "tools/capture/proxy-b/core.c")},
            "outputs": {name: save(roots, name, b"synthetic shim placeholder")
                        for name in ("opengl32.dll", "winmm.dll")},
            "compiler": "synthetic build fixture; no compilation", "commands": [["fixture"]],
        },
        "transformation": "450-compatibility", "fallback": None,
        "calls": [{
            "sequence": 1, "stage": 0x8b30, "count": 1,
            "caller": "0x00406dcc", "return": "0x00406dce", "source_addresses": ["0x00409918"],
            "input": [original_binding], "forwarded": [replacement_binding],
            "forward_calls": 1, "program": 37,  # Never assume the old program ID 2.
        }],
    }
    return m, roots, tmp_path / "eligibility.json"


def assess(experiment):
    m, roots, path = experiment
    path.write_text(json.dumps(m))
    return compat.assess(path, roots)


def fallback(experiment):
    m, roots, _ = experiment
    original = (roots["data"] / "original.glsl").read_bytes()
    source = original.replace(b"#version 450\n", b"#version 450\nlayout(location=0) out vec4 eidolon_FragColor;\n")
    source = source.replace(b"gl_FragColor", b"eidolon_FragColor")
    m["calls"][0]["forwarded"] = [save(roots, "fallback.glsl", source)]
    m["transformation"] = "450-explicit-output-0"
    m["fallback"] = {
        "failed_primary": save(roots, "primary-failure.json", b'{"synthetic":true}'),
        "routing": save(roots, "routing.json", b'{"synthetic":true}'),
    }


@pytest.mark.parametrize("mode,size,checksum", [
    ("450-compatibility", 1324, "cb62ed7fd0878836b763b892f64cb9e4a789f49f304d32d0a2fc334aecb433ea"),
    ("450-explicit-output-0", 1362, "a9b79ea049f9c36023ca95d7bb6c2bfbba89b547cfdfd7b760f495232f2d9961"),
])
def test_pinned_source_edits_never_accept_missing_runtime_evidence(experiment, mode, size, checksum):
    if mode == "450-explicit-output-0":
        fallback(experiment)
    m, roots, path = experiment
    expected = compat.authorized_source((roots["data"] / "original.glsl").read_bytes(), mode)
    assert len(expected) == size and hashlib.sha256(expected).hexdigest() == checksum
    result = assess(experiment)
    assert result["status"] == "PROVENANCE_ONLY"
    assert result["source_edit_matches_d9"] is True
    assert result["runtime_semantics_verified"] is False
    assert result["reference_eligible"] is result["reference_accepted"] is False
    with pytest.raises(ref.InvalidCapture, match="invalid fields"):
        ref.load_run(path)


@pytest.mark.parametrize("fault,reason", [
    ("wrong-stage", "fingerprint changed"), ("wrong-return", "fingerprint changed"),
    ("wrong-address", "fingerprint changed"), ("wrong-caller", "unrelated shader"),
    ("zero-forward", "forwarded exactly once"), ("double-forward", "forwarded exactly once"),
    ("bool-count", "expected integer"), ("multiple-strings", "fingerprint changed"),
    ("array-length", "array length mismatch"), ("no-calls", "missing shader creation"),
    ("duplicate-target", "exactly one authorized"), ("sequence-gap", "gap, duplicate"),
    ("no-substitution", "unauthorized source edit"), ("global-rewrite", "unrelated shader"),
    ("unrecognized-mode", "unauthorized transformation ID"),
])
def test_call_routing_and_edit_scope_fail_closed(experiment, fault, reason):
    m, _, _ = experiment
    call = m["calls"][0]
    changes = {
        "wrong-stage": ("stage", 0x8b31), "wrong-return": ("return", "0x00406dd0"),
        "wrong-address": ("source_addresses", ["0x00409919"]),
        "wrong-caller": ("caller", "0x00406dcd"), "zero-forward": ("forward_calls", 0),
        "double-forward": ("forward_calls", 2), "bool-count": ("count", True),
        "array-length": ("count", 2), "sequence-gap": ("sequence", 2),
    }
    if fault in changes:
        key, value = changes[fault]
        call[key] = value
    elif fault == "multiple-strings":
        call["count"] = 2
        for key in ("source_addresses", "input", "forwarded"):
            call[key] *= 2
    elif fault == "no-calls":
        m["calls"] = []
    elif fault in ("duplicate-target", "global-rewrite"):
        extra = deepcopy(call)
        extra["sequence"] = 2
        if fault == "global-rewrite":
            extra["caller"], extra["return"] = "0x00408000", "0x00408002"
        m["calls"].append(extra)
    elif fault == "no-substitution":
        call["forwarded"] = deepcopy(call["input"])
    else:
        m["transformation"] = "420-downgrade"
    with pytest.raises(ref.InvalidCapture, match=reason):
        assess(experiment)


@pytest.mark.parametrize("fault,reason", [
    ("body-edit", "unauthorized source edit"), ("version-downgrade", "unauthorized source edit"),
    ("alpha-edit", "unauthorized source edit"), ("nul-tail", "exclude NUL"),
    ("unpinned-original", "not D7-pinned"), ("stale-shim-hash", "bound artifact hash mismatch"),
    ("missing-shim", "missing payload"), ("missing-build-inputs", "missing build inputs"),
    ("missing-proxy", "missing proxy DLL"), ("changed-exe", "unapproved exe"),
    ("changed-bank", "unapproved bank"), ("missing-run", "missing payload"),
    ("wrong-run", "same ineligible experiment"), ("wrong-label", "labeled ineligible"),
    ("reference-eligible", "labeled ineligible"), ("missing-field", "invalid fields"),
    ("path-escape", "root-relative"),
])
def test_hash_refresh_does_not_authorize_changes(experiment, fault, reason):
    m, roots, _ = experiment
    call = m["calls"][0]
    source = (roots["data"] / "replacement.glsl").read_bytes()
    if fault in ("body-edit", "version-downgrade", "alpha-edit", "nul-tail"):
        changed = {"body-edit": source.replace(b"5151.5473453", b"5151.5473454"),
                   "version-downgrade": source.replace(b"450", b"420", 1),
                   "alpha-edit": source.replace(b",0);}", b",1);}"), "nul-tail": source + b"\0"}[fault]
        assert changed != source
        call["forwarded"] = [save(roots, "replacement.glsl", changed)]
    elif fault == "unpinned-original":
        call["input"] = [save(roots, "original.glsl", b"#version 450\nvoid main(){}")]
    elif fault in ("stale-shim-hash", "missing-shim"):
        path = roots["data"] / "opengl32.dll"
        if fault == "missing-shim":
            path.unlink()
        else:
            path.write_bytes(b"changed shim")
    elif fault == "missing-build-inputs":
        m["build"]["inputs"] = {}
    elif fault == "missing-proxy":
        del m["build"]["outputs"]["winmm.dll"]
    elif fault in ("changed-exe", "changed-bank"):
        name = fault.removeprefix("changed-")
        m["inputs"][name] = save(roots, "changed-input", b"changed original input")
    elif fault == "missing-run":
        (roots["data"] / "run.json").unlink()
    elif fault == "wrong-run":
        m["run_manifest"] = save(roots, "run.json", b'{"run_id":"other","reference_eligible":false}')
    elif fault == "wrong-label":
        m["kind"] = "original"
    elif fault == "reference-eligible":
        m["reference_eligible"] = True
    elif fault == "missing-field":
        del m["inputs"]["launcher"]
    else:
        m["inputs"]["launcher"]["path"] = "../tools/wine-headless"
    with pytest.raises(ref.InvalidCapture, match=reason):
        assess(experiment)


@pytest.mark.parametrize("missing", ["failed_primary", "routing"])
def test_fallback_requires_bound_prerequisite_artifacts(experiment, missing):
    fallback(experiment)
    del experiment[0]["fallback"][missing]
    with pytest.raises(ref.InvalidCapture, match="invalid fields"):
        assess(experiment)


def test_fallback_location_change_is_not_authorized_even_with_refreshed_hash(experiment):
    fallback(experiment)
    m, roots, _ = experiment
    source = (roots["data"] / "fallback.glsl").read_bytes()
    m["calls"][0]["forwarded"] = [save(roots, "fallback.glsl", source.replace(b"location=0", b"location=1"))]
    with pytest.raises(ref.InvalidCapture, match="unauthorized source edit"):
        assess(experiment)


def test_unrelated_multistring_program_is_preserved_and_real_handle_is_not_assumed(experiment):
    m, roots, _ = experiment
    extra = deepcopy(m["calls"][0])
    extra.update(sequence=2, caller="0x00408000", count=2, source_addresses=["0x00500000", "0x00501000"])
    extra["input"] = [save(roots, "unrelated-1.glsl", b"#version 450\n"),
                      save(roots, "unrelated-2.glsl", b"void main(){}")]
    extra["forwarded"] = deepcopy(extra["input"])
    extra["program"] = 0  # Failed link/use is for runtime review, not a byte-edit check.
    m["calls"].append(extra)
    assert assess(experiment)["shader_calls_checked"] == 2


def test_cli_provenance_success_and_failure_never_report_reference_pass(experiment, capsys):
    m, roots, path = experiment
    path.write_text(json.dumps(m))
    args = [str(path), "--checkout-root", str(roots["checkout"]),
            "--shared-root", str(roots["shared"]), "--data-root", str(roots["data"])]
    assert compat.main(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PROVENANCE_ONLY"
    path.write_text('{"schema":"a","schema":"b"}')
    assert compat.main(args) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "FAIL" and result["reference_accepted"] is False


def test_full_reference_checker_rejects_modified_source_kind(tmp_path):
    capture = make_capture(tmp_path / "modified", "modified")
    capture.manifest["source"]["kind"] = "compatibility-modified-diagnostic"
    capture.save()
    with pytest.raises(ref.InvalidCapture, match="invalid source kind"):
        ref.load_run(capture.path)
