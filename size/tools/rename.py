#!/usr/bin/env python3
"""Cost-guided renaming of function-local names (parameters and locals) in the CG29 shader pool.

rename.py IN OUT [--seconds S] [--passes N]: for each local name X declared in a function body or
parameter list, tries every allowed name Y and keeps the one that lowers the native kkrunchy model cost
of the whole pool. Safety rules (no capture):
  * X is declared in the function, is not a global/function/struct/macro name anywhere in the pool,
    and does not occur in any #define line of the pool (macros may reference caller locals);
  * Y does not occur anywhere in the function text, is not a pool global/function/struct/macro name,
    does not occur in any #define line, and is a single letter or an existing local name;
  * occurrences after '.' (field selections) are untouched.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import random
import re
import string
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import glsl  # noqa: E402
import gparse  # noqa: E402
import lexmin  # noqa: E402
import minify  # noqa: E402
import poolcost  # noqa: E402

RESERVED = set('''float int bool uint vec2 vec3 vec4 ivec2 ivec3 ivec4 bvec2 bvec3 bvec4 mat2 mat3 mat4 void const
uniform in out inout return if else for while do break continue discard struct sampler2D sampler3D true false
highp mediump lowp precision layout switch case default'''.split())


def global_names(frags):
    names = set()
    macro_ids = set()
    for f in frags:
        for kind, text in glsl.items(f):
            if kind == 'func':
                names.add(glsl.func_name(text))
            elif kind == 'decl':
                toks = [t for k, t in glsl.lex(text) if k not in ('space', 'comment')]
                depth = 0
                for i, t in enumerate(toks):
                    if t in '([{':
                        depth += 1
                    elif t in ')]}':
                        depth -= 1
                    if depth <= 1 and re.match(r'[A-Za-z_]', t):
                        names.add(t)  # conservative: every identifier of a global declaration
            elif kind == 'pp':
                macro_ids |= set(glsl.ids(text))
        for line in f.split('\n'):
            if line.lstrip().startswith('#'):
                macro_ids |= set(glsl.ids(line))
    return names, macro_ids


def locals_of(text):
    """Names declared in a function's parameter list or body."""
    toks = [t for k, t in glsl.lex(text) if k not in ('space', 'comment')]
    out = set()
    start = toks.index('(')
    for i in range(start, len(toks) - 1):
        t, n = toks[i], toks[i + 1]
        if (t in gparse.TYPES or re.fullmatch(r'Z[a-zA-Z]|Z[A-Z]\w*', t) or t in STRUCTS) and re.match(r'[A-Za-z_]', n) \
                and n not in RESERVED:
            out.add(n)
            # comma-continued declarators: T a=..,b=..;
            depth = 0
            j = i + 2
            while j < len(toks) and not (depth == 0 and toks[j] in (';', ')', '{')):
                if toks[j] in '([':
                    depth += 1
                elif toks[j] in ')]':
                    depth -= 1
                elif depth == 0 and toks[j] == ',' and j + 1 < len(toks) and re.match(r'[A-Za-z_]', toks[j + 1]):
                    if toks[j + 1] not in gparse.TYPES and toks[j + 1] not in STRUCTS:
                        out.add(toks[j + 1])
                j += 1
    return out


STRUCTS = set()


def rename(text, x, y):
    out = []
    prev = ''
    for kind, t in glsl.lex(text):
        if kind == 'id' and t == x and prev != '.':
            t = y
        if kind not in ('space', 'comment'):
            prev = t
        out.append(t)
    return ''.join(out)


def main():
    args = sys.argv[1:]
    seconds = float(args[args.index('--seconds') + 1]) if '--seconds' in args else 1e9
    passes = int(args[args.index('--passes') + 1]) if '--passes' in args else 1
    seed = int(args[args.index('--seed') + 1]) if '--seed' in args else 1
    poolcost.start(args[1], seed)
    frags, recipes = minify.load(args[0])
    for f in frags:
        STRUCTS.update(re.findall(r'\bstruct\s+(\w+)', f))
    globs, macro_ids = global_names(frags)
    forbidden = globs | macro_ids | RESERVED | STRUCTS
    # candidate names: single letters plus existing locals
    all_locals = set()
    funcs = []  # (fragment, item index)
    for fi, f in enumerate(frags):
        for ii, (kind, text) in enumerate(glsl.items(f)):
            if kind == 'func':
                funcs.append((fi, ii))
                all_locals |= locals_of(text)
    pool_names = sorted((set(string.ascii_letters) | all_locals) - forbidden)
    print('candidate names', len(pool_names), flush=True)
    pool = lambda fr: b''.join(f.encode('latin1') + b'\0' for f in fr)
    best = poolcost.cost(pool(frags))
    print('start', best, flush=True)
    t0 = time.time()
    rng = random.Random(seed)
    for p in range(passes):
        order = list(range(len(funcs)))
        rng.shuffle(order)
        for k in order:
            if time.time() - t0 > seconds or not poolcost.remaining():
                break
            fi, ii = funcs[k]

            def span():
                pos = 0
                for jj, (kind, t) in enumerate(glsl.items(frags[fi])):
                    if jj == ii:
                        return pos, pos + len(t)
                    pos += len(t)
            a, b = span()
            for x in sorted(locals_of(frags[fi][a:b])):
                if x in forbidden:
                    continue
                a, b = span()
                text = frags[fi][a:b]
                t_ids = set(glsl.ids(text))
                trials = [(y, rename(text, x, y)) for y in pool_names if y not in t_ids]
                trials = trials[:poolcost.remaining()]

                def cost(tr):
                    fr = list(frags)
                    fr[fi] = fr[fi][:a] + tr[1] + fr[fi][b:]
                    return poolcost.cost(pool(fr))
                with ThreadPoolExecutor(poolcost.WORKERS) as ex:
                    cs = list(ex.map(cost, trials))
                if not cs:
                    continue
                j = min(range(len(cs)), key=cs.__getitem__)
                if cs[j] < best:
                    y, new = trials[j]
                    frags[fi] = frags[fi][:a] + new + frags[fi][b:]
                    best = cs[j]
                    print(round(time.time() - t0), 'f%d' % fi, x, '->', y, best, flush=True)
    minify.save(args[1], frags, recipes)
    print('final', best)


if __name__ == '__main__':
    main()
