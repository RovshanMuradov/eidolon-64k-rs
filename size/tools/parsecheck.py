#!/usr/bin/env python3
"""List pool functions that gparse cannot parse: parsecheck.py DIR."""
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import glsl  # noqa: E402
import gparse  # noqa: E402
import lexmin  # noqa: E402
import minify  # noqa: E402

frags, recipes = minify.load(sys.argv[1])
structs = set()
for f in frags:
    structs |= set(re.findall(r'\bstruct\s+(\w+)', f))
bad = total = 0
for fi, f in enumerate(frags):
    for kind, text in glsl.items(f):
        if kind != 'func':
            continue
        total += 1
        toks = lexmin.sig(text)
        start = next(i for i, (t, _, _) in enumerate(toks) if t == '{')
        p = gparse.Parser([t for t, _, _ in toks[start:]], structs)
        try:
            p.block()
            if p.i != len(toks) - start:
                raise gparse.Fail('trailing')
        except gparse.Fail as e:
            bad += 1
            print(fi, len(text), str(e)[:60], ' '.join(t for t, _, _ in toks[start + max(0, p.i - 6):start + p.i + 4]))
print(bad, 'of', total)
