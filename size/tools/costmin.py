#!/usr/bin/env python3
"""Cost-guided, tree-preserving edits of the CG29 shader pool.

costmin.py IN OUT KIND... [--rounds N]: generates candidate edits inside function bodies (see
KINDS), keeps only those whose reparsed body has the same normalized tree (gparse.strip), measures
each with the native kkrunchy model on the whole pool, and greedily accepts edits that lower it.

Kinds: parens (drop redundant parentheses), braces (drop braces around one non-declaration statement of
if/else/for/while), decls (merge `T a;T b;`), ctor (vecN(c,c,c) -> vecN(c) for one literal),
swz (rgba/stpq swizzle letters -> xyzw and back), lit (literal spelling: 0. / 0.0 / .0)."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import glsl  # noqa: E402
import gparse  # noqa: E402
import lexmin  # noqa: E402
import minify  # noqa: E402
import poolcost  # noqa: E402

STRUCTS = set()


def func_spans(frag):
    """(start, end) offsets of function items in a fragment."""
    out, pos = [], 0
    for kind, text in glsl.items(frag):
        if kind == 'func':
            out.append((pos, pos + len(text)))
        pos += len(text)
    return out


def literal_forms(tok):
    m = re.fullmatch(r'(\d*)\.(\d*)', tok)
    if not m:
        return []
    a, b = m.group(1), m.group(2)
    a2 = a.lstrip('0')
    b2 = b.rstrip('0')
    forms = {f'{a2}.{b2}' if (a2 or b2) else '0.', f'{a or "0"}.{b2}', f'{a2}.{b or "0"}' if a2 else f'0.{b or "0"}'}
    if not a2 and b2:
        forms.add('0.' + b2)
    forms.discard(tok)
    return [f for f in forms if f != '.' and float(f) == float(tok)]


def candidates(text, kinds):
    """Edits (start, end, replacement) relative to a function item's text."""
    toks = lexmin.sig(text)
    body = next(i for i, (t, _, _) in enumerate(toks) if t == '{')
    out = []
    for kind in kinds:
        if kind in ('parens', 'braces', 'decls'):
            for e in lexmin.candidates(toks, kind):
                out.append(tuple(e))
        elif kind == 'ctor':
            for i, (t, pos, _) in enumerate(toks):
                if i > body and re.fullmatch(r'[ib]?vec[234]', t) and i + 1 < len(toks) and toks[i + 1][0] == '(':
                    n = int(t[-1])
                    j = i + 2
                    args = [toks[j + 2 * k][0] for k in range(n) if j + 2 * k < len(toks)]
                    seps = [toks[j + 2 * k + 1][0] for k in range(n) if j + 2 * k + 1 < len(toks)]
                    if len(args) == n and all(re.fullmatch(r'[0-9.]+', a) for a in args) and len(set(args)) == 1 \
                            and seps == [','] * (n - 1) + [')']:
                        out.append(((toks[j][1], toks[j + 2 * n - 1][1], args[0]),))
        elif kind == 'swz':
            for i, (t, pos, _) in enumerate(toks):
                if i > body and toks[i - 1][0] == '.' and re.fullmatch(r'[rgba]{1,4}|[xyzw]{1,4}', t):
                    other = t.translate(str.maketrans('rgbaxyzw', 'xyzwrgba'))
                    out.append(((pos, pos + len(t), other),))
        elif kind == 'lit':
            for i, (t, pos, k) in enumerate(toks):
                if i > body and k == 'number':
                    for f in literal_forms(t):
                        out.append(((pos, pos + len(t), f),))
    return out


def tree(text):
    return lexmin.parse_body(text, STRUCTS)[0]


def apply_edits(text, edits):
    for a, b, rep in sorted(edits, reverse=True):
        text = text[:a] + rep + text[b:]
    return text


def overlaps(edits, used):
    return any(not (b <= u0 or a >= u1) for a, b, _ in edits for u0, u1 in used)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    rounds = int(sys.argv[sys.argv.index('--rounds') + 1]) if '--rounds' in sys.argv else 3
    if '--rounds' in sys.argv:
        args.remove(str(rounds))
    src, dst, kinds = args[0], args[1], args[2:]
    frags, recipes = minify.load(src)
    for f in frags:
        STRUCTS.update(re.findall(r'\bstruct\s+(\w+)', f))
    pool = lambda fr: b''.join(f.encode('latin1') + b'\0' for f in fr)
    best = poolcost.cost(pool(frags))
    print('start', best, flush=True)
    for rnd in range(rounds):
        # candidates per fragment with absolute offsets; validated individually against the tree
        cands = []
        for fi, f in enumerate(frags):
            for a, b in func_spans(f):
                text = f[a:b]
                t0 = tree(text)
                if t0 is None:
                    continue
                for e in candidates(text, kinds):
                    new = apply_edits(text, e)
                    if tree(new) != t0:
                        continue
                    # no token fusion
                    if [t for t, _, _ in lexmin.sig(new)] != [t for t, _, _ in lexmin.sig(new)]:
                        continue
                    cands.append((fi, a, b, tuple((x + a, y + a, r) for x, y, r in e)))

        def gain(c):
            fi, a, b, e = c
            fr = list(frags)
            fr[fi] = apply_edits(fr[fi], e)
            return best - poolcost.cost(pool(fr))
        with ThreadPoolExecutor(16) as ex:
            gains = list(ex.map(gain, cands))
        order = sorted((g, i) for i, g in enumerate(gains) if g > 0)[::-1]
        print('round', rnd, 'candidates', len(cands), 'positive', len(order), flush=True)
        if not order:
            break
        # sequential acceptance on top of the accepted set; edits are absolute offsets in the round's frags
        accepted = {}
        used = {}
        base = list(frags)
        cur = best
        for g, i in order:
            fi, a, b, e = cands[i]
            if overlaps(e, used.get(fi, [])):
                continue
            trial = accepted.get(fi, []) + list(e)
            fr = list(base)
            for fj, es in accepted.items():
                fr[fj] = apply_edits(base[fj], es)
            fr[fi] = apply_edits(base[fi], trial)
            # whole-fragment tree check of affected functions
            ok = True
            for x, y in func_spans(base[fi]):
                pass
            c = poolcost.cost(pool(fr))
            if c < cur:
                # verify all functions of this fragment still parse to the original trees
                old = [tree(base[fi][x:y]) for x, y in func_spans(base[fi])]
                new = [tree(fr[fi][x:y]) for x, y in func_spans(fr[fi])]
                if old != new:
                    continue
                cur = c
                accepted[fi] = trial
                used.setdefault(fi, []).extend((x, y) for x, y, _ in e)
        for fi, es in accepted.items():
            frags[fi] = apply_edits(base[fi], es)
        print('round', rnd, 'accepted', sum(len(v) for v in accepted.values()), 'cost', best, '->', cur, flush=True)
        if cur >= best:
            break
        best = cur
    minify.save(dst, frags, recipes)


if __name__ == '__main__':
    main()
