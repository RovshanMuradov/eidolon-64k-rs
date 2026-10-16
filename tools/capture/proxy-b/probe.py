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
    parser.add_argument("--entry-probe", action="store_true")
    parser.add_argument("--capture-probe", action="store_true")
    parser.add_argument("--frames", type=int, default=3)
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
    env.pop("EIDOLON_B_BOOTSTRAP", None)
    if args.entry_probe:
        env["EIDOLON_B_BOOTSTRAP"] = "entry-probe"
    if args.capture_probe:
        assert not args.entry_probe and not args.invalid_backend
        env["EIDOLON_B_BOOTSTRAP"] = "capture-probe"
        env["EIDOLON_B_OUTPUT"] = "Z:" + str(data)
        env["EIDOLON_B_FRAMES"] = str(args.frames)
    if args.invalid_backend:
        env["EIDOLON_B_BACKEND"] = r"Z:\tmp\opencode\eidolon\T2\absent-backend\missing.dll"
    command = ["bash", "tools/run", "tools/wine-headless",
               str(stage / (original["exe"] if args.entry_probe or args.capture_probe else "canary.exe"))]
    started = datetime.now(timezone.utc).isoformat()
    sink_module = None
    if args.capture_probe:
        sink_module = subprocess.check_output(["pactl", "load-module", "module-null-sink",
                                              "sink_name=eidolon_T2_proxy", "rate=44100", "channels=2"], text=True).strip()
        env["PULSE_SINK"] = "eidolon_T2_proxy"
    try:
        with (data / "runner.log").open("wb") as log:
            result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
    finally:
        if sink_module:
            subprocess.run(["pactl", "unload-module", sink_module], check=True)
    ended = datetime.now(timezone.utc).isoformat()
    events = [json.loads(line) for line in (data / "backend.jsonl").read_text().splitlines()] \
        if (data / "backend.jsonl").exists() else []
    success = (result.returncode == 0 and len(events) == 2 and
               {e["dll"] for e in events} == {"opengl32.dll", "winmm.dll"} and
               all(e["result"] == "distinct_backend" for e in events))
    if args.entry_probe:
        success = result.returncode == 0 and len(events) == 1 and events[0]["result"] == "post_fixup_entry_reached_planned_stop"
    if args.capture_probe:
        success = result.returncode == 0 and any(e["event"] == "planned_partial_stop" for e in events)
    manifest = {
        "kind": "proxy-B-G1-capture-diagnostic" if args.capture_probe else ("proxy-B-G1b-entry-diagnostic" if args.entry_probe else "proxy-B-G1a-backend-diagnostic"), "run_id": args.run_id,
        "reference_eligible": False, "diagnostic_incomplete": True,
        "status": "prerequisite_passed" if success else "G1_failed",
        "first_failed_check": None if success else ("G1: " + next((e["reason"] for e in events if e["event"] == "failure"), "native capture did not reach planned stop") if args.capture_probe else ("G1b: safe post-fixup entry rendezvous" if args.entry_probe else "G1a: distinct unmodified backend loading")),
        "scope": "Native three-frame controlled capture probe; remaining G1 items require review." if args.capture_probe else ("Native demo entry rendezvous with planned stop before synthesis." if args.entry_probe else "Explicit post-loader canary beside unchanged demo copy; no demo execution or clock/capture claim."),
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
            "backend_override": env.get("EIDOLON_B_BACKEND"), "bootstrap_mode": env.get("EIDOLON_B_BOOTSTRAP"),
            "frames": args.frames if args.capture_probe else None, "output": env.get("EIDOLON_B_OUTPUT"),
            "pulse_sink": env.get("PULSE_SINK"), "lc_all": "C", "tz": "UTC"},
        "reproduce": ["bash", "tools/run", "python", "tools/capture/proxy-b/probe.py", "--run-id", "<fresh-run-id>"] +
                     (["--invalid-backend"] if args.invalid_backend else []) + (["--entry-probe"] if args.entry_probe else []) +
                     (["--capture-probe", "--frames", str(args.frames)] if args.capture_probe else []),
        "command": command, "started_utc": started, "finished_utc": ended,
        "launcher_exit": result.returncode,
        "runner_terminal": [line for line in (data / "runner.log").read_text(errors="replace").splitlines()
                            if line.startswith(("WINE_EXIT=", "TIMEOUT"))],
        "observations": events if not args.capture_probe else [e for e in events if e["event"] not in ("lookup", "clock")],
        "evidence": {str(p.relative_to(Path(os.environ["EIDOLON_DATA"]))): sha(p)
                     for p in sorted(data.iterdir()) if p.is_file()},
        "D2": "WINE_EXIT authoritative; post-native GAMESCOPE_EXIT=139 never changes G1 status.",
    }
    output = Path("artifacts/reference") / f"{args.run_id}.json"
    output.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"manifest": str(output), "status": manifest["status"],
                      "exit": result.returncode, "results": [e.get("result", e.get("reason", e["event"])) for e in events if e["event"] not in ("lookup", "clock")]}))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
