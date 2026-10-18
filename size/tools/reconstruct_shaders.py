#!/usr/bin/env python3
"""Reconstruct the frozen fo2 CG29 candidate; no optimizer/native cost tool needed.

python3 size/tools/reconstruct_shaders.py [--output FILE] [--check]
All data paths default relative to this repository, never a private worktree.
"""
import argparse
import hashlib
import json
from pathlib import Path

import cg29

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'size/shaders'
SHIPPING = ROOT / 'size/crate/src/data/graphics.cg29'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def reconstruct():
    manifest = json.loads((DATA / 'fo2-provenance.json').read_text())
    checkpoint = (DATA / 'checkpoint-tx.cg29').read_bytes()
    source = (DATA / 'fo2-source.json').read_bytes()
    if sha(checkpoint) != manifest['checkpoint']['sha256'] or sha(source) != manifest['source_sha256']:
        raise ValueError('checkpoint/source hash mismatch')
    if sha((DATA / 'fo2-renames.json').read_bytes()) != manifest['rename_map_sha256']:
        raise ValueError('rename map hash mismatch')
    tables, _, baseline_recipes = cg29.parse(checkpoint)
    doc = json.loads(source)
    fragments = [s.encode('latin1') for s in doc['fragments']]
    recipes = doc['recipes']
    if len(recipes) != len(baseline_recipes):
        raise ValueError('program count changed')
    if [sha(f) for f in fragments] != manifest['fragment_sha256']:
        raise ValueError('fragment mapping/hash mismatch')
    if recipes != manifest['recipes']:
        raise ValueError('recipe mapping changed')
    result = cg29.write(tables, fragments, recipes)
    decoded_tables, decoded_fragments, decoded_recipes = cg29.parse(result)
    if (tables, fragments, recipes) != (decoded_tables, decoded_fragments, decoded_recipes):
        raise ValueError('CG29 round trip changed tables/fragments/recipes')
    programs = [b''.join(fragments[i] for i in r) for r in recipes]
    if [sha(p) for p in programs] != manifest['program_sha256']:
        raise ValueError('reconstructed program hash mismatch')
    if sha(result) != manifest['candidate']['sha256'] or len(result) != manifest['candidate']['bytes']:
        raise ValueError('candidate hash/size mismatch')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=SHIPPING)
    ap.add_argument('--check', action='store_true', help='compare without writing')
    args = ap.parse_args()
    try:
        result = reconstruct()
        if args.check:
            if args.output.read_bytes() != result:
                raise ValueError('output is not the reconstructed candidate')
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(result)
        print(f'{len(result)} bytes; SHA-256 {sha(result)}; all 12 tables unchanged')
    except (OSError, ValueError, KeyError, IndexError) as e:
        ap.exit(1, f'FAIL: {e}\n')


if __name__ == '__main__':
    main()
