#!/usr/bin/env python3
"""Query recovered raw tracks (before physics), or verify all controlled samples.

Models SSE scalar float32 operations at 0x407c64..0x407f9c. This is a static
arithmetic model, not native execution evidence or a graphics reference.
"""
import argparse
import json
import math
import os
from pathlib import Path
import struct


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def bits(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


def curve_value(keys, time):
    if len(keys) == 4 or time <= keys[1]:
        return keys[2]
    j = 4
    while j < len(keys)-4 and time > keys[j+1]:
        j += 4
    end = keys[j+1]
    t = f32(f32(min(time, end)-keys[j-3]) / f32(end-keys[j-3]))
    delta = f32(keys[j+2]-keys[j-2])
    m0, m1 = keys[j-1], keys[j]
    a = f32(f32(f32(f32(delta+delta)+delta)-m0)-m0)
    a = f32(a-m1)
    b = f32(f32(f32(m1+m0)-delta)-delta)
    return f32(f32(f32(f32(f32(f32(b*t)+a)*t)+m0)*t)+keys[j-2])


def clock(n):
    seconds = f32(f32(float(735*n))/44100.0)
    return seconds, f32(seconds*f32(80.0/60.0))


def load():
    data = Path(os.environ['EIDOLON_DATA']) / 'analysis/graphics'
    manifest = json.loads((Path(__file__).resolve().parents[3] /
                           'analysis/graphics/assets.json').read_text())
    raw = (data / 'engine-tables.json').read_bytes()
    import hashlib
    assert hashlib.sha256(raw).hexdigest() == manifest['decoded']['sha256']
    tables = json.loads(raw)
    curves = {key: struct.unpack('<'+'f'*len(value['float32_bits']),
              struct.pack('<'+'I'*len(value['float32_bits']), *value['float32_bits']))
              for key,value in tables['curves'].items()}
    return tables, curves


def sample(tables, curves, n):
    seconds, beat = clock(n)
    row = next((r for r in tables['rows'] if beat < r['beats_half_open'][1]), None)
    if row is None:
        return {'n': n, 'seconds': seconds, 'beat': beat, 'row': None, 'uniforms': {}}
    local = f32(beat-row['beats_half_open'][0])
    values = {u['uniform']: [curve_value(curves[c], local) for c in u['curve_refs']]
              for u in row['uniforms']}
    return {'n': n, 'seconds': seconds, 'beat': beat, 'row': row['row'],
            'local_beat': local, 'dt': f32(seconds-clock(n-1)[0]) if n else 0.0,
            'uniforms': values}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frame', type=int, default=0)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    tables, curves = load()
    if args.verify:
        samples = 0
        for n in range(27000):
            result = sample(tables, curves, n)
            row = tables['rows'][result['row']]
            first, end = row['controlled_frames_half_open']
            assert first <= n < end
            for values in result['uniforms'].values():
                assert all(math.isfinite(v) for v in values), (n, result)
                samples += len(values)
        assert sample(tables, curves, 27000)['row'] is None
        # Native lower-segment preference at equal timestamps retains the
        # pre-jump value. A right-biased generic spline would fail this check.
        duplicate = curves['690:112']
        assert bits(curve_value(duplicate, 5.0)) == bits(duplicate[14*4+2])
        assert curve_value(duplicate, f32(5.0+2**-21)) < 0.000001
        print(json.dumps({'status': 'STATIC_TRACK_MODEL_VERIFIED', 'frames': 27000,
                          'scalar_samples': samples, 'native_execution': False}))
    else:
        if not 0 <= args.frame <= 27000:
            parser.error('--frame must be 0..27000')
        print(json.dumps(sample(tables, curves, args.frame), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
