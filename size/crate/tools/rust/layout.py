#!/usr/bin/env python3
"""Regenerate/check lay2 ordering and reject changed COFF section membership.

--import-order accepts a research {text: [...], rdata: [...]} order and an
unrenamed --object. This explicit operation writes a new manifest and script.
Normal builds only validate; they never update the frozen layout implicitly.
"""
import argparse
from collections import Counter
from fnmatch import fnmatchcase
import json
from pathlib import Path
import re

from coff import anonymous_digest, rename_anonymous_rdata, sections

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / 'lay2.json'
SCRIPT = HERE / 'sizecoded.ld'
PREFIXES = ('.text$', '.rdata$', '.rd$')


def pattern(name):
    # Rust v0 disambiguators and backrefs use base62 (including uppercase).
    # Backrefs in this frozen symbol set are <= 3 digits. Restrict their length
    # to avoid consuming an identifier such as "BoxNtNt...Cs..._" as a backref.
    name = re.sub(r'Cs[0-9A-Za-z]*_', 'Cs*_', name)
    return re.sub(r'(?<=[0-9A-Za-z])B[0-9A-Za-z]{0,3}_(?=[0-9EINCTB]|$)', 'B*_', name)


def render(script, manifest):
    for key in ('text', 'rdata'):
        block = '\n'.join(f'    *({name})' for name in manifest[key])
        expr = rf'(?<=    /\* BEGIN LAYOUT {key} \*/\n).*?(?=    /\* END LAYOUT {key} \*/)'
        script, count = re.subn(expr, lambda _: block + '\n', script, flags=re.S)
        if count != 1:
            raise ValueError(f'missing/duplicate generated {key} layout block')
    return script


def check_script(manifest):
    script = SCRIPT.read_text()
    if render(script, manifest) != script:
        raise ValueError('stale sizecoded.ld: run python3 size/crate/tools/rust/layout.py')


def validate(data, manifest):
    actual = [s for s in sections(data) if s['name'].startswith(PREFIXES)]
    names = [s['name'] for s in actual]
    expected = manifest['text'] + manifest['rdata'] + manifest['discarded']
    if len(expected) != len(set(expected)) or any(n > 1 for n in Counter(names).values()):
        raise ValueError('layout requires unique section identities')
    errors = []
    for pat in expected:
        matches = [name for name in names if fnmatchcase(name, pat)]
        if len(matches) != 1:
            errors.append(f'{pat}: expected one section, got {len(matches)}')
    for name in names:
        matches = [pat for pat in expected if fnmatchcase(name, pat)]
        if len(matches) != 1:
            errors.append(f'{name}: expected one layout slot, got {len(matches)}')
    digests = {s['name']: anonymous_digest(s) for s in actual if s['name'].startswith('.rd$')}
    if digests != manifest['anonymous']:
        errors.append('anonymous-rdata full digest membership changed')
    if errors:
        raise ValueError('lay2 section membership changed; explicitly regenerate/retune the layout:\n  ' +
                         '\n  '.join(errors))


def prepare_object(data):
    manifest = json.loads(MANIFEST.read_text())
    check_script(manifest)
    data, _ = rename_anonymous_rdata(data)
    validate(data, manifest)
    return data


def import_order(order, data):
    data, digests = rename_anonymous_rdata(data)
    names = [s['name'] for s in sections(data) if s['name'].startswith(PREFIXES)]
    placed = order['text'] + order['rdata']
    if len(placed) != len(set(placed)) or set(placed) - set(names):
        raise ValueError('order has duplicate sections or sections absent from the supplied object')
    manifest = {'schema': 1, 'name': 'lay2',
                'text': [pattern(n) for n in order['text']],
                'rdata': [pattern(n) for n in order['rdata']],
                'discarded': [pattern(n) for n in names if n not in placed],
                'anonymous': dict(sorted(digests.items()))}
    validate(data, manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--object', type=Path, help='validate an unrenamed runtime COFF object')
    parser.add_argument('--import-order', type=Path)
    args = parser.parse_args()
    if args.import_order:
        if not args.object or args.check:
            parser.error('--import-order requires --object and cannot be used with --check')
        manifest = import_order(json.loads(args.import_order.read_text()), args.object.read_bytes())
        MANIFEST.write_text(json.dumps(manifest, indent=2) + '\n')
    else:
        manifest = json.loads(MANIFEST.read_text())
    if args.check:
        check_script(manifest)
    else:
        SCRIPT.write_text(render(SCRIPT.read_text(), manifest))
    if args.object:
        prepare_object(args.object.read_bytes())
    print('PASS lay2 layout' + (' and object membership' if args.object else ''))


if __name__ == '__main__':
    main()
