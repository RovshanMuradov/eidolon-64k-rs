#!/usr/bin/env python3
"""Cost-guided pool-wide alpha-renaming of internal shader names (random swaps / fresh renames).

permute.py IN OUT [--seconds S] [--seed N]: a move swaps two internal names, or renames one to a fresh
name, uniformly in every fragment (including #define lines and struct field selections of field names).
Internal names are declared in the pool and are not uniforms, outputs, `main`, or swizzle-like.
A uniform consistent permutation of internal identifiers is an alpha-renaming of every program.
Cost: native kkrunchy model of the whole pool."""
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
import minify  # noqa: E402
import poolcost  # noqa: E402

SWIZZLE = re.compile(r'[xyzw]{1,4}|[rgba]{1,4}|[stpq]{1,4}')
RESERVED = set('''if in do for int out main gl_ void const true false uniform return else break while struct float
vec2 vec3 vec4 mat2 mat3 mat4 bool layout inout version define ifdef ifndef endif undef'''.split())
BUILTINS = set('''abs sign floor ceil fract mod min max clamp mix step smoothstep length distance dot cross normalize
reflect refract pow exp log exp2 log2 sqrt inversesqrt sin cos tan asin acos atan radians degrees texture texture2D
textureLod texelFetch dFdx dFdy fwidth any all not equal lessThan greaterThan sinh cosh tanh round trunc transpose
inverse determinant matrixCompMult outerProduct isnan isinf floatBitsToInt intBitsToFloat'''.split())


def tokens(frag):
    """(kind, text, after_dot, in_pp_directive_word) for every lexeme; pp lines are re-lexed inside."""
    out = []
    prev = ''
    for kind, t in glsl.lex(frag):
        if kind == 'pp':
            if t.startswith('#version'):
                out.append(('raw', t, False))
                continue
            m = re.match(r'(\s*#\s*\w+)(.*)', t, re.S)
            out.append(('raw', m.group(1), False))
            p2 = ''
            for k2, t2 in glsl.lex(m.group(2)):
                out.append((k2, t2, p2 == '.'))
                if k2 not in ('space', 'comment'):
                    p2 = t2
            continue
        out.append((kind, t, prev == '.'))
        if kind not in ('space', 'comment'):
            prev = t
    return out


def analyse(frags):
    fields, decl, external, used = set(), set(), {'main'}, set()
    for f in frags:
        for m in re.finditer(r'\bstruct\s+(\w+)\s*\{([^}]*)\}', f):
            decl.add(m.group(1))
            fields |= set(re.findall(r'(\w+)\s*;', m.group(2)))
        for m in re.finditer(r'\b(?:uniform|out)\s+\w+\s+(\w+)', f):
            external.add(m.group(1))
        for kind, t, dot in tokens(f):
            if kind == 'id':
                used.add(t)
        for kind, text in glsl.items(f):
            if kind == 'func':
                decl.add(glsl.func_name(text))
            toks = [t for k, t in glsl.lex(text) if k not in ('space', 'comment')]
            for i in range(len(toks) - 1):
                if (toks[i] in gparse.TYPES or toks[i] in decl) and re.match(r'[A-Za-z_]', toks[i + 1]):
                    decl.add(toks[i + 1])
                if toks[i] == ',' and re.match(r'[A-Za-z_]', toks[i + 1]):
                    pass
        for line in f.split('\n'):
            m = re.match(r'\s*#\s*define\s+(\w+)(?:\(([^)]*)\))?', line)
            if m:
                decl.add(m.group(1))
                if m.group(2):
                    decl |= set(re.findall(r'\w+', m.group(2)))
    # declarators after commas (T a=..,b=..;) and parameters are covered by the type rule above only
    # partially; restrict to names that are declared somewhere
    internal = {n for n in decl if n not in external and n not in RESERVED and n not in BUILTINS and n not in gparse.TYPES
                and not n.startswith('gl_') and n in used}
    internal = {n for n in internal if not (n in fields and SWIZZLE.fullmatch(n))}
    return internal, fields, used


def apply(frags, mapping, fields):
    out = []
    for f in frags:
        s = []
        for kind, t, dot in tokens(f):
            if kind == 'id' and t in mapping and (not dot or t in fields):
                t = mapping[t]
            s.append(t)
        out.append(''.join(s))
    return out


def main():
    args = sys.argv[1:]
    seconds = float(args[args.index('--seconds') + 1]) if '--seconds' in args else 600
    seed = int(args[args.index('--seed') + 1]) if '--seed' in args else 1
    frags, recipes = minify.load(args[0])
    internal, fields, used = analyse(frags)
    names = sorted(internal)
    fresh = [a for a in string.ascii_letters if a not in used and a not in RESERVED]
    fresh += [a + b for a in string.ascii_letters for b in string.ascii_letters + string.digits
              if a + b not in used and a + b not in RESERVED and not SWIZZLE.fullmatch(a + b)]
    print('internal names', len(names), 'fresh 1-char', sum(len(x) == 1 for x in fresh), flush=True)
    pool = lambda fr: b''.join(f.encode('latin1') + b'\0' for f in fr)
    best = poolcost.cost(pool(frags))
    print('start', best, flush=True)
    rng = random.Random(seed)
    t0 = time.time()

    def propose():
        x = rng.choice(names)
        if rng.random() < 0.8:
            y = rng.choice(names)
            if x == y or (x in fields or y in fields) and (SWIZZLE.fullmatch(x) or SWIZZLE.fullmatch(y)):
                return None
            return {x: y, y: x}
        y = rng.choice(fresh[:200])
        if x in fields and SWIZZLE.fullmatch(y):
            return None
        return {x: y}

    with ThreadPoolExecutor(16) as ex:
        while time.time() - t0 < seconds:
            props = []
            while len(props) < 32:
                p = propose()
                if p:
                    props.append(p)
            costs = list(ex.map(lambda m: poolcost.cost(pool(apply(frags, m, fields))), props))
            k = min(range(len(costs)), key=costs.__getitem__)
            if costs[k] < best:
                m = props[k]
                frags = apply(frags, m, fields)
                best = costs[k]
                # update name sets
                for x, y in m.items():
                    if len(m) == 1:
                        names.remove(x)
                        names.append(y)
                        fresh.remove(y)
                        fresh.append(x)
                        if x in fields:
                            fields.discard(x)
                            fields.add(y)
                if len(m) == 2:
                    (x, y), = [tuple(m)]
                    fx, fy = x in fields, y in fields
                    fields.discard(x)
                    fields.discard(y)
                    if fx:
                        fields.add(y)
                    if fy:
                        fields.add(x)
                names.sort()
                print(round(time.time() - t0), m, best, flush=True)
                minify.save(args[1], frags, recipes)
    minify.save(args[1], frags, recipes)
    print('final', best)


if __name__ == '__main__':
    main()
