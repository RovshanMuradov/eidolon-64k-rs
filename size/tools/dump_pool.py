#!/usr/bin/env python3
"""Dump a CG29 blob's tables, fragments and recipes: dump_pool.py BLOB OUTDIR."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cg29  # noqa: E402

blob = Path(sys.argv[1]).read_bytes()
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
tables, frags, recipes = cg29.parse(blob)
assert cg29.write(tables, frags, recipes) == blob
for i, t in enumerate(tables):
    print(i, t['mode'], t['stride'], t['dec'], len(t['payload']))
print('fragments', len(frags), 'pool bytes', sum(len(f) + 1 for f in frags))
for i, f in enumerate(frags):
    (out / f'{i:02d}.glsl').write_bytes(f)
(out / 'recipes.json').write_text(json.dumps(recipes))
for i, r in enumerate(recipes):
    print('recipe', i, r)
print([len(f) for f in frags])
