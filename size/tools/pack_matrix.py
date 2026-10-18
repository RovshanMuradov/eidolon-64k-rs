#!/usr/bin/env python3
"""Measure complete delivered EXEs for a finite PE/packer matrix; never promotes a candidate.

Example: pack_matrix.py --input combined=unprepared.exe --packer tuned=kkrunchy.exe
                       --work-dir .build/matrix
Inputs are unprepared linker outputs. Each result preserves that input, the prepared image,
the delivered EXE and identities of the input and packer. Packing is serialized in one private
Wine prefix. Existing result directories are refused so capture inputs cannot be overwritten.
"""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build


def named_path(value):
    name, separator, path = value.partition('=')
    if not separator or not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise argparse.ArgumentTypeError('expected a simple NAME=PATH')
    path = Path(path).resolve()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f'not a file: {path}')
    return name, path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=named_path, action='append', required=True)
    parser.add_argument('--packer', type=named_path, action='append', required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    args = parser.parse_args()
    for group in (args.input, args.packer):
        if len({name for name, _ in group}) != len(group):
            parser.error('names must be unique within each input or packer group')
    work = args.work_dir.resolve()
    if work.exists():
        parser.error(f'choose a fresh work directory: {work}')
    # Load and pin every input before running any external tool.
    inputs = {name: (path, path.read_bytes()) for name, path in args.input}
    packers = {name: (path, build.file_identity(path)) for name, path in args.packer}
    work.mkdir(parents=True)
    prefix = work / 'wine-prefix'
    prefix.mkdir()
    results = []
    for name, (path, original) in inputs.items():
        for model, (packer, identity) in packers.items():
            trial = work / name / model
            trial.mkdir(parents=True)
            (trial / 'wine-prefix').symlink_to(prefix, target_is_directory=True)
            # Wine initializes the common private prefix on its first start.
            build.WORK = trial
            (trial / 'unprepared.exe').write_bytes(original)
            if build.file_identity(packer) != identity:
                raise SystemExit(f'packer changed during the matrix: {packer}')
            delivered = build.trim(build.pack(packer, build.prepare(original)))
            exe = trial / 'eidolon-runtime.exe'
            exe.write_bytes(delivered)
            row = {
                'input': name, 'model': model, 'status': 'CANDIDATE',
                'media_capture_performed': False,
                'input_path': str(path), 'packer_path': str(packer),
                'unprepared': build.file_identity(trial / 'unprepared.exe'),
                'prepared': build.file_identity(trial / 'input.exe'),
                'packer': identity, 'delivered': build.file_identity(exe),
                'directory': str(trial.relative_to(work)),
            }
            (trial / 'candidate.json').write_text(json.dumps(row, indent=2) + '\n')
            results.append(row)
            (work / 'matrix.json').write_text(json.dumps(results, indent=2) + '\n')
            print(f'{name}/{model}: {len(delivered)} bytes, {build.sha(delivered)}', flush=True)
    print(f'{len(results)} candidates recorded in {work / "matrix.json"}')


if __name__ == '__main__':
    main()
