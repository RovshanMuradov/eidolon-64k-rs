#!/usr/bin/env python3
"""One search round on a fragment dir: round.py IN TAG SECONDS_SCALE -> permute, rename, item order, fragment order."""
import subprocess
import sys
from pathlib import Path

T = Path(__file__).resolve().parent
src, tag, scale = sys.argv[1], sys.argv[2], float(sys.argv[3])
steps = [('permute.py', 'pm', 1500), ('rename.py', 'rn', 1500), ('itemorder.py', 'io', 400), ('fragorder.py', 'fo', 600)]
cur = src
for script, short, sec in steps:
    out = f'{short}{tag}'
    with open(f'{out}.log', 'w') as log:
        subprocess.run([sys.executable, str(T / script), cur, out, '--seconds', str(int(sec * scale)), '--seed', tag],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    print(out, open(f'{out}.log').read().strip().splitlines()[-1], flush=True)
    cur = out
