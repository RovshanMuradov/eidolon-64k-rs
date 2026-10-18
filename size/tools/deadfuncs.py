#!/usr/bin/env python3
"""Find function overloads and global constants that no including program reaches from main().

deadfuncs.py DIR [--apply OUT]: uses the glslang AST of each program (one top-level item per line) to
build the call graph by mangled signature; a definition is dead when it is unreachable in every program
that includes its fragment. Unreferenced global `const` declarations are reported the same way."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import glsl  # noqa: E402
import minify  # noqa: E402


def analyse(frags, recipe):
    """Return set of (fragment, item index) definitions reachable from main, and all definitions."""
    src = '#define texture2D texture\n'
    starts = {}
    for fi in recipe:
        for ii, (kind, text) in enumerate(glsl.items(frags[fi])):
            if not src.endswith('\n'):
                src += '\n'
            if kind in ('func', 'decl'):
                starts[src.count('\n') + 1] = (fi, ii)
            src += text
    # the #version line must come first: swap it with the texture2D mapping
    first, rest = src.split('\n', 1)
    v, rest2 = rest.split('\n', 1)
    assert v.startswith('#version'), v
    src = v + '\n' + first + '\n' + rest2
    where = starts
    shift = 0
    with tempfile.NamedTemporaryFile(suffix='.frag', mode='w') as f:
        f.write(src)
        f.flush()
        out = subprocess.run(['glslangValidator', '-i', f.name], capture_output=True, text=True).stdout
    defs = {}      # signature -> (fragment, item)
    calls = {}     # signature -> set of called signatures
    current = None
    for line in out.splitlines():
        m = re.match(r'0:(\d+)\s+Function Definition: (\S+)', line)
        if m:
            ln = int(m.group(1))
            current = m.group(2)
            defs[current] = where.get(ln)
            calls.setdefault(current, set())
            continue
        m = re.search(r'Function Call: (\S+)', line)
        if m and current:
            calls[current].add(m.group(1))
    reach, todo = set(), ['main(']
    while todo:
        s = todo.pop()
        if s in reach:
            continue
        reach.add(s)
        todo.extend(calls.get(s, ()))
    live = {defs[s] for s in reach if defs.get(s)}
    alldefs = {v for v in defs.values() if v}
    return live, alldefs, out


def main():
    d = sys.argv[1]
    frags, recipes = minify.load(d)
    live, seen = set(), set()
    for p, r in enumerate(recipes):
        l, a, out = analyse(frags, r)
        if 'main(' not in out:
            print('program', p, 'no AST main; skipped', file=sys.stderr)
            # be conservative: everything in this program is live
            for fi in r:
                for ii, _ in enumerate(glsl.items(frags[fi])):
                    live.add((fi, ii))
        live |= l
        seen |= a
    dead = sorted(seen - live)
    total = 0
    for fi, ii in dead:
        text = glsl.items(frags[fi])[ii][1]
        total += len(text)
        print(fi, ii, len(text), text[:80])
    print('dead bytes', total)
    if '--apply' in sys.argv:
        for fi in {fi for fi, _ in dead}:
            its = glsl.items(frags[fi])
            frags[fi] = ''.join(t for ii, (k, t) in enumerate(its) if (fi, ii) not in dead)
        minify.save(sys.argv[sys.argv.index('--apply') + 1], frags, recipes)


if __name__ == '__main__':
    main()
