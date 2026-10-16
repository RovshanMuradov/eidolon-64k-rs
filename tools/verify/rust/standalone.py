#!/usr/bin/env python3
"""Independently build/render merged production audio with file access closed."""
import argparse
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time

from conformance import CHECKOUT, ROOT, DATA, PIN, Native, checked, load, need, sha, exact_files, PCM_BYTES

AUDIO_PIN = "102f75784cdd5f8a91fde2e2e1f0205dc73c721f2dee108e38d240796ed519f5"
ANALYSIS_PIN = "ff3ffdff0acad90e4103a95652ed7c80262c251d4d44bcc78516802fca4070d2"
AUDIT_PIN = "7c1090f5d9db37ffda722579ad7e5b6b833a144222eedd2ac264cf05b45b9a86"


def chunks(raw, start, end):
    while start < end:
        need(start + 8 <= end, "short RIFF header")
        tag, size = struct.unpack_from("<4sI", raw, start)
        begin, finish = start + 8, start + 8 + size
        need(finish <= end, "RIFF extent")
        yield tag, begin, finish
        start = finish + (size & 1)
    need(start == end, "RIFF alignment")


def bank_waves(raw):
    need(raw[:4] == b"RIFF" and raw[8:12] == b"DLS ", "not DLS RIFF")
    need(struct.unpack_from("<I", raw, 4)[0] + 8 == len(raw), "DLS length")
    result = []
    for tag, a, b in chunks(raw, 12, len(raw)):
        if tag == b"LIST" and raw[a:a+4] == b"wvpl":
            for kind, c, d in chunks(raw, a+4, b):
                need(kind == b"LIST" and raw[c:c+4] == b"wave", "DLS wave list")
                payloads = [raw[e:f] for typ, e, f in chunks(raw, c+4, d) if typ == b"data"]
                need(len(payloads) == 1, "DLS wave payload count")
                result.append(payloads[0])
    need(len(result) == 495, "DLS wave coverage")
    return result


def closure(path):
    analysis = load(checked(CHECKOUT / "analysis/audio/manifest.json", ANALYSIS_PIN))
    audit = load(checked(CHECKOUT / "analysis/audio/audit.json", AUDIT_PIN))
    image = checked(DATA / analysis["inputs"]["postfix"]["path"], analysis["inputs"]["postfix"]["sha256"]).read_bytes()
    bank = checked(DATA / "reference/dependencies/gm.dls", analysis["inputs"]["dls"]["sha256"]).read_bytes()
    waves = bank_waves(bank)
    expected_ids = audit["event_closure"]["event_reachable_samples"]
    stream = io.BytesIO(Path(path).read_bytes())
    def take(n):
        raw = stream.read(n); need(len(raw) == n, "truncated embedded-data dump"); return raw
    def u32(): return struct.unpack("<I", take(4))[0]
    need(take(8) == b"EIDAUD01", "embedded-data magic")
    for expected in (image[0x37040:0x3edcf], image[0x3edf0:0x40c30]):
        need(u32() == len(expected) and take(len(expected)) == expected, "score/patch differs from native image")
    need(u32() == len(expected_ids) == 15, "embedded sample closure count")
    total = 0
    for expected_id in expected_ids:
        index, count = u32(), u32()
        need(index == expected_id and count*2 == len(waves[index]), "sample identity/extent")
        need(take(count*2) == waves[index], "sample bytes differ from pinned DLS")
        total += count*2
    source = checked(ROOT / ".tools/analysis/audio/64klang/Player/Player/SynthNode.cpp", analysis["source"]["files"]["SynthNode.cpp"]).read_text()
    body = source.split("short FORMANT_Coeff[FORMANT_NUM_COEFFS] =", 1)[1].split("{", 1)[1].split("}", 1)[0]
    body = re.sub(r"//[^\n]*", "", body)
    values = [int(x.strip()) for x in body.split(",") if x.strip()]
    need(len(values) == 375, "formant source extent")
    formants = struct.pack("<375h", *values)
    need(take(750) == formants and not stream.read(1), "formants/trailing embedded data")
    return dict(score_bytes=32143, patch_bytes=7744, sample_ids=expected_ids, instrument_pcm16_bytes=total,
                formant_entries=375, formant_basis="pinned recovered source; not a new native runtime observation",
                image_sha256=analysis["inputs"]["postfix"]["sha256"], bank_sha256=analysis["inputs"]["dls"]["sha256"],
                analysis_sha256=ANALYSIS_PIN, audit_sha256=AUDIT_PIN, dump_sha256=sha(path))


def run(directory):
    native = Native()
    producer = load(checked(CHECKOUT / "artifacts/rust/audio/standalone.json", AUDIO_PIN))
    need(set(producer["rust_files"]) == {str(p.relative_to(CHECKOUT)) for p in (CHECKOUT / "src/audio").glob("*.rs")}, "unbound audio source")
    inputs = dict(producer["rust_files"])
    inputs["tools/verify/rust/render.rs"] = sha(CHECKOUT / "tools/verify/rust/render.rs")
    directory.mkdir(parents=True, exist_ok=False)
    snapshot = directory / "source"
    for name, digest in inputs.items():
        source = checked(CHECKOUT / name, digest)
        target = snapshot / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target); checked(target, digest)
    scratch = directory / "tmp"; scratch.mkdir()
    empty = directory / "empty"; empty.mkdir()
    env = dict(os.environ, TMPDIR=str(scratch))
    rustc = subprocess.check_output(["rustc", "--version"], text=True).strip()
    binary = directory / "render"
    command = ["rustc", "--edition=2021", "-A", "dead_code", "-C", "opt-level=2", "-C", "target-feature=+sse4.1",
               "--emit=dep-info,link", "tools/verify/rust/render.rs", "-o", str(binary)]
    subprocess.run(command, cwd=snapshot, env=env, check=True)
    dependencies = (directory / "render.d").read_text().splitlines()[0].split(": ", 1)[1].split()
    actual = {str((snapshot / p).resolve().relative_to(snapshot)) for p in dependencies}
    need(actual == set(inputs), "compiler source closure differs")
    dynamic = subprocess.check_output(["readelf", "-d", str(binary)], text=True)
    libraries = re.findall(r"Shared library: \[(.*?)\]", dynamic)
    need(set(libraries) <= {"libgcc_s.so.1", "libc.so.6", "libm.so.6", "ld-linux-x86-64.so.2"}, "unexpected native/oracle linkage")
    assets = directory / "embedded.bin"
    subprocess.run([str(binary), "--assets", str(assets)], cwd=empty, check=True)
    embedded = closure(assets)
    pcm = directory / "pcm.f32le"
    started = time.monotonic()
    proc = subprocess.run([str(binary), "--render", str(pcm)], cwd=empty, env=env, check=True, capture_output=True, text=True, timeout=600)
    elapsed = time.monotonic() - started
    need(proc.stdout.strip() == "FULL_RENDER frames=19964544 bytes=159716352 file_inputs_denied=true mxcsr_restored=true poison_remaining=0" and not proc.stderr, "unexpected render outcome")
    exact_files(native.pcm, pcm, PCM_BYTES)
    for name, digest in inputs.items(): checked(snapshot / name, digest)
    return dict(schema="eidolon-independent-standalone-audio-1", status="EXACT_NATIVE_PCM", standalone_rust_synth=True,
                reference_accepted=True, production_accepted=False, reference_manifest_sha256=PIN, source_manifest_sha256=AUDIO_PIN,
                source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CHECKOUT, text=True).strip(),
                inputs=inputs, compiler_dependencies=sorted(actual), compile_command=command, rustc=rustc,
                binary=dict(path=str(binary.relative_to(DATA)), sha256=sha(binary), needed=libraries),
                output=dict(path=str(pcm.relative_to(DATA)), sha256=sha(pcm), bytes=PCM_BYTES),
                elapsed_seconds=elapsed, embedded=embedded, file_inputs_denied_during_render=True,
                invalid_size_no_write=True, poison_remaining=0, caller_mxcsr_restored=True,
                environment=dict(os="Linux", target="x86_64-unknown-linux-gnu", wine=None, gpu=None, driver=None, resolution=None),
                scope="Host production-entrypoint synthesis only; Windows shipped EXE remains unexecuted")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DATA / "verification/rust" / ("standalone-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")))
    parser.add_argument("--result", type=Path, default=CHECKOUT / "artifacts/verification/rust/standalone.json")
    args = parser.parse_args()
    result = run(args.directory)
    args.result.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))
