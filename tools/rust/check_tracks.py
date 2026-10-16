#!/usr/bin/env python3
"""Compare host Rust raw track bits against the pinned pre-port static Python model.

This is CPU model agreement, not a native execution or graphics-equivalence claim.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host_probe', type=Path)
    args = parser.parse_args()
    assert args.host_probe.read_bytes()[:4] == b'\x7fELF', 'CPU checks require the Linux host build, never a PE'
    spec = importlib.util.spec_from_file_location('recovered_timeline', ROOT / 'tools/analysis/graphics/timeline.py')
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    tables, curves = model.load()
    raw = subprocess.check_output([str(args.host_probe), '--raw-stream'])
    assert raw[:8] == b'EIDRAW01'
    offset = 8

    def words(count):
        nonlocal offset
        value = struct.unpack_from('<' + 'I' * count, raw, offset)
        offset += 4 * count
        return value

    scalars = 0
    for n in range(27000):
        expected = model.sample(tables, curves, n)
        row = tables['rows'][expected['row']]
        header = words(8)
        assert header == (n, n * 735, model.bits(expected['seconds']), model.bits(expected['beat']),
                          expected['row'], model.bits(expected['local_beat']), model.bits(expected['dt']), len(row['uniforms'])), (n, header)
        for uniform in row['uniforms']:
            assert words(2) == (uniform['name_index'], uniform['components']), (n, uniform)
            actual = words(uniform['components'])
            expected_bits = tuple(model.bits(v) for v in expected['uniforms'][uniform['uniform']])
            assert actual == expected_bits, (n, uniform['uniform'], actual, expected_bits)
            scalars += uniform['components']
    assert offset == len(raw), (offset, len(raw))
    print(json.dumps({'status': 'RUST_TRACK_BITS_MATCH_STATIC_MODEL', 'frames': 27000,
                      'scalar_samples': scalars, 'stream_bytes': len(raw), 'native_equivalence': False}))


if __name__ == '__main__':
    main()
