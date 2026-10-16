#!/usr/bin/env python3
"""Check saved original locals against pinned instructions/tables; Reverse owns confirmation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    args = parser.parse_args()
    m = json.loads(args.manifest.read_text())
    root = Path(os.environ['EIDOLON_DATA'])
    image = (root/'reverse/confirmed-debug/postfix-00400000.bin').read_bytes()
    assert hashlib.sha256(image).hexdigest() == 'da9cc65b64aa7d322807d93cb4361bc864a10f00ed47246f5df96fb5b9ecf504'
    f32 = lambda address: np.float32(struct.unpack_from('<f',image,address-0x400000)[0])
    bits = lambda x: struct.unpack('<I',struct.pack('<f',x))[0]
    bpm, divisor, sample_rate = [f32(a) for a in (0x437040,0x436428,0x43642c)]
    beat_rate = np.float32(bpm/divisor)
    rows = [struct.unpack_from('<ff',image,0x42fc50-0x400000+8*i) for i in range(50)]
    tokens = struct.unpack_from('<50I',image,0x42fde0-0x400000)
    path = root/'reference'/m['run_id']/'backend.jsonl'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == m['evidence'][str(path.relative_to(root))]
    events = [json.loads(line) for line in path.read_text().splitlines()]
    scenes = [e for e in events if e['event']=='scene_state']
    boundaries = []
    previous = None
    for e in scenes:
        n = e['n']
        # Original 0x407ba1..0x407be5: unsigned integer -> double -> float;
        # scalar float division by 44100, then scalar float beat multiplication.
        seconds = np.float32(np.float32(float(n*735))/sample_rate)
        beat = np.float32(seconds*beat_rate)
        row = next(i for i,(_,end) in enumerate(rows) if np.float32(end)>beat)
        local = np.float32(beat-np.float32(rows[row][0]))
        assert e['seconds_f32_bits'] == bits(seconds), (n,'seconds')
        assert e['scene_local_beat_f32_bits'] == bits(local), (n,'scene local')
        assert e['scene_token'] == tokens[row], (n,'scene token')
        if row != previous:
            boundaries.append(dict(n=n,row=row,token=tokens[row],seconds=float(seconds),beat=float(beat),
                                   native_seconds_bits=e['seconds_f32_bits'],native_local_beat_bits=e['scene_local_beat_f32_bits']))
            previous = row
    print(json.dumps(dict(status='PRODUCER_RECONCILIATION_ONLY',frames=len(scenes),
                          bpm=float(bpm),beat_divisor=float(divisor),sample_rate=float(sample_rate),
                          transitions=boundaries,reverse_confirmation_required=True,reference_accepted=False)))


if __name__ == '__main__':
    main()
