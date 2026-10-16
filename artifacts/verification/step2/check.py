#!/usr/bin/env python3
"""Repeat the step-2 checks with all generated data isolated in T21's zone.

Run through tools/run from this worktree. Run recovery first, then other modes.
Upstream source/manifest pins remain authoritative; no network or Windows runs.
"""
import argparse
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("recovery", "graphics", "packing", "audio", "closed", "decoder", "kernels"))
    args = parser.parse_args()
    shared = Path(os.environ["EIDOLON_DATA"])
    scratch = shared / "verification/step2"
    scratch.mkdir(parents=True, exist_ok=True)
    # Existing evidence is only read; generated analysis is private to T21.
    for name in ("reverse", "reference"):
        link = scratch / name
        if not link.exists():
            link.symlink_to(shared / name, target_is_directory=True)
        assert link.resolve() == (shared / name).resolve()
    temporary = scratch / "tmp"
    temporary.mkdir(exist_ok=True)
    os.environ.update(EIDOLON_DATA=str(scratch), TMPDIR=str(temporary), PYTHONDONTWRITEBYTECODE="1")
    sys.dont_write_bytecode = True
    commands = {
        "recovery": [("tools/analysis/audio/recover.py", [])],
        "graphics": [("tools/analysis/graphics/extract.py", []),
                     ("tools/analysis/graphics/timeline.py", ["--verify"]),
                     ("tools/analysis/graphics/saved_state.py", []),
                     ("tools/verify/review_d12.py", [])],
        "packing": [("tools/analysis/packing/measure.py", [])],
        "audio": [("tools/analysis/audio/source_check.py", ["--frames", "19964544"])],
        "closed": [("tools/analysis/audio/source_check.py", ["--frames", "19964544", "--closed-bank"])],
        "decoder": [("tools/analysis/audio/decoder_cost.py", [])],
        "kernels": [("tools/analysis/audio/kernel_inventory.py", [])],
    }[args.mode]
    for script, options in commands:
        print("CHECK", script, *options, flush=True)
        sys.argv = [script, *options]
        sys.path.insert(0, str(Path(script).parent.resolve()))
        if script == "tools/verify/review_d12.py":
            # The read-only reviewer rejects symlinks escaping its data root.
            subprocess.run([sys.executable, script], check=True,
                           env={**os.environ, "EIDOLON_DATA": str(shared)})
        elif args.mode == "kernels":
            # This owner script has no output switch. Redirect only its final
            # manifest write; verify the resulting inventory against its pin.
            source = Path(script).read_text()
            old = "Path('analysis/audio/kernels.json').write_text"
            assert source.count(old) == 1
            source = source.replace(old, "Path(os.environ['EIDOLON_DATA'] + '/kernels.json').write_text")
            exec(compile(source, script, "exec"), {"__name__": "__main__", "__file__": str(Path(script).resolve())})
            assert json.loads((scratch / "kernels.json").read_text()) == json.loads(Path("analysis/audio/kernels.json").read_text())
        else:
            runpy.run_path(script, run_name="__main__")
    if args.mode == "recovery":
        fresh = json.loads((scratch / "analysis/audio/T19/summary.json").read_text())
        assert fresh == json.loads(Path("analysis/audio/manifest.json").read_text())
    if args.mode in ("audio", "closed"):
        folder = "source-player-closed" if args.mode == "closed" else "source-player"
        fresh = json.loads((scratch / f"analysis/audio/T19/{folder}/comparison-19964544.json").read_text())
        pinned = json.loads(Path("analysis/audio/source-check" + ("-closed" if args.mode == "closed" else "") + ".json").read_text())
        assert fresh["equal"] and fresh["first_mismatch_byte"] is None
        for key in ("frames", "actual_sha256", "reference_full_sha256", "coverage", "build_files", "binary_sha256", "bank_transformation"):
            assert fresh[key] == pinned[key], key
        raw = Path(fresh["run_command"][4]).read_bytes()
        altered = bytearray(raw)
        altered[len(raw) // 2] ^= 1
        assert raw != altered and raw != raw[:-8] and raw != raw[8:] + bytes(8)
    if args.mode == "decoder":
        fresh = json.loads((scratch / "analysis/audio/T19/decoder/summary.json").read_text())
        pinned = json.loads(Path("analysis/audio/decoder-cost.json").read_text())
        assert fresh["source"] == pinned["source"]
        for name, result in fresh["results"].items():
            for key in ("input_sha256", "lzma_alone_bytes", "pe_bytes", "pe_sha256", "sample_indices", "sample_pcm_bytes", "sections", "imports", "host_decode_byte_equality", "pe_executed"):
                assert result[key] == pinned["results"][name][key], (name, key)
    print("T21_PASS", args.mode, flush=True)


if __name__ == "__main__":
    main()
