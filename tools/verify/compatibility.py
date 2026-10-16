#!/usr/bin/env python3
"""File-only D9 provenance/edit checks; never accepts runtime semantics or a reference."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

if __package__:
    from . import reference as ref
else:
    import reference as ref


SCHEMA = "eidolon-d9-eligibility-1"
# Approved native inputs and D7's saved glCreateShaderProgramv source identity.
INPUT_HASHES = {
    "exe": ref.ORIGINAL_SHA256,
    "archive": "11104969a59ef85d1f7ed416abfb01a377834504369902a735eb1a2fd1e40008",
    "bank": "3229b09b9d7d9f3f4793b0d9b34fe6abc75cfa4a2503c0c90f43ff651ba7f2c0",
}
SOURCE_HASH = "57cdc43590d369b0744da71530cf879b6099cc6d80797809b59abd0fa5cc2182"
MODES = ("450-compatibility", "450-explicit-output-0")
CALLER, RETURN, SOURCE_ADDRESS = "0x00406dcc", "0x00406dce", "0x00409918"


def authorized_source(original, mode):
    ref.require(mode in MODES, "unauthorized transformation ID")
    ref.require(len(original) == 1310 and hashlib.sha256(original).hexdigest() == SOURCE_HASH,
                "original source is not D7-pinned bytes")
    header, body = original.split(b"\n", 1)
    ref.require(header == b"#version 450" and body.count(b"gl_FragColor") == 1,
                "unexpected original source structure")
    if mode == "450-compatibility":
        return b"#version 450 compatibility\n" + body
    return (header + b"\nlayout(location=0) out vec4 eidolon_FragColor;\n"
            + body.replace(b"gl_FragColor", b"eidolon_FragColor"))


def bound_file(binding, roots):
    ref.fields(binding, ("root", "path", "sha256"))
    ref.text(binding["root"], "artifact root")
    ref.require(binding["root"] in roots, "unknown artifact root")
    ref.digest(binding["sha256"], "artifact hash")
    path = ref.payload_path(roots[binding["root"]], binding["path"])
    ref.require(ref.hash_file(path) == binding["sha256"], f"bound artifact hash mismatch: {path.name}")
    return path


def pointer(value):
    ref.require(isinstance(value, str) and re.fullmatch(r"0x[0-9a-f]{8}", value),
                "expected canonical 32-bit address")


def verify_calls(calls, mode, roots):
    ref.require(isinstance(calls, list) and bool(calls), "missing shader creation ledger")
    substitutions = 0
    for sequence, call in enumerate(calls, 1):
        ref.fields(call, ("sequence", "stage", "count", "caller", "return", "source_addresses",
                          "input", "forwarded", "forward_calls", "program"))
        for key in ("sequence", "stage", "count", "forward_calls", "program"):
            ref.integer(call[key], f"shader call {key}")
        ref.require(call["sequence"] == sequence, "shader ledger has a gap, duplicate or reordering")
        ref.require(call["forward_calls"] == 1, "shader API must be forwarded exactly once")
        pointer(call["caller"])
        pointer(call["return"])
        for key in ("input", "forwarded", "source_addresses"):
            ref.require(isinstance(call[key], list) and len(call[key]) == call["count"] > 0,
                        "shader count/array length mismatch")
        for address in call["source_addresses"]:
            pointer(address)
        before = [bound_file(item, roots).read_bytes() for item in call["input"]]
        after = [bound_file(item, roots).read_bytes() for item in call["forwarded"]]
        ref.require(all(b"\0" not in source for source in before + after),
                    "saved shader strings must exclude NUL terminators")
        # The original 30-record creation loop shares this PC. Only its
        # source-address role identifies D7; siblings must remain byte-identical.
        # Membership (not just element zero) keeps malformed target arrays closed.
        if call["caller"] == CALLER and SOURCE_ADDRESS in call["source_addresses"]:
            ref.require(call["return"] == RETURN and call["stage"] == 0x8b30
                        and call["count"] == 1 and call["source_addresses"] == [SOURCE_ADDRESS],
                        "expected shader call fingerprint changed")
            ref.require(after[0] == authorized_source(before[0], mode),
                        "candidate contains an unauthorized source edit")
            substitutions += 1
        else:
            ref.require(before == after, "unrelated shader source array changed")
    ref.require(substitutions == 1, "expected exactly one authorized substitution")
    return len(calls)


def assess(manifest_path, roots):
    m = ref.load_json(manifest_path.read_text(encoding="utf-8"))
    ref.fields(m, ("schema", "kind", "decision", "run_id", "reference_eligible", "run_manifest",
                   "inputs", "build", "transformation", "calls", "fallback"))
    ref.require(m["schema"] == SCHEMA, "unsupported D9 provenance schema")
    ref.require(m["kind"] == "compatibility-modified-diagnostic" and m["decision"] == "D9"
                and m["reference_eligible"] is False, "D9 must remain a labeled ineligible experiment")
    ref.text(m["run_id"], "run_id")
    # The producer's run manifest retains its native schema and actual stop state.
    # Hash binding is not a semantic review of its runtime claims.
    run_path = bound_file(m["run_manifest"], roots)
    run = ref.load_json(run_path.read_text(encoding="utf-8"))
    ref.require(isinstance(run, dict) and run.get("run_id") == m["run_id"]
                and run.get("reference_eligible") is False,
                "bound run must identify the same ineligible experiment")
    ref.fields(m["inputs"], (*INPUT_HASHES, "launcher"))
    for name, binding in m["inputs"].items():
        path = bound_file(binding, roots)
        if name in INPUT_HASHES:
            ref.require(binding["sha256"] == INPUT_HASHES[name], f"unapproved {name} identity")
        ref.require(path.stat().st_size > 0, "empty input artifact")
    build = m["build"]
    ref.fields(build, ("inputs", "outputs", "compiler", "commands"))
    ref.text(build["compiler"], "compiler identity/version")
    for key in ("inputs", "outputs"):
        ref.require(isinstance(build[key], dict) and bool(build[key]), f"missing build {key}")
        for name, binding in build[key].items():
            ref.text(name, f"build {key} name")
            ref.require(bound_file(binding, roots).stat().st_size > 0, "empty build artifact")
    ref.require({"opengl32.dll", "winmm.dll"} <= build["outputs"].keys(), "missing proxy DLL identity")
    ref.require(isinstance(build["commands"], list) and bool(build["commands"]), "missing build commands")
    for command in build["commands"]:
        ref.require(isinstance(command, list) and bool(command), "expected build argv array")
        for arg in command:
            ref.text(arg, "build argument")
    ref.require(m["transformation"] in MODES, "unauthorized transformation ID")
    if m["transformation"] == "450-explicit-output-0":
        ref.fields(m["fallback"], ("failed_primary", "routing"))
        for binding in m["fallback"].values():
            ref.require(bound_file(binding, roots).stat().st_size > 0, "empty fallback evidence")
    else:
        ref.require(m["fallback"] is None, "primary experiment cannot claim fallback evidence")
    count = verify_calls(m["calls"], m["transformation"], roots)
    return {
        "status": "PROVENANCE_ONLY", "run_id": m["run_id"],
        "manifest_sha256": ref.hash_file(manifest_path), "shader_calls_checked": count,
        "transformation": m["transformation"], "source_edit_matches_d9": True,
        "runtime_semantics_verified": False, "reference_eligible": False, "reference_accepted": False,
        "limitations": [
            "Only bound file identities and declared source-call arrays were checked; no target/GPU execution.",
            "Ledger coverage, actual forwarding, complete build provenance and observed runtime identities need independent review.",
            "Fallback failure/routing artifacts are hash-bound, not semantically approved by this checker.",
            "Compilation, state preservation, atlas/pixel/PCM repeatability and original scene identity remain unproven.",
            "T12 and coordinator review precede any restoration or full-reference acceptance.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--checkout-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--shared-root", type=Path, default=Path(os.environ.get("EIDOLON_ROOT", ".")))
    parser.add_argument("--data-root", type=Path, default=Path(os.environ.get("EIDOLON_DATA", "data")))
    args = parser.parse_args(argv)
    try:
        result = assess(args.manifest, {"checkout": args.checkout_root,
                                       "shared": args.shared_root, "data": args.data_root})
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "FAIL", "reference_accepted": False, "reason": str(error)}))
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
