#!/usr/bin/env python3
"""Audit the stopped B diagnostic and bind its first G1 failure for handoff.

This audits recorded observations and saved bytes, not instrumentation fidelity.
It never converts a failed/partial run into a reference or starts Windows code.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import zstandard


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    manifest_path = Path("artifacts/reference/proxy-b-g1-20261016.json")
    manifest = json.loads(manifest_path.read_text())
    data_root = Path(os.environ["EIDOLON_DATA"])
    data = data_root / "reference" / manifest["run_id"]
    assert manifest["status"] == "G1_failed" and manifest["launcher_exit"] == 125
    for path, digest in manifest["evidence"].items():
        assert sha(data_root / path) == digest, path
    # Preserve exactly the sources of the failing executable, outside Git builds.
    build = Path(manifest["build"]["build_directory"])
    snapshots = {}
    for path, digest in manifest["build"]["sources"].items():
        assert sha(path) == digest, path
        target = build / "source-snapshot" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        assert sha(target) == digest
        snapshots[str(target)] = digest
    for path, digest in manifest["build"]["outputs"].items():
        assert sha(build / path) == digest, path
    for backend in manifest["build"]["backends"].values():
        assert sha(backend["path"]) == backend["sha256"], backend["path"]
    for path, digest in manifest["bundle"].items():
        assert sha(path) == digest
    events = [json.loads(line) for line in (data / "backend.jsonl").read_text().splitlines()]
    ordered = [event for event in events if "seq" in event]
    assert [e["seq"] for e in ordered] == list(range(1, len(ordered) + 1))

    def one(name):
        matches = [e for e in events if e["event"] == name]
        assert len(matches) == 1, (name, len(matches))
        return matches[0]

    assert one("bootstrap_before_synth")["seq"] < one("hooks_installed")["seq"] < one("synth_launch")["seq"]
    assert one("synth_launch")["initial_tick"] == 1
    completion = one("synth_complete")
    extent = one("wave_write")
    assert completion["initial_tick"] == 1 and completion["final_tick"] == 19964545
    assert completion["tid"] == one("synth_thread")["synth_tid"] != one("hooks_installed")["tid"]
    assert int(completion["final_cursor"],16) - int(extent["base"],16) == extent["bytes"] == 159716352
    assert one("timeline_gate_enter")["completion_count"] == 0
    ids = {name: one(name)["seq"] for name in ("synth_complete", "readback_begin", "readback_end", "stability_check")}
    assert list(ids.values()) == sorted(set(ids.values()))
    pcm = data / "pcm.f32le"
    digest = sha(pcm)
    assert pcm.stat().st_size == extent["bytes"] and digest == one("readback_end")["sha256"] == one("stability_check")["sha256"]
    assert one("wave_open")["result"] == one("wave_prepare")["result"] == extent["result"] == 0
    assert one("epoch")["E"] == 1001
    startup = [e["value"] for e in events if e["event"] == "clock" and e["api"] == "GetTickCount"]
    assert startup == list(range(1001))
    positions = [e for e in events if e["event"] == "clock" and e["api"] == "waveOutGetPosition"]
    assert len(positions) == 1 and positions[0]["n"] == positions[0]["value"] == 0 and positions[0]["wType"] == 2
    assert not any(e["event"] in ("pre_present", "post_present", "planned_partial_stop") for e in events)
    failure = one("failure")
    assert failure["seq"] == ordered[-1]["seq"] and failure["reason"] == "GL_initial_error"

    evidence = Path("reports/evidence/capture")
    compressed = {}
    for source, name in ((data / "backend.jsonl", "proxy-b-g1-events.jsonl.zst"),
                         (data / "runner.log", "proxy-b-g1-runner.log.zst")):
        destination = evidence / name
        destination.write_bytes(zstandard.ZstdCompressor(level=19).compress(source.read_bytes()))
        assert zstandard.ZstdDecompressor().decompress(destination.read_bytes()) == source.read_bytes()
        compressed[str(destination)] = {"sha256":sha(destination), "uncompressed_sha256":sha(source),
                                        "uncompressed_bytes":source.stat().st_size}
    prefix = b"WINEPREFIX=/tmp/opencode/eidolon/T2/prefix"
    runtime = []
    for process in Path("/proc").glob("[0-9]*"):
        try:
            environment = (process / "environ").read_bytes().split(b"\0")
            name = (process / "comm").read_text().strip()
            command = (process / "cmdline").read_bytes().replace(b"\0",b" ").decode(errors="replace")
            if prefix in environment or name in {"gamescope","gamescopereaper"} or (name == "Xwayland" and " :0 " not in command):
                runtime.append({"pid":int(process.name), "name":name, "command":command})
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    sinks = json.loads(subprocess.check_output(["pactl","--format=json","list","sinks","short"],text=True))
    assert not runtime and not any(s["name"].startswith("eidolon_T2") for s in sinks)
    output = {
        "kind":"proxy-B-first-G1-failure-review", "reference_eligible":False,
        "manifest":str(manifest_path), "manifest_sha256":sha(manifest_path),
        "first_failure":failure, "gate":"G1e; G1c three-present requirement consequently unmet",
        "interpretation":"The readback precheck rejects a prior GL error OR an error from initial state queries. The numeric GL enum and which side failed were not recorded. Win32 error 183 is not a GL error enum. No causal attribution is established.",
        "clock_observed":{"startup_values":"0..1000", "epoch":1001, "positions":positions},
        "pcm_observed":{"submitted_bytes":extent["bytes"], "sample_frames":extent["bytes"]//8,
                        "initial_tick":1,"final_tick":completion["final_tick"],
                        "final_cursor_offset":extent["bytes"],"events":ids,"sha256":digest,
                        "tail_sample_frames":119544},
        "pixels_observed":0,"timeline_presents_observed":0,
        "gates":{"G1":"failed", "G2":"PCM observations audited; independent runtime review pending",
                 "G3":"not passed; no raw pixels", "G4":"not passed; only first zero cursor",
                 "G5":"no small capture to review", "G6":"not run"},
        "missing_G1_items":["second fresh-process three-present diagnostic", "full runtime export/ABI canary",
                            "all repeated clock/QPC/QPF paths", "live register/FP restoration checks beyond saved CONTEXT equality",
                            "GL state restoration", "corrupted-fingerprint control", "invalid-backend-path control"],
        "next":"Coordinator records D3 fallback A; no further B runtime attempted after first G1 failure.",
        "compressed_evidence":compressed,"source_snapshots":snapshots,
        "runtime_release":{"checked_utc":datetime.now(timezone.utc).isoformat(),"T2_runtime_processes":runtime,
                           "private_audio_sink_present":False},
    }
    destination = Path("artifacts/reference/proxy-b-g1-failure-review.json")
    destination.write_text(json.dumps(output,indent=2)+"\n")
    print(json.dumps({"audit":"PASS for saved failure evidence only", "first_failure":failure["reason"],
                      "frames":0,"pcm_bytes":pcm.stat().st_size,"runtime_processes":0,"review":str(destination)}))


if __name__ == "__main__":
    main()
