#!/usr/bin/env python3
"""Recheck retained T22/T23 diagnostics against native data, without importing port code."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from conformance import (ROOT, DATA, PIN, Native, checked, load, need, sha, pe_identity,
                         compare_probe, compare_shaders, exact_files, PCM_BYTES)

ENGINE_PIN = "70fb4c6663c5036cb435effc32dec9b5d97af5814e6c7cf7e8488b09b9c799e9"
AUDIO_PIN = "eee595326cc4cc5d02008c2bbb8fddc91a6bbaa93e08ca013b687ce011f6c5b6"
ENGINE_COMMIT = "7c643ad76f8f9f6e927d8f10be6ba3049231679e"
AUDIO_COMMIT = "9d94fd96f91aae795154b282f03baf1d35750a5c"


def committed(root, commit, path, digest):
    raw = subprocess.check_output(["git", "-C", str(root), "show", f"{commit}:{path}"])
    need(hashlib.sha256(raw).hexdigest() == digest, f"committed input differs: {path}")
    return raw


def probes(output):
    engine_root = ROOT / ".worktrees/T22"
    engine = json.loads(committed(engine_root, ENGINE_COMMIT, "artifacts/rust/engine/build.json", ENGINE_PIN))
    for path, digest in engine["inputs"].items():
        committed(engine_root, ENGINE_COMMIT, path, digest)
    host = checked(DATA / "builds/T22/host/x86_64-unknown-linux-gnu/release/eidolon-engine", engine["host_probe_sha256"])
    with host.open("rb") as f:
        header = f.read(20)
    need(header[:6] == b"\x7fELF\x02\x01" and header[18:20] == b"\x3e\x00", "only pinned Linux x86_64 host probe may execute")
    output.mkdir(parents=True, exist_ok=True)
    paths = {}
    for kind in ("raw", "state", "shader"):
        path = output / f"T22-{kind}.bin"
        with path.open("wb") as f:
            subprocess.run([str(host), f"--{kind}-stream"], stdout=f, check=True, timeout=120)
        paths[kind] = path
    return engine, paths


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
    pe = pe_identity(checked(DATA / engine["pe"]["path"], engine["pe"]["sha256"]))
    need(pe["imports"] == engine["pe"]["imports"], "PE import inventory differs")
    audio_root = ROOT / ".worktrees/T23"
    audio = json.loads(committed(audio_root, AUDIO_COMMIT, "artifacts/rust/audio/slices.json", AUDIO_PIN))
    need(audio["kind"] == "hybrid-source-oracle-diagnostic" and audio["standalone_rust_synth"] is False,
         "hybrid scope changed")
    for path, digest in audio["rust_files"].items():
        committed(audio_root, AUDIO_COMMIT, path, digest)
    pcm = checked(Path(audio["output"]), audio["output_sha256"])
    checks["hybrid_pcm"] = dict(bytes=exact_files(native.pcm, pcm, PCM_BYTES),
                                status="EXACT_NATIVE_PCM", standalone_rust_synth=False)
    return dict(schema="eidolon-rust-independent-diagnostics-1", status="PARTIAL", reference_sha256=PIN,
                engine_manifest_sha256=ENGINE_PIN, audio_manifest_sha256=AUDIO_PIN,
                engine_commit=ENGINE_COMMIT, audio_commit=AUDIO_COMMIT,
                probes={k: {"path": str(p.relative_to(DATA)), "sha256": sha(p)} for k, p in paths.items()},
                checks=checks, pe=pe, reference_accepted=False, production_accepted=False,
                runtime=dict(gpu=None, driver=None, wine=None, resolution=None, target_executed=False),
                remaining=["final G6", "production audiovisual EXE", "native post-update physics/uniform vectors",
                           "standalone Rust PCM", "production runtime evidence and performance baseline"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DATA / "verification/rust/T24")
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    result = run(args.output)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.result:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(text)
    print(text, end="")
    sys.exit(int(any(c.get("status") == "FAIL" for c in result["checks"].values())))
