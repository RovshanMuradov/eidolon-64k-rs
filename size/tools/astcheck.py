#!/usr/bin/env python3
"""Compare the glslang front-end ASTs of every program in two fragment directories.

astcheck.py DIR_A DIR_B [--names]: each DIR holds NN.glsl fragments and recipes.json (as written by
dump_pool.py). Programs are compiled as fragment shaders with `glslangValidator -i`; the dumped
intermediate trees (after constant folding) are normalized (source locations and, unless --names,
identifier spellings are dropped) and compared. Prints one line per program."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def programs(d):
    d = Path(d)
    recipes = json.loads((d / 'recipes.json').read_text())
    frags = {int(p.stem): p.read_bytes() for p in d.glob('[0-9][0-9].glsl')}
    return [b''.join(frags[i] for i in r) for r in recipes]


def collapse(lines):
    """Indentation tree; drop single-child Sequence nodes (braces around one statement)."""
    root = ('', [])
    stack = [(-1, root)]
    for line in lines:
        depth = len(line) - len(line.lstrip(' '))
        node = (line.strip(), [])
        while stack[-1][0] >= depth:
            stack.pop()
        stack[-1][1][1].append(node)
        stack.append((depth, node))

    def norm(n):
        kids = []
        for k in n[1]:
            k = norm(k)
            if n[0] == 'Sequence' and k[0] == 'Sequence':
                kids.extend(k[1])  # nested sequences (multi-declarator initializers) splice
            else:
                kids.append(k)
        if n[0] == 'Sequence' and len(kids) == 1:
            return kids[0]
        return (n[0], kids)

    out = []
    top = norm(root)
    if SORT:
        # order-insensitive at top level: function definitions and linker objects
        def ser(n):
            return n[0] + '(' + ','.join(ser(k) for k in n[1]) + ')'
        def srt(n, d):
            kids = [srt(k, d + 1) for k in n[1]]
            if d <= 1 or n[0] == 'Linker Objects':
                kids.sort(key=ser)
            return (n[0], kids)
        top = srt(top, 0)

    def emit(n, d):
        out.append('  ' * d + n[0])
        for k in n[1]:
            emit(k, d + 1)
    for k in top[1]:
        emit(k, 0)
    return out


def ast(src, keep_names):
    # glslang is stricter than the drivers the intro targets: map texture2D for checking only.
    src = src.replace(b'#version 450\n', b'#version 450\n#define texture2D texture\n', 1)
    with tempfile.NamedTemporaryFile(suffix='.frag') as f:
        f.write(src)
        f.flush()
        r = subprocess.run(['glslangValidator', '-i', f.name], capture_output=True, text=True)
    lines = []
    for line in r.stdout.splitlines()[1:]:
        if line.startswith('Linked') or line.startswith('ERROR') and 'link' in line.lower():
            break
        if line.startswith('ERROR') or line.startswith('WARNING'):
            lines.append(re.sub(r'0:\d+:', '', line))
            continue
        line = re.sub(r'^\d+:\d+ ', '', line)
        line = re.sub(r'^0:\? ', '', line)
        line = re.sub(r'\(\d+:\d+\)', '', line)
        line = re.sub(r'0:\d+', '', line)
        if not keep_names:
            line = re.sub(r"'[A-Za-z_]\w*'", "'_'", line)
            line = re.sub(r'(global|temp|in|out|inout|uniform|const) ([\w -]*?(?:float|int|bool|uint|structure\{[^}]*\})) [A-Za-z_]\w*([,}])', r'\1 \2 _\3', line)
            line = re.sub(r'(?:global|temp) ([\w -]*?float|int) [A-Za-z_]\w*(?=[,}])', r'\1 _', line)
            line = re.sub(r'struct-[A-Za-z_]\w*-', 'struct-_-', line)
            line = re.sub(r'\b[A-Za-z_]\w*: direct index for structure', '_: direct index for structure', line)
            line = re.sub(r'structure\{[^}]*\}', lambda m: re.sub(r' [A-Za-z_]\w*(?=[,}])', ' _', m.group()), line)
            line = re.sub(r'\b(Function Definition|Function Call): [\w(;)]*', r'\1', line)
        lines.append(line.rstrip())
    lines = collapse(lines)
    return r.returncode, lines


SORT = '--sort' in sys.argv


def main():
    a, b = programs(sys.argv[1]), programs(sys.argv[2])
    names = '--names' in sys.argv
    bad = 0
    for i, (x, y) in enumerate(zip(a, b)):
        ra, la = ast(x, names)
        rb, lb = ast(y, names)
        same = la == lb and ra == rb
        bad += not same
        print(i, 'same' if same else 'DIFFERS', ra, rb, len(la), len(lb))
        if not same and '-v' in sys.argv:
            import difflib
            print('\n'.join(list(difflib.unified_diff(la, lb, lineterm='', n=1))[:40]))
    print('differing programs:', bad)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
