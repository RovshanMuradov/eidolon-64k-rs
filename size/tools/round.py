#!/usr/bin/env python3
"""Bounded, isolated research round: round.py IN EXPERIMENT --seed N [--evaluations 200].

The total proxy budget is divided across four passes. Each pass writes its own
immutable candidate directory. This is not used to reproduce the frozen fo2 data.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', type=Path)
    ap.add_argument('experiment', type=Path)
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--evaluations', type=int, default=200)
    args = ap.parse_args()
    if not 4 <= args.evaluations <= 200:
        ap.error('round budget must be in 4..200')
    args.experiment.mkdir(parents=True, exist_ok=False)
    (args.experiment / 'round.json').write_text(json.dumps(dict(seed=args.seed,
        evaluations=args.evaluations, workers=4, gpu_validated=False), indent=2) + '\n')
    scripts = ['permute', 'rename', 'itemorder', 'fragorder']
    current = args.source.resolve()
    for i, script in enumerate(scripts):
        out = (args.experiment / script).resolve()
        budget = args.evaluations // 4 + (i < args.evaluations % 4)
        env = dict(os.environ, EIDOLON_SHADER_MAX_EVALS=str(budget))
        with (args.experiment / (script + '.log')).open('x') as log:
            subprocess.run([sys.executable, str(Path(__file__).with_name(script + '.py')),
                            str(current), str(out), '--seed', str(args.seed), '--seconds', '600'],
                           env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        current = out
    print(current)


if __name__ == '__main__':
    main()
