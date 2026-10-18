#!/usr/bin/env python3
"""Fail-closed shader comparison: unmodified glslang compile + binding-aware tokens.

Inputs are CG29 blobs or fragment directories. Exit 0 means every program compiled
and matched, 1 means a difference/error, 2 means explicitly unsupported compilation.
An unsupported baseline NEVER counts as PASS. No texture2D macro is injected.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import difflib
import json
from pathlib import Path
import pprint
import re
import subprocess
import tempfile

import bindings
import cg29


def programs(path):
    path = Path(path)
    if path.is_file():
        _, frags, recipes = cg29.parse(path.read_bytes())
    else:
        recipes = json.loads((path / 'recipes.json').read_text())
        files = sorted(path.glob('*.glsl'))
        if [p.name for p in files] != [f'{i:02d}.glsl' for i in range(len(files))]:
            raise ValueError('fragments must be contiguous NN.glsl files')
        frags = [p.read_bytes() for p in files]
    if not isinstance(recipes, list) or not recipes or not frags:
        raise ValueError('empty or invalid program/fragment set')
    for r in recipes:
        if not isinstance(r, list) or not r or any(type(i) is not int or not 0 <= i < len(frags) for i in r):
            raise ValueError('invalid recipe/fragment reference')
    return [b''.join(frags[i] for i in r) for r in recipes]


def compile_source(src, validator='glslangValidator', temp_dir=None):
    with tempfile.TemporaryDirectory(prefix='shader-check-', dir=temp_dir) as d:
        path = Path(d) / 'shader.frag'
        path.write_bytes(src)
        compiled = subprocess.run([validator, '--dump-builtin-symbols', str(path)],
                                  capture_output=True, text=True, timeout=60)
        before, marker, tail = compiled.stdout.partition('BuiltinSymbolTable {\n')
        table, end, after = tail.partition('\n}\n')
        builtins = set(re.findall(r'^([A-Za-z_]\w*):', table, re.M)) if marker and end else set()
        diagnostic = before + after + compiled.stderr
        if compiled.returncode or 'ERROR:' in diagnostic:
            return False, diagnostic, None, builtins
        if not builtins:
            return False, 'unsupported glslang builtin-symbol dump format', None, set()
        pre = subprocess.run([validator, '-E', str(path)], capture_output=True, text=True, timeout=60)
        if pre.returncode or 'ERROR:' in pre.stderr:
            return False, diagnostic + pre.stdout + pre.stderr, None, builtins
        return True, diagnostic, pre.stdout, builtins


def compare(a, b, *, names=None, fields=None, keep_names=False, reorder=False,
            uniforms_by_name=False, validator='glslangValidator', temp_dir=None):
    # Compile both inputs exactly as supplied, before preprocessing/canonicalization.
    ca, da, pa, ba = compile_source(a, validator, temp_dir)
    cb, db, pb, bb = compile_source(b, validator, temp_dir)
    if not ca or not cb:
        return 'COMPILE_FAILURE', f'baseline compiled={ca}; candidate compiled={cb}\n{da}\n{db}'
    try:
        opts = dict(keep_names=keep_names, reorder=reorder, uniforms_by_name=uniforms_by_name)
        left = bindings.canonical(pa, builtins=ba, **opts)
        right = bindings.canonical(pb, builtins=bb, names=names, fields=fields, **opts)
    except bindings.Fail as e:
        return 'UNSUPPORTED_SYNTAX', str(e)
    if left == right:
        return 'PASS', 'unmodified compilation and binding-aware token equivalence'
    diff = difflib.unified_diff(pprint.pformat(left, width=120).splitlines(),
                                pprint.pformat(right, width=120).splitlines(), lineterm='', n=2)
    return 'DIFFERS', '\n'.join(list(diff)[:60])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('baseline', type=Path)
    ap.add_argument('candidate', type=Path)
    ap.add_argument('--rename-map', type=Path, help='JSON candidate-to-baseline names and fields maps')
    ap.add_argument('--names', action='store_true', help='also retain local spellings')
    ap.add_argument('--reorder-functions', action='store_true', help='ignore only function/type definition order')
    ap.add_argument('--uniforms-by-name', action='store_true', help='host looks up uniforms by name; ignore their declaration order')
    ap.add_argument('--unsupported', type=int, action='append', default=[], help='report failed program as unsupported (still exit 2)')
    ap.add_argument('--validator', default='glslangValidator')
    ap.add_argument('--work', type=Path, default=Path('.build/shader-check'))
    ap.add_argument('--jobs', type=int, choices=range(1, 5), default=4)
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args(argv)
    try:
        a, b = programs(args.baseline), programs(args.candidate)
        if len(a) != len(b):
            raise ValueError(f'unequal program counts: {len(a)} != {len(b)}')
        if any(i < 0 or i >= len(a) for i in args.unsupported):
            raise ValueError('unsupported program index out of range')
        mapping = json.loads(args.rename_map.read_text()) if args.rename_map else {}
        if not isinstance(mapping, dict) or set(mapping) - {'names', 'fields'}:
            raise ValueError('invalid rename map')
        if any(not isinstance(m, dict) for m in mapping.values()):
            raise ValueError('rename maps must be objects')
        args.work.mkdir(parents=True, exist_ok=True)

        def check(pair):
            return compare(*pair, names=mapping.get('names'), fields=mapping.get('fields'),
                           keep_names=args.names, reorder=args.reorder_functions,
                           uniforms_by_name=args.uniforms_by_name, validator=args.validator, temp_dir=args.work)

        with ThreadPoolExecutor(args.jobs) as ex:
            results = list(ex.map(check, zip(a, b, strict=True)))
        bad = unsupported = passed = 0
        for i, (status, detail) in enumerate(results):
            if status == 'PASS':
                passed += 1
            elif status == 'COMPILE_FAILURE' and detail.startswith('baseline compiled=False;') and i in args.unsupported:
                status = 'UNSUPPORTED'
                unsupported += 1
            else:
                bad += 1
            print(i, status)
            if args.verbose and status != 'PASS':
                print(detail)
        print(f'{passed} passed; {bad} failed; {unsupported} unsupported; {len(a)} total')
        return 1 if bad else 2 if unsupported else 0
    except (OSError, ValueError, KeyError, IndexError, AssertionError, subprocess.SubprocessError) as e:
        print(f'FAIL: {e}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
