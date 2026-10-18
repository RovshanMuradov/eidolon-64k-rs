#!/usr/bin/env python3
"""Exact lexical/preprocessor minification passes over the CG29 shader pool.

minify.py IN OUT [pass ...]: IN/OUT are fragment directories (NN.glsl + recipes.json). Every pass keeps
each program's meaning: the preprocessed token stream (pp) or the glslang AST (others) is unchanged, which
astcheck.py confirms. Passes:
  pp      resolve #if/#ifdef/#ifndef groups whose outcome is the same in every program that includes the
          fragment, then drop #defines that no including program references
  empty   drop empty fragments from pool and recipes
  unizero drop `=0.` / `=vecN(0.,...)` initializers of uniforms (uniforms default to zero)
"""
import json
from pathlib import Path
import re
import sys

ID = re.compile(r'[A-Za-z_]\w*')


def load(d):
    d = Path(d)
    recipes = json.loads((d / 'recipes.json').read_text())
    frags = [f.read_text('latin1') for f in sorted(d.glob('[0-9][0-9].glsl'))]
    return frags, recipes


def save(d, frags, recipes):
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob('[0-9][0-9].glsl'):
        old.unlink()
    for i, f in enumerate(frags):
        (d / f'{i:02d}.glsl').write_bytes(f.encode('latin1'))
    (d / 'recipes.json').write_text(json.dumps(recipes))


def users(recipes, n):
    u = [[] for _ in range(n)]
    for p, r in enumerate(recipes):
        for f in r:
            if p not in u[f]:
                u[f].append(p)
    return u


# ---------------------------------------------------------------- preprocessor


def directive(line):
    m = re.match(r'\s*#\s*(\w+)\s*(.*)', line)
    return (m.group(1), m.group(2).strip()) if m else (None, None)


def evaluate(expr, defines):
    """Value of a trivial #if expression, or None if not trivially known."""
    expr = expr.strip()
    for _ in range(8):
        if re.fullmatch(r'\d+', expr):
            return int(expr) != 0
        if re.fullmatch(r'[A-Za-z_]\w*', expr):
            if expr not in defines:
                return False
            body = defines[expr]
            if body is None:
                return None
            expr = body.strip()
            continue
        return None
    return None


def simulate(frags, recipe):
    """Outcomes of conditional directives in one program: {(frag, line): True/False/None/'inactive'}."""
    defines = {}
    stack = []  # (active_before, taken_any, current_active)
    out = {}
    for fi in recipe:
        for li, line in enumerate(frags[fi].split('\n')):
            kind, rest = directive(line) if line.lstrip().startswith('#') else (None, None)
            active = all(s[2] for s in stack)
            if kind in ('if', 'ifdef', 'ifndef'):
                if not active:
                    out[(fi, li)] = 'inactive'
                    stack.append((False, True, False))
                    continue
                if kind == 'if':
                    v = evaluate(rest, defines)
                else:
                    name = rest.split()[0]
                    v = (name in defines) == (kind == 'ifdef')
                out[(fi, li)] = v
                if v is None:
                    return None  # unknown condition: give up on this program
                stack.append((True, v, v))
            elif kind in ('else', 'elif'):
                outer, taken, _ = stack.pop()
                if kind == 'elif':
                    return None
                out[(fi, li)] = 'inactive' if not outer else (not taken)
                stack.append((outer, True, outer and not taken))
            elif kind == 'endif':
                stack.pop()
            elif kind == 'define' and active:
                m = re.match(r'(\w+)(\([^)]*\))?\s*(.*)', rest)
                defines[m.group(1)] = None if m.group(2) else m.group(3)
            elif kind == 'undef' and active:
                defines.pop(rest.split()[0], None)
    assert not stack
    return out


def resolve_conditionals(frags, recipes):
    """Remove conditional groups whose outcome agrees in every including program. Returns count."""
    u = users(recipes, len(frags))
    sims = [simulate(frags, r) for r in recipes]
    changed = 0
    for fi, f in enumerate(frags):
        if not u[fi] or any(sims[p] is None for p in u[fi]):
            continue
        lines = f.split('\n')
        # find outermost groups
        i = 0
        keep = []
        while i < len(lines):
            kind, _ = directive(lines[i]) if lines[i].lstrip().startswith('#') else (None, None)
            if kind not in ('if', 'ifdef', 'ifndef'):
                keep.append(lines[i])
                i += 1
                continue
            # collect group structure at this nesting level
            depth, j = 0, i
            branches = [i]  # line indices of if/else at our level
            while True:
                k2, _ = directive(lines[j]) if lines[j].lstrip().startswith('#') else (None, None)
                if k2 in ('if', 'ifdef', 'ifndef'):
                    depth += 1
                elif k2 == 'endif':
                    depth -= 1
                    if depth == 0:
                        break
                elif k2 in ('else', 'elif') and depth == 1:
                    branches.append(j)
                j += 1
            end = j
            outcomes = set()
            for p in u[fi]:
                vals = tuple(sims[p].get((fi, b)) for b in branches)
                if vals[0] != 'inactive':
                    outcomes.add(vals)
            if len(outcomes) == 1 and None not in next(iter(outcomes)):
                vals = next(iter(outcomes))
                bounds = branches + [end]
                for b, v in enumerate(vals):
                    if v is True:
                        keep.extend(lines[bounds[b] + 1:bounds[b + 1]])
                changed += 1
            elif not outcomes:
                changed += 1  # inactive everywhere: drop the whole group
            else:
                keep.extend(lines[i:end + 1])
            i = end + 1
        frags[fi] = '\n'.join(keep)
    return changed


def uses(src, name):
    """Occurrences of identifier `name` outside the defined-name position of `#define name` lines."""
    n = 0
    for line in src.split('\n'):
        found = ID.findall(line)
        n += found.count(name)
        if re.match(r'\s*#\s*define\s+' + name + r'\b', line):
            n -= 1
    return n


def drop_unused_defines(frags, recipes):
    u = users(recipes, len(frags))
    programs = [''.join(frags[f] for f in r) for r in recipes]
    changed = 0
    for fi, f in enumerate(frags):
        if not u[fi]:
            continue
        keep = []
        for line in f.split('\n'):
            kind, rest = directive(line) if line.lstrip().startswith('#') else (None, None)
            if kind == 'define':
                name = re.match(r'\w+', rest).group()
                if all(uses(programs[p], name) == 0 for p in u[fi]):
                    changed += 1
                    continue
            keep.append(line)
        frags[fi] = '\n'.join(keep)
    return changed


def pass_pp(frags, recipes):
    total = 0
    while True:
        n = resolve_conditionals(frags, recipes) + drop_unused_defines(frags, recipes)
        total += n
        if not n:
            return total


# ---------------------------------------------------------------- uniforms


def pass_unizero(frags, recipes):
    n = 0
    zero = r'(?:0\.?|\.0|0\.0)'
    pat = re.compile(r'(uniform\s+(?:float|vec[234])\s+\w+)\s*=\s*(?:' + zero + r'|vec[234]\(\s*' + zero +
                     r'(?:\s*,\s*' + zero + r')*\s*\))\s*;')
    for i, f in enumerate(frags):
        g, k = pat.subn(r'\1;', f)
        frags[i] = g
        n += k
    return n


def pass_empty(frags, recipes):
    """Drop empty fragments from the pool and the recipes (an empty string adds nothing to a program)."""
    keep = [i for i, f in enumerate(frags) if f]
    index = {old: new for new, old in enumerate(keep)}
    n = len(frags) - len(keep)
    recipes[:] = [[index[x] for x in r if frags[x]] for r in recipes]
    frags[:] = [frags[i] for i in keep]
    return n


def pass_tex2d(frags, recipes):
    """texture2D(s,p) -> texture(s,p): the same builtin for sampler2D; only in #version 450 programs."""
    n = 0
    for i, f in enumerate(frags):
        g, k = re.subn(r'\btexture2D\(', 'texture(', f)
        frags[i] = g
        n += k
    return n


PASSES = {'tex2d': pass_tex2d, 'pp': pass_pp, 'unizero': pass_unizero, 'empty': pass_empty}


def main():
    frags, recipes = load(sys.argv[1])
    for name in sys.argv[3:]:
        print(name, PASSES[name](frags, recipes))
    save(sys.argv[2], frags, recipes)


if __name__ == '__main__':
    main()
