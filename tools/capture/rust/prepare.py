#!/usr/bin/env python3
"""Bind an immutable production PE and cross-build capture helper; never launch it."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "verify/rust"))
from conformance import CHECKOUT, DATA, PIN, Native, checked, need, sha, pe_identity, load, ref


def export_rva(path, symbol):
    raw = Path(path).read_bytes(); pe = struct.unpack_from("<I", raw, 60)[0]
    count = struct.unpack_from("<H", raw, pe+6)[0]
    optsize = struct.unpack_from("<H", raw, pe+20)[0]; opt = pe+24
    sections = [struct.unpack_from("<4I", raw, opt+optsize+40*i+8) for i in range(count)]
    def offset(address):
        for _, va, size, ptr in sections:
            if va <= address < va+size: return ptr+address-va
        raise ValueError("unmapped export RVA")
    address, size = struct.unpack_from("<II", raw, opt+96)
    need(address and size, "missing marker export table")
    table = offset(address)
    functions, names, ordinals = struct.unpack_from("<3I", raw, table+28)
    total = struct.unpack_from("<I", raw, table+24)[0]
    for i in range(total):
        name = offset(struct.unpack_from("<I", raw, offset(names)+i*4)[0])
        end = raw.index(b"\0", name)
        if raw[name:end].decode("ascii") == symbol:
            ordinal = struct.unpack_from("<H", raw, offset(ordinals)+2*i)[0]
            value = struct.unpack_from("<I", raw, offset(functions)+4*ordinal)[0]
            need(not address <= value < address+size, "forwarded marker export")
            return value
    raise ValueError("missing marker export")


def prepare(commit, directory):
    need(len(commit) == 40 and all(x in "0123456789abcdef" for x in commit), "full immutable commit required")
    def blob(path): return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=CHECKOUT)
    pointer_raw = blob("artifacts/rust/engine/candidate.json"); pointer = json.loads(pointer_raw)
    bundle = Path(pointer["directory"])
    publication = load(checked(bundle / "candidate.json", pointer["manifest_sha256"]))
    need(publication["source_commit"] == pointer["source_commit"] and
         publication["executable_sha256"] == pointer["executable_sha256"], "candidate publication identity")
    for name, item in publication["files"].items():
        need(item["path"] == name and Path(name).name == name,"bundle path")
        entry = checked(ref.payload_path(bundle,name),item["sha256"])
        need(entry.stat().st_size == item["bytes"],"bundle file extent")
    inventory = load(bundle / "source-inventory.json")
    with tarfile.open(bundle / "source.tar") as archive:
        members = archive.getmembers()
        need(len(members) == len(inventory) and {m.name for m in members} == set(inventory),"source archive coverage")
        for member in members:
            need(member.isfile(),"non-file source archive entry")
            content = archive.extractfile(member).read()
            need(len(content) == inventory[member.name]["bytes"] and
                 hashlib.sha256(content).hexdigest() == inventory[member.name]["sha256"],"source archive identity")
    raw = (bundle / "build.json").read_bytes()
    need(raw == blob("artifacts/rust/engine/build.json"),"published/committed build inventory differs")
    build = json.loads(raw)
    candidate = build["runtime_candidate"]
    need(candidate["synth_integrated"] is True and candidate["independent_build_equal"] is True, "unintegrated/unreproduced candidate")
    executable = checked(bundle / "eidolon-runtime.exe", candidate["sha256"])
    identity = pe_identity(executable)
    need(identity["imports"] == candidate["imports"], "candidate import inventory")
    native = Native()
    directory.mkdir(parents=True, exist_ok=False)
    source = directory / "source"; source.mkdir()
    published = directory / "bundle"; published.mkdir()
    for name in (*publication["files"], "candidate.json"):
        shutil.copyfile(bundle / name, published / name)
    (directory / "candidate-pointer.json").write_bytes(pointer_raw)
    inputs = dict(build["inputs"])
    assets = json.loads(blob("artifacts/rust/engine/assets.json"))
    inputs.update({a["path"]: a["sha256"] for a in assets["outputs"]})
    for path, digest in inputs.items():
        content = blob(path)
        need(hashlib.sha256(content).hexdigest() == digest, f"unbound candidate source: {path}")
        target = source / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
    for item in assets["inputs"]:
        recovered = checked(DATA / "analysis/graphics" / item["path"], item["sha256"])
        target = source / "recovery" / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(recovered, target)
    for path in ("capture.c", "inject.js"):
        shutil.copyfile(CHECKOUT / "tools/capture/rust" / path, directory / path)
    shutil.copyfile(CHECKOUT / "tools/capture/rust/prepare.py", directory / "prepare.py")
    for name in ("runtime_events.py", "conformance.py"):
        shutil.copyfile(CHECKOUT / "tools/verify/rust" / name, directory / name)
    target = directory / "eidolon-runtime.exe"; shutil.copyfile(executable, target); checked(target, candidate["sha256"])
    (directory / "build.json").write_bytes(raw)
    helper = directory / "capture.dll"
    command = ["i686-w64-mingw32-gcc", "-std=c11", "-O2", "-msse2", "-Wall", "-Wextra", "-Werror", "-shared",
               "-Wl,--no-insert-timestamp", str(directory / "capture.c"), "-lopengl32", "-ladvapi32", "-o", str(helper)]
    subprocess.run(command, check=True)
    subprocess.run(["node", "--check", str(directory / "inject.js")], check=True)
    for name in ("capture_init", "capture_event", "capture_cursor"): export_rva(helper, name)
    retained = [r["n"] for r in native.frames if "raw_zst" in r]
    runtime = directory / "runtime"; runtime.mkdir()
    def win(path): return "Z:" + str(path).replace("/", "\\")
    config = dict(helper=win(helper), output=win(runtime), module=target.name,
                  markerRva=export_rva(target, "eidolon_runtime_event"), retained=retained)
    script = directory / "armed.js"
    script.write_text("globalThis.EIDOLON_CAPTURE = " + json.dumps(config) + ";\n" + (directory / "inject.js").read_text())
    # Account actual existing bytes plus worst-case uncompressed sparse runtime output.
    present = sum(p.stat().st_size for p in DATA.rglob("*") if p.is_file())
    reserve = len(retained)*8294400 + 159716352 + 40000000
    need(present+reserve < 30000000000, "capture reservation would exceed 30GB")
    files = {str(p.relative_to(directory)): sha(p) for p in directory.rglob("*") if p.is_file()}
    result = dict(schema="eidolon-rust-capture-request-1", status="PREPARED_NOT_EXECUTED", candidate_commit=commit,
                  production_source_commit=pointer["source_commit"], candidate_bundle_manifest_sha256=pointer["manifest_sha256"],
                  reference_manifest_sha256=PIN, reference_accepted=True, production_accepted=False,
                  executable=dict(path=target.name, sha256=sha(target)), identity=identity, files=files,
                  command=[win(target), "--play"], mode="play-controlled-sample-cursor", marker=config,
                  expected_environment=native.manifest["conditions"]["environment"], observed_environment=None,
                  helper_compile_command=command,
                  tools=dict(gcc=subprocess.check_output(["i686-w64-mingw32-gcc","--version"],text=True).splitlines()[0],
                             node=subprocess.check_output(["node","--version"],text=True).strip()),
                  target_executed=False, storage=dict(existing_bytes=present,reserved_bytes=reserve,limit_bytes=30000000000),
                  pending=["authorized suspended-before-main injection/runner integration", "live hook ABI/FP/restoration controls",
                           "actual executable pre/post identity and process-exit envelope", "full frames/PCM/runtime comparison"])
    (directory / "request.json").write_text(json.dumps(result, indent=2)+"\n")
    template=dict(schema="eidolon-rust-runtime-envelope-1",status="UNEXECUTED",
                  request=dict(path="request.json",sha256=sha(directory / "request.json")),
                  events=None,pcm=None,process=None)
    (directory / "runtime-envelope.template.json").write_text(json.dumps(template,indent=2)+"\n")
    return dict(path=str((directory / "request.json").relative_to(DATA)), sha256=sha(directory / "request.json"),
                candidate_sha256=sha(target), candidate_commit=commit, marker_rva=config["markerRva"], helper_sha256=sha(helper),
                status=result["status"], target_executed=False, production_accepted=False, storage=result["storage"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--result", type=Path, default=CHECKOUT / "artifacts/verification/rust/capture.json")
    args = parser.parse_args()
    result = prepare(args.commit, args.directory)
    args.result.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result))
