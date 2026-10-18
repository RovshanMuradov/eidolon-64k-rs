#!/usr/bin/env python3
"""Bounded insertion search using a captured link and a repo-built t15t packer.

Measures actual trimmed EXE bytes after the production safe constant pass.
Every trial has a validated manifest/script pair. At most four seed evaluations
and 64 proposals; one worker, deterministic seed 20261018. Does not modify the
repository layout or its acceptance hash. Use layout.py --migrate-order on the
resulting best.json to explicitly freeze a result.
"""
import argparse
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'size'))
import build
sys.path.insert(0, str(ROOT / 'size/crate/tools/rust'))
import layout
from coff import rename_anonymous_rdata


def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--link-snapshot', type=Path, required=True,
                        help='unrenamed/ directory captured by EIDOLON_SAVE_LINK')
    parser.add_argument('--packer', type=Path, required=True, help='packer built from size/packer')
    parser.add_argument('--seed', type=Path, action='append', help='old manifest/order JSON (up to four)')
    parser.add_argument('--trials', type=int, default=64)
    parser.add_argument('--seconds', type=int, default=540)
    parser.add_argument('--work', type=Path, default=ROOT / '.build/layout-search')
    args = parser.parse_args()
    seeds = args.seed or [layout.MANIFEST]
    if len(seeds) > 4 or not 0 <= args.trials <= 64 or not 1 <= args.seconds <= 540:
        parser.error('limits: four seeds, 0..64 proposals, 1..540 seconds')
    snapshot, work, packer = args.link_snapshot.resolve(), args.work.resolve(), args.packer.resolve()
    work.mkdir(parents=True, exist_ok=True)
    saved = json.loads((snapshot / 'link.json').read_text())
    objects = {str(p): snapshot / Path(p).name for p in saved['objects']}
    runtime = [p for p in objects.values() if p.name.startswith('eidolon_runtime-') and p.suffix == '.o']
    if len(runtime) != 1:
        raise SystemExit('expected one unrenamed runtime COFF object in the snapshot')
    original = runtime[0].read_bytes()
    renamed, _ = rename_anonymous_rdata(original)
    runtime_path = work / (runtime[0].stem + '.rd.o')
    runtime_path.write_bytes(renamed)
    link_args = []
    for arg in saved['args']:
        if arg.startswith('-Wl,-T,') or arg.startswith('-Wl,-Map,'):
            continue
        if arg in objects:
            path = objects[arg]
            arg = str(runtime_path if path == runtime[0] else path)
        link_args.append(arg)
    output_index = link_args.index('-o') + 1
    # The GNU linker embeds this basename in .edata; keep rustc's original name.
    linked = work / Path(link_args[output_index]).name
    link_args[output_index] = str(linked)
    script_base = layout.SCRIPT.read_text()
    script, map_file = work / 'trial.ld', work / 'trial.map'
    input_pe, packed_pe = work / 'input.exe', work / 'packed.exe'
    env = dict(os.environ, WINEPREFIX=str(work / 'wine-prefix'), WINEARCH='win64', WINEDEBUG='-all',
               WINEDLLOVERRIDES='winemenubuilder.exe,mscoree,mshtml=d')
    env.pop('KK_DUMP', None)
    win = lambda p: 'Z:' + str(p).replace('/', '\\')
    history = []
    started = time.monotonic()

    def run(argv):
        result = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=90)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout

    def measure(state):
        layout.validate(renamed, state)
        script.write_text(layout.render(script_base, state))
        run(['i686-w64-mingw32-gcc', '-nostdlib', *link_args, f'-Wl,-T,{script}', f'-Wl,-Map,{map_file}'])
        merge_log = run([sys.executable, str(ROOT / 'size/crate/tools/rust/merge-constants'), str(linked)])
        unprepared = linked.read_bytes()
        prepared = build.prepare(unprepared)
        input_pe.write_bytes(prepared)
        packed_pe.unlink(missing_ok=True)
        run(['wine', str(packer), '--out', win(packed_pe), win(input_pe)])
        exe = build.trim(packed_pe.read_bytes())
        return unprepared, prepared, exe, merge_log.strip()

    def save_best(state, measured):
        unprepared, prepared, exe, _ = measured
        (work / 'best.json').write_text(json.dumps(state, indent=2) + '\n')
        (work / 'best.ld').write_text(layout.render(script_base, state))
        (work / 'best-unprepared.exe').write_bytes(unprepared)
        (work / 'best-input.exe').write_bytes(prepared)
        (work / 'best.exe').write_bytes(exe)
        shutil.copyfile(map_file, work / 'best.map')

    best, state = None, None
    for index, seed in enumerate(seeds):
        proposal, changes = layout.migrate_order(json.loads(seed.read_text()), original)
        measured = measure(proposal)
        record = {'seed': index, 'name': seed.name, 'migration': changes,
                  'delivered': identity(measured[2]), 'unprepared': identity(measured[0]),
                  'constant_pass': measured[3]}
        history.append(record)
        print(f'SEED {index} {seed.name}: {len(measured[2])} bytes', flush=True)
        if best is None or len(measured[2]) < best:
            best, state = len(measured[2]), proposal
            save_best(state, measured)
    rng = random.Random(20261018)
    proposals = 0
    for trial in range(args.trials):
        if time.monotonic() - started >= args.seconds:
            break
        key = 'text' if trial < 48 else 'rdata'
        i, j = rng.sample(range(len(state[key])), 2)
        order = list(state[key])
        item = order.pop(i)
        order.insert(j, item)
        proposal = dict(state, **{key: order})
        measured = measure(proposal)
        proposals += 1
        record = {'trial': trial, 'kind': key, 'from': i, 'to': j, 'member': item,
                  'bytes': len(measured[2]), 'improved': len(measured[2]) < best}
        if record['improved']:
            best, state = len(measured[2]), proposal
            save_best(state, measured)
            record['sha256'] = identity(measured[2])['sha256']
            print('IMPROVED ' + json.dumps(record), flush=True)
        history.append(record)
        (work / 'history.json').write_text(json.dumps(history, indent=2) + '\n')
    # Validate the claimed GC-discarded members against the final link map.
    retained = (work / 'best.map').read_text().split('Linker script and memory map', 1)[-1]
    for pat in state['discarded']:
        entries = re.findall(r'^ (\.[^\s]+)(?:\s|$)', retained, flags=re.M)
        if any(fnmatchcase(name, pat) for name in entries):
            raise SystemExit(f'claimed discarded section is retained: {pat}')
    report = {'seed': 20261018, 'seed_measurements': len(seeds), 'proposal_measurements': proposals,
              'elapsed_seconds': round(time.monotonic() - started, 3),
              'delivered': identity((work / 'best.exe').read_bytes()),
              'unprepared': identity((work / 'best-unprepared.exe').read_bytes()),
              'manifest': identity((work / 'best.json').read_bytes()),
              'script': identity((work / 'best.ld').read_bytes()),
              'packer': identity(packer.read_bytes())}
    (work / 'history.json').write_text(json.dumps(history, indent=2) + '\n')
    (work / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print('FINAL ' + json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
