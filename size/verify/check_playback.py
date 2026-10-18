#!/usr/bin/env python3
"""Offline negative controls for paired playback reports; never launches a target."""
import argparse
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace

from playback import compare
from verify import ROOT, load, sha, write


def run(args):
    real = SimpleNamespace(baseline=args.baseline, candidate=args.candidate, media=args.media, console=None)
    result = compare(real)
    results = ['real serialized pair and full-media identity accepted']
    scratch = ROOT / '.build/playback-contracts'
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as folder:
        folder = Path(folder)
        fixtures = {name: load(getattr(real, name)) for name in ('baseline', 'candidate', 'media')}
        for label in ('prefix mismatch', 'full-media identity mismatch', 'failed playback closure', 'surviving supervisor'):
            altered = deepcopy(fixtures)
            if label == 'prefix mismatch':
                altered['candidate']['prefix_seed_sha256']['system.reg'] = '0' * 64
            elif label == 'full-media identity mismatch':
                altered['media']['candidate_sha256'] = '0' * 64
            elif label == 'failed playback closure':
                altered['candidate']['status'] = 'FAIL'
                altered['candidate']['failures'] = ['Wine/Gamescope closure failed']
            else:
                altered['candidate']['cleanup']['supervisor_exists'] = True
            for name, content in altered.items():
                write(folder / (name + '.json'), content)
            fake = SimpleNamespace(**{name: folder / (name + '.json') for name in altered}, console=None)
            try:
                compare(fake)
            except ValueError:
                results.append(label + ' rejected')
            else:
                raise ValueError('false acceptance: ' + label)
    return dict(status='OFFLINE_PLAYBACK_CORRUPTION_CONTROLS_PASS', candidate_sha256=result['candidate_sha256'],
                checks=len(results), results=results, checker_sha256=sha(__file__), production_accepted=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'candidate', 'media', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = run(args)
    write(args.output, result)
    print(f"{result['status']}: {result['checks']} checks")
