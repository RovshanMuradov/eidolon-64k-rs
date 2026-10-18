#!/usr/bin/env python3
"""Offline corruption controls using a pinned, already-closed native-exact ledger.

These checks exercise the inherited verifier with observed evidence and deliberate
late-frame corruption. They never execute a candidate or modify reference files.
"""
import argparse
import hashlib
from pathlib import Path
import shutil
import struct
import tempfile

from verify import Oracle, ROOT, checked, inputs, load, need, process_exit, sha, write


def run(args):
    oracle = Oracle(args.config)
    job = args.reference_job.resolve()
    state = load(checked(job / 'state.json', args.reference_state_sha256))
    need(state['phase'] == 'closed' and state['exit_code'] == 0 and state['full'], 'closed full control source')
    ledger = checked(job / 'output/events.bin', state['output']['output/events.bin']['sha256']).read_bytes()
    records, pending = oracle.m.bounded_records(ledger, True)
    observed, _ = oracle.m.prefix(records, oracle.native, oracle.times)
    need(not pending and observed['matching_frame_hashes'] == 27000 and
         observed['queries'] == 27001 and observed['endpoint'] and observed['terminal_stability'], 'positive full-ledger control')
    results = ['observed full ledger: 27000 exact frames and natural endpoint']
    log = checked(job / 'runner.log', state['runner_log_sha256']).read_text()
    need(process_exit(log, 0)['clean'], 'positive closed-process control')
    results.append('observed clean child/Wine/Gamescope closure')
    bad = log.replace('GAMESCOPE_EXIT=0', 'GAMESCOPE_EXIT=139')
    need(not process_exit(bad, 0)['clean'], 'Gamescope failure masked by child exit zero')
    results.append('Gamescope 139 rejected despite child/Wine zero')
    need(not process_exit('WINE_EXIT=0 GAMESCOPE_EXIT=0 SECONDS=1\n' + bad, 0)['clean'], 'earlier clean wrapper line masks later failure')
    results.append('earlier clean wrapper line cannot mask failing closure')
    need(not process_exit(log + 'CHILD_EXIT 0 stages=111\n', 0)['clean'], 'duplicate child closure')
    results.append('duplicate child closure rejected')

    def rejects(label, operation):
        try:
            operation()
        except ValueError:
            results.append(label)
        else:
            raise ValueError('false acceptance: ' + label)

    for label, bad in [('truncated final record', ledger[:-1]),
                       ('extra trailing bytes', ledger + b'\0'),
                       ('wrong magic', b'X' + ledger[1:])]:
        rejects(label, lambda bad=bad: oracle.m.bounded_records(bad, True))
    raw = bytearray(ledger)
    struct.pack_into('<I', raw, 8, 2)
    rejects('record sequence gap', lambda: oracle.m.bounded_records(raw, True))
    raw = bytearray(ledger)
    first_tid = struct.unpack_from('<I', raw, 12)[0]
    struct.pack_into('<I', raw, 8 + 16 + 32 + 4, first_tid + 1)
    rejects('mixed capture thread', lambda: oracle.m.bounded_records(raw, True))

    def changed(index, byte):
        altered = list(records)
        kind, payload = altered[index]
        payload = bytearray(payload)
        payload[byte] ^= 1
        altered[index] = kind, bytes(payload)
        return altered

    frame = 13365
    altered = changed(3 + 5*frame + 3, 4)
    mismatch, _ = oracle.m.prefix(altered, oracle.native, oracle.times)
    need(mismatch['frame_mismatches'] == 1 and mismatch['first_frame_mismatch']['n'] == frame,
         'late-frame hash corruption attribution')
    results.append(f'late-frame hash corruption located at frame {frame}, sample {frame*735}')
    altered = changed(3 + 5*frame, 8)
    # Keep the query/pre/post witnesses internally consistent: the native oracle
    # must still reject the fabricated time, rather than only a snapshot mismatch.
    payload = altered[3 + 5*frame][1]
    altered[3 + 5*frame + 1] = 3, payload
    altered[3 + 5*frame + 4] = 4, payload
    mismatch, _ = oracle.m.prefix(altered, oracle.native, oracle.times)
    need(mismatch['time_mismatches'] == 1 and mismatch['first_time_mismatch']['n'] == frame,
         'late-frame native-time corruption attribution')
    results.append('internally consistent fabricated native time rejected')
    rejects('query/pre/post mismatch', lambda: oracle.m.prefix(changed(3 + 5*frame + 4, 28), oracle.native, oracle.times))
    rejects('initial PCM digest corruption', lambda: oracle.m.prefix(changed(0, 0), oracle.native, oracle.times))
    rejects('terminal PCM stability corruption', lambda: oracle.m.prefix(changed(len(records)-1, 0), oracle.native, oracle.times))
    rejects('terminal cursor corruption', lambda: oracle.m.prefix(changed(len(records)-2, 4), oracle.native, oracle.times))
    rejects('initial physics corruption', lambda: oracle.m.prefix(changed(2, 28), oracle.native, oracle.times))

    for n, expected in oracle.physics:
        need(records[3+5*n][1][28:] == expected, f'positive sampled physics control {n}')
    results.append('observed ledger matches all 151 native physics samples')
    scratch = ROOT / '.build/verify-contracts'
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as temporary:
        output = Path(temporary)
        record = oracle.native.frames[-1]
        source = oracle.native.directory / record['raw_zst']
        import zstandard
        raw = bytearray(zstandard.ZstdDecompressor().decompress(source.read_bytes()))
        need(hashlib.sha256(raw).hexdigest() == record['sha256'], 'positive native raw control')
        raw[3] ^= 1  # Alpha, not an RGB tolerance test.
        target = output / 'alpha-mutated.raw'
        target.write_bytes(raw)
        rejects('terminal raw alpha-byte corruption', lambda: oracle.m.exact_retained(source, target, record['sha256']))
        (output / 'before.bin').write_bytes(bytes(512))
        fp = bytearray(512)
        fp[24] = 0x40
        (output / 'after.bin').write_bytes(fp)
        rejects('physical MXCSR restoration corruption', lambda: oracle.physical(output, 'FP', 'before.bin', 'after.bin', [(0, 512)]))
        if args.manifest:
            manifest, files = inputs(args.manifest, oracle)
            results.append('candidate manifest/preparation identity verified')
            bundle = output / 'bundle'
            bundle.mkdir()
            for role, source in files.items():
                shutil.copyfile(source, bundle / manifest['files'][role]['path'])
            prepared = bundle / manifest['files']['prepared']['path']
            raw = bytearray(prepared.read_bytes())
            pe = oracle.pe(prepared)
            raw[pe.offset(pe.entry)] ^= 1
            prepared.write_bytes(raw)
            # Rehashing an altered prepared PE must not bypass the independent
            # whole-file preparation transform check.
            manifest['files']['prepared']['sha256'] = sha(prepared)
            path = bundle / 'candidate.json'
            write(path, manifest)
            rejects('repinned prepared-code corruption', lambda: inputs(path, oracle))
    return dict(status='OFFLINE_CORRUPTION_CONTROLS_PASS', checks=len(results), results=results,
                checker_sha256=sha(__file__),
                candidate_manifest_sha256=sha(args.manifest) if args.manifest else None,
                candidate_sha256=load(args.manifest)['files']['candidate']['sha256'] if args.manifest else None,
                reference_state_sha256=args.reference_state_sha256,
                ledger_sha256=state['output']['output/events.bin']['sha256'],
                reference_manifest_sha256=oracle.provenance['reference_manifest_sha256'],
                production_accepted=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--reference-job', type=Path, required=True)
    parser.add_argument('--reference-state-sha256', required=True)
    parser.add_argument('--manifest', type=Path, help='also check a real candidate bundle and a repinned code mutation')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args)
    write(args.output, result)
    print(f"{result['status']}: {result['checks']} checks")
