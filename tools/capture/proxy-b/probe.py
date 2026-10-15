#!/usr/bin/env python3
"""Fail-fast G1a backend feasibility canary; never labels this a reference."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--invalid-backend", action="store_true")
    args = parser.parse_args()
    assert args.run_id and all(c.isalnum() or c in "-_" for c in args.run_id)
    root = Path(os.environ["EIDOLON_ROOT"])
    data = Path(os.environ["EIDOLON_DATA"]) / "reference" / args.run_id
    data.mkdir(parents=True, exist_ok=False)
    subprocess.run(["python", "tools/capture/prepare-native.py"], check=True)
    build = Path(subprocess.check_output(["python", "tools/capture/proxy-b/build.py"], text=True).strip())
    build_manifest = json.loads((build / "build.json").read_text())
    stage = Path("/tmp/opencode/eidolon/T2/proxy-demo")
    stage.mkdir(exist_ok=True)
    original = json.loads(Path("artifacts/reference/wine-smoke-manifest.json").read_text())["input"]
    native = Path("/tmp/opencode/eidolon/T2/input") / original["exe"]
    assert sha(native) == original["exe_sha256"]
    for name in ("opengl32.dll", "winmm.dll", "canary.exe"):
        shutil.copyfile(build / name, stage / name)
        assert sha(stage / name) == build_manifest["outputs"][name]
    shutil.copyfile(native, stage / native.name)
    assert sha(stage / native.name) == original["exe_sha256"]
    dependency = json.loads(Path("artifacts/reference/dependencies/gm-dls.json").read_text())
    prefix = Path("/tmp/opencode/eidolon/T2/prefix")
    baseline = {str(p.relative_to(prefix)): sha(p)
                for p in [prefix / f for f in ("system.reg", "user.reg", "userdef.reg",
                          "drive_c/windows/system32/drivers/gm.dls", "drive_c/windows/syswow64/drivers/gm.dls")]}
    overrides = "opengl32,winmm=n,b;winemenubuilder.exe,mscoree,mshtml=d"
    env = dict(os.environ, AGENT="T2", WINE_TIMEOUT="300", WINE_W="1920", WINE_H="1080",
               WINEDLLOVERRIDES=overrides, WINEDEBUG="-all,+loaddll",
               EIDOLON_B_LOG="Z:" + str(data / "backend.jsonl"))
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("EIDOLON_B_BACKEND", None)
    if args.invalid_backend:
        env["EIDOLON_B_BACKEND"] = r"Z:\tmp\opencode\eidolon\T2\absent-backend\missing.dll"
    command = ["bash", "tools/run", "tools/wine-headless", str(stage / "canary.exe")]
    started = datetime.now(timezone.utc).isoformat()
    with (data / "runner.log").open("wb") as log:
        result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
    ended = datetime.now(timezone.utc).isoformat()
    events = [json.loads(line) for line in (data / "backend.jsonl").read_text().splitlines()] \
        if (data / "backend.jsonl").exists() else []
    success = (result.returncode == 0 and len(events) == 2 and
               {e["dll"] for e in events} == {"opengl32.dll", "winmm.dll"} and
               all(e["result"] == "distinct_backend" for e in events))
    manifest = {
        "kind": "proxy-B-G1a-backend-diagnostic", "run_id": args.run_id,
        "reference_eligible": False, "diagnostic_incomplete": True,
        "status": "backend_prerequisite_passed" if success else "G1_failed",
        "first_failed_check": None if success else "G1a: distinct unmodified backend loading",
        "scope": "Explicit post-loader canary beside unchanged demo copy; no demo execution or clock/capture claim.",
        "planned_negative_control": args.invalid_backend,
        "unrun_gates": ["G1a ABI/context/waveOut/demo", "G1b", "G1c", "G1d", "G1e", "G2", "G3", "G4", "G5", "G6"],
        "input": original, "dependency": dependency,
        "build": build_manifest,
        "bundle": {p: sha(p) for p in ("tools/run", "tools/wine-headless", "tools/capture/prepare-native.py")},
        "stage": str(stage), "prefix_baseline": baseline,
        "environment": {
            "os": platform.platform(), "arch": platform.machine(),
            "wine": subprocess.check_output(["wine", "--version"], text=True).strip(),
            "packages": subprocess.check_output(["pacman", "-Q", "wine", "gamescope", "nvidia-utils", "lib32-nvidia-utils"], text=True).splitlines(),
            "gpu": subprocess.check_output(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"], text=True).strip(),
            "display": {"kind": "gamescope-headless", "width": 1920, "height": 1080,
                        "launcher": "tools/wine-headless", "wine_virtual_desktop": False},
            "settings": {key: env[key] for key in ("AGENT", "WINE_TIMEOUT", "WINE_W", "WINE_H", "WINEDLLOVERRIDES", "WINEDEBUG", "EIDOLON_B_LOG")},
            "backend_override": env.get("EIDOLON_B_BACKEND"), "lc_all": "C", "tz": "UTC"},
        "reproduce": ["bash", "tools/run", "python", "tools/capture/proxy-b/probe.py", "--run-id", "<fresh-run-id>"] +
                     (["--invalid-backend"] if args.invalid_backend else []),
        "command": command, "started_utc": started, "finished_utc": ended,
        "launcher_exit": result.returncode,
        "runner_terminal": [line for line in (data / "runner.log").read_text(errors="replace").splitlines()
                            if line.startswith(("WINE_EXIT=", "TIMEOUT"))],
        "observations": events,
        "evidence": {str(p.relative_to(Path(os.environ["EIDOLON_DATA"]))): sha(p)
                     for p in sorted(data.iterdir()) if p.is_file()},
        "D2": "WINE_EXIT authoritative; post-native GAMESCOPE_EXIT=139 never changes G1 status.",
    }
    output = Path("artifacts/reference") / f"{args.run_id}.json"
    output.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"manifest": str(output), "status": manifest["status"],
                      "exit": result.returncode, "results": [e["result"] for e in events]}))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
