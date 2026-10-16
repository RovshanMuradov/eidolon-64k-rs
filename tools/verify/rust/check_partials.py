#!/usr/bin/env python3
"""Replay retained, hash-pinned CPU streams; current standalone audio has its own checker."""
import argparse
import json
from pathlib import Path
import shutil
import sys

from conformance import (CHECKOUT, DATA, PIN, Native, checked, load, need, sha,
                         compare_probe, compare_shaders)

ENGINE_PIN = "70fb4c6663c5036cb435effc32dec9b5d97af5814e6c7cf7e8488b09b9c799e9"
ENGINE_COMMIT = "7c643ad76f8f9f6e927d8f10be6ba3049231679e"


def probes(output):
    retained = load(checked(CHECKOUT / "artifacts/verification/rust/partials.json",
                           "92ec94a5ef8c2e7ef53dcc0a24ece2090dabf129f0399bb3af288f61c9f1b66d"))
    output.mkdir(parents=True, exist_ok=True)
    paths = {}
    for kind in ("raw", "state", "shader"):
        path = output / f"T22-{kind}.bin"
        original = checked(DATA / retained["probes"][kind]["path"], retained["probes"][kind]["sha256"])
        if path.resolve() != original.resolve(): shutil.copyfile(original, path)
        paths[kind] = path
    return retained, paths


def run(output):
    native = Native()
    engine, paths = probes(output)
    times = native.times()
    checks = {}
    for kind in ("raw", "state", "shader"):
        try:
            result = compare_shaders(native, paths[kind]) if kind == "shader" else compare_probe(native, paths[kind], times)
            checks[kind] = dict(status="MATCH_WITHIN_DECLARED_COVERAGE", **result)
        except ValueError as exc:
            checks[kind] = dict(status="FAIL", reason=str(exc))
    return dict(schema="eidolon-rust-independent-diagnostics-1", status="PARTIAL", reference_sha256=PIN,
                engine_manifest_sha256=ENGINE_PIN, engine_commit=ENGINE_COMMIT,
                probes={k: {"path": str(p.relative_to(DATA)), "sha256": sha(p)} for k, p in paths.items()},
                checks=checks, reference_accepted=True, production_accepted=False,
                runtime=dict(gpu=None, driver=None, wine=None, resolution=None, target_executed=False),
                remaining=["native post-update physics/uniform vectors", "production runtime evidence and performance baseline"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DATA / "verification/rust/T24")
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    result = run(args.output)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.result:
        need(args.result.resolve() != (CHECKOUT / "artifacts/verification/rust/partials.json").resolve(), "retained manifest is immutable")
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(text)
    print(text, end="")
    sys.exit(int(any(c.get("status") == "FAIL" for c in result["checks"].values())))
