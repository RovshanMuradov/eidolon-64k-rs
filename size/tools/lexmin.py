#!/usr/bin/env python3
"""Tree-preserving token deletions in the CG29 shader pool's function bodies.

lexmin.py IN OUT KIND...: KIND is any of
  parens  remove redundant parentheses
  braces  remove braces around a single non-declaration statement of if/else/for/while
  decls   merge consecutive declarations with identical qualifiers and type (`T a;T b;` -> `T a,b;`)
Every edit is kept only if the reparsed body has the same normalized tree (gparse.strip) and the
token sequence is unchanged apart from the edit (no tokens fuse). Functions whose body holds
preprocessor lines or fails to parse are left alone."""
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import glsl  # noqa: E402
import gparse  # noqa: E402
import minify  # noqa: E402


def sig(text):
    """Significant tokens with their offsets."""
    out, pos = [], 0
    for kind, t in glsl.lex(text):
        if kind not in ('space', 'comment'):
            out.append((t, pos, kind))
        pos += len(t)
    return out


def parse_body(text, structs):
    toks = sig(text)
    if any(k == 'pp' for _, _, k in toks):
        return None, toks
    # body starts at the first '{'
    start = next((i for i, (t, _, _) in enumerate(toks) if t == '{'), None)
    if start is None:
        return None, toks
    p = gparse.Parser([t for t, _, _ in toks[start:]], structs)
    try:
        tree = p.block()
    except gparse.Fail:
        return None, toks
    if p.i != len(toks) - start:
        return None, toks
    return gparse.strip(tree), toks


def match(toks, i):
    depth = 0
    for j in range(i, len(toks)):
        if toks[j][0] in '([{':
            depth += 1
        elif toks[j][0] in ')]}':
            depth -= 1
            if depth == 0:
                return j
    return None


def apply(text, edits):
    for a, b, rep in sorted(edits, reverse=True):
        text = text[:a] + rep + text[b:]
    return text


def candidates(toks, kind):
    """Yield lists of (start, end, replacement) text edits."""
    if kind in ('parens', 'braces'):
        opener = '(' if kind == 'parens' else '{'
        body = next(i for i, (t, _, _) in enumerate(toks) if t == '{')
        for i, (t, pos, _) in enumerate(toks):
            if t != opener or i <= body:
                continue
            prev = toks[i - 1][0] if i else ''
            if kind == 'parens' and (re.match(r'[A-Za-z_0-9\]]', prev) or prev == ')'):
                continue  # call, constructor, if/for/while, or cast-like syntax
            if kind == 'braces' and prev not in (')', 'else'):
                continue
            j = match(toks, i)
            if j is None:
                continue
            yield [(pos, pos + 1, ''), (toks[j][1], toks[j][1] + 1, '')]
    elif kind == 'decls':
        for i, (t, pos, _) in enumerate(toks):
            if t == ';' and i + 1 < len(toks):
                # previous statement must be a declaration: find its start
                j = i + 1
                if toks[j][0] in gparse.TYPES or re.match(r'[A-Z]\w*$', toks[j][0]):
                    yield [(pos, toks[j][1] + len(toks[j][0]) + 1, ',')]


def minimize(text, structs, kinds):
    tree, toks = parse_body(text, structs)
    if tree is None:
        return text, 0
    count = 0
    for kind in kinds:
        progress = True
        while progress:
            progress = False
            toks = sig(text)
            for edit in candidates(toks, kind):
                new = apply(text, edit)
                if kind == 'decls':
                    # `T a..;T b` -> `T a..,b`: needs the declaration type of the first statement equal
                    pass
                t2, toks2 = parse_body(new, structs)
                if t2 is None or t2 != tree:
                    continue
                # no token fusion: significant tokens equal the old minus deleted ones
                old = [t for t, _, _ in toks]
                newt = [t for t, _, _ in toks2]
                if kind != 'decls' and len(newt) != len(old) - 2:
                    continue
                if kind == 'decls' and len(newt) != len(old) - 1:
                    continue
                text = new
                count += 1
                progress = True
                break
    return text, count


def main():
    frags, recipes = minify.load(sys.argv[1])
    kinds = sys.argv[3:]
    structs = set()
    for f in frags:
        structs |= set(re.findall(r'\bstruct\s+(\w+)', f))
    total = 0
    for fi, f in enumerate(frags):
        out = []
        for kind, text in glsl.items(f):
            if kind == 'func':
                text, n = minimize(text, structs, kinds)
                total += n
            out.append(text)
        frags[fi] = ''.join(out)
    print('edits', total)
    minify.save(sys.argv[2], frags, recipes)


if __name__ == '__main__':
    main()
