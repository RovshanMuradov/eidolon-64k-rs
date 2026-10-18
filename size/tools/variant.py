#!/usr/bin/env python3
"""Rewrite a CG29 blob's shader pool from a directory of fragments: variant.py BLOB FRAGDIR OUT.

FRAGDIR holds NN.glsl (one per fragment, same count) and optionally recipes.json."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cg29  # noqa: E402

tables, frags, recipes = cg29.parse(Path(sys.argv[1]).read_bytes())
d = Path(sys.argv[2])
files = sorted(d.glob('[0-9][0-9].glsl'))
frags = [f.read_bytes() for f in files]
if (d / 'recipes.json').exists():
    recipes = json.loads((d / 'recipes.json').read_text())
blob = cg29.write(tables, frags, recipes)
Path(sys.argv[3]).write_bytes(blob)
print(len(blob), 'pool', sum(len(f) + 1 for f in frags))
