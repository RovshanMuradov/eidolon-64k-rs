#!/usr/bin/env python3
"""Hill-climb the order of fragments in the CG29 pool (recipes are re-indexed; programs unchanged).

fragorder.py IN OUT [--seconds S] [--seed N]. Cost: native kkrunchy model of the whole pool."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import random
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import minify  # noqa: E402
import poolcost  # noqa: E402


def main():
    args = sys.argv[1:]
    seconds = float(args[args.index('--seconds') + 1]) if '--seconds' in args else 600
    seed = int(args[args.index('--seed') + 1]) if '--seed' in args else 1
    frags, recipes = minify.load(args[0])
    enc = [f.encode('latin1') + b'\0' for f in frags]
    cost = lambda order: poolcost.cost(b''.join(enc[j] for j in order))
    cur = list(range(len(frags)))
    best = cost(cur)
    print('start', best, flush=True)
    rng = random.Random(seed)
    t0 = time.time()
    with ThreadPoolExecutor(16) as ex:
        while time.time() - t0 < seconds:
            cands = []
            for _ in range(32):
                i, j = rng.randrange(len(cur)), rng.randrange(len(cur))
                if i != j:
                    o = list(cur)
                    o.insert(j, o.pop(i))
                    cands.append(o)
            cs = list(ex.map(cost, cands))
            k = min(range(len(cs)), key=cs.__getitem__)
            if cs[k] < best:
                best, cur = cs[k], cands[k]
                print(round(time.time() - t0), best, flush=True)
    new_index = {old: new for new, old in enumerate(cur)}
    minify.save(args[1], [frags[j] for j in cur], [[new_index[x] for x in r] for r in recipes])
    print('final', best)


if __name__ == '__main__':
    main()
