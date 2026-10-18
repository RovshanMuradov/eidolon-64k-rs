#!/usr/bin/env python3
"""Build/pack one isolated shader experiment and report the WHOLE EXE size/hash.

measure.py BLOB [GL_NAMES_RS] --work NEW_BUILD_DIR --keep NEW_RESULT_DIR
Optional --packer/--nasm reuse explicit tools. Defaults build the tracked packer.
No expected acceptance hash is updated, and no GPU capture is performed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build  # noqa: E402


def record(data):
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('blob', type=Path)
    ap.add_argument('gl_names', type=Path, nargs='?')
    ap.add_argument('--work', type=Path, required=True)
    ap.add_argument('--keep', type=Path, required=True)
    ap.add_argument('--packer', type=Path)
    ap.add_argument('--nasm', type=Path)
    args = ap.parse_args()
    if args.keep.exists():
        ap.error('result directory already exists; choose a new experiment path')
    build.WORK = args.work.resolve()
    build.WORK.mkdir(parents=True, exist_ok=False)
    tree = build.stage()
    shutil.copyfile(args.blob, tree / 'src/data/graphics.cg29')
    if args.gl_names:
        shutil.copyfile(args.gl_names, tree / 'src/gl_names.rs')
    pe = build.build_pe(tree)
    packer = args.packer.resolve() if args.packer else build.build_packer(
        args.nasm.resolve() if args.nasm else build.build_nasm())
    packed = build.trim(build.pack(packer, build.prepare(pe)))
    manifest = dict(blob=record(args.blob.read_bytes()), unprepared_pe=record(pe),
                    whole_exe=record(packed), gpu_verified=False)
    # Publish only complete outputs, in a per-experiment directory.
    stage = build.WORK / 'result'
    stage.mkdir()
    (stage / 'unprepared.exe').write_bytes(pe)
    (stage / 'eidolon-size.exe').write_bytes(packed)
    (stage / 'measurement.json').write_text(json.dumps(manifest, indent=2) + '\n')
    args.keep.parent.mkdir(parents=True, exist_ok=True)
    stage.rename(args.keep)
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
