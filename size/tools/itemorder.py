#!/usr/bin/env python3
"""Hill-climb the order of top-level functions/declarations inside each fragment of the CG29 pool.

itemorder.py IN OUT [--seconds S] [--seed N]: items move only within runs of func/decl items between
preprocessor lines, and only to positions where every name an item uses that is defined in the same
run is still defined earlier (functions, globals, structs). Overload sets keep their relative order.
Cost: native kkrunchy model of the whole pool."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import random
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import glsl  # noqa: E402
import minify  # noqa: E402
import poolcost  # noqa: E402

KEYWORDS = set('float int bool vec2 vec3 vec4 mat2 mat3 mat4 void const uniform in out inout return if else for '
               'while break continue struct'.split())


def defined(kind, text):
    if kind == 'func':
        return {glsl.func_name(text)}
    m = re.match(r'\s*struct\s+(\w+)', text)
    if m:
        return {m.group(1)}
    # declaration: names right before = , ; [ at depth 0
    names = set()
    depth = 0
    toks = [t for k, t in glsl.lex(text) if k not in ('space', 'comment')]
    for i, t in enumerate(toks):
        if t in '([{':
            depth += 1
        elif t in ')]}':
            depth -= 1
        elif depth == 0 and t in ('=', ',', ';', '[') and i and re.match(r'[A-Za-z_]', toks[i - 1]) \
                and toks[i - 1] not in KEYWORDS:
            names.add(toks[i - 1])
    return names


def runs(frag):
    """Split into segments: lists of items; movable runs are lists of (kind, text) func/decl items."""
    segs, cur = [], []
    for kind, text in glsl.items(frag):
        if kind in ('func', 'decl'):
            cur.append((kind, text))
        else:
            if cur:
                segs.append(('run', cur))
                cur = []
            segs.append(('fixed', text))
    if cur:
        segs.append(('run', cur))
    return segs


def valid(run):
    seen = set()
    names_in_run = set()
    for kind, text in run:
        names_in_run |= defined(kind, text)
    for kind, text in run:
        d = defined(kind, text)
        used = set(glsl.ids(text)) & names_in_run
        if kind == 'func':
            # body uses; own name may recurse into an earlier overload, which must stay earlier
            pass
        if (used - d) - seen:
            return False
        if kind == 'func' and glsl.func_name(text) in seen and not all(
                True for _ in [0]):
            pass
        seen |= d
    return True


def join(segs):
    return ''.join(x if k == 'fixed' else ''.join(t for _, t in x) for k, x in segs)


def main():
    args = [a for a in sys.argv[1:]]
    seconds = float(args[args.index('--seconds') + 1]) if '--seconds' in args else 300
    seed = int(args[args.index('--seed') + 1]) if '--seed' in args else 1
    frags, recipes = minify.load(args[0])
    segs = [runs(f) for f in frags]
    # overload order: functions sharing a name keep relative order (checked in move)
    pool = lambda S: b''.join(join(s).encode('latin1') + b'\0' for s in S)
    best = poolcost.cost(pool(segs))
    print('start', best, flush=True)
    rng = random.Random(seed)
    movable = [(fi, si) for fi, s in enumerate(segs) for si, (k, x) in enumerate(s) if k == 'run' and len(x) > 1]
    weights = [len(segs[fi][si][1]) for fi, si in movable]
    t0 = time.time()

    def propose():
        fi, si = rng.choices(movable, weights)[0]
        run = list(segs[fi][si][1])
        i, j = rng.randrange(len(run)), rng.randrange(len(run))
        if i == j:
            return None
        if re.match(r'\s*out\b', run[i][1]):
            return None  # output declarations keep their order (fragment output locations)
        item = run.pop(i)
        run.insert(j, item)
        names = [glsl.func_name(t) if k == 'func' else None for k, t in run]
        old = [glsl.func_name(t) if k == 'func' else None for k, t in segs[fi][si][1]]
        for n in set(x for x in names if x):
            if [t for (k, t), m in zip(run, names) if m == n] != [t for (k, t), m in zip(segs[fi][si][1], old) if m == n]:
                return None
        if not valid(run):
            return None
        return fi, si, run

    def cost(p):
        fi, si, run = p
        S = list(segs)
        s = list(S[fi])
        s[si] = ('run', run)
        S[fi] = s
        return poolcost.cost(pool(S))

    with ThreadPoolExecutor(16) as ex:
        while time.time() - t0 < seconds:
            props = []
            while len(props) < 32:
                p = propose()
                if p:
                    props.append(p)
            costs = list(ex.map(cost, props))
            k = min(range(len(costs)), key=costs.__getitem__)
            if costs[k] < best:
                best = costs[k]
                fi, si, run = props[k]
                s = list(segs[fi])
                s[si] = ('run', run)
                segs[fi] = s
                print(round(time.time() - t0), best, flush=True)
                minify.save(args[1], [join(s) for s in segs], recipes)
    minify.save(args[1], [join(s) for s in segs], recipes)
    print('final', best)


if __name__ == '__main__':
    main()
