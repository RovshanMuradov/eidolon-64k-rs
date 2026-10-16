"""Exact native float timeline; row identity is independent of reused tokens."""
import hashlib
import os
from pathlib import Path
import struct

import numpy as np


def timeline():
    image = (Path(os.environ['EIDOLON_DATA'])/'reverse/confirmed-debug/postfix-00400000.bin').read_bytes()
    assert hashlib.sha256(image).hexdigest() == 'da9cc65b64aa7d322807d93cb4361bc864a10f00ed47246f5df96fb5b9ecf504'
    f32 = lambda a: np.float32(struct.unpack_from('<f',image,a-0x400000)[0])
    rate = np.float32(f32(0x437040)/f32(0x436428))
    sample_rate = f32(0x43642c)
    table = [struct.unpack_from('<ff',image,0x2fc50+8*i) for i in range(50)]
    tokens = struct.unpack_from('<50I',image,0x2fde0)
    rows = []
    for n in range(27000):
        seconds = np.float32(np.float32(float(735*n))/sample_rate)
        beat = np.float32(seconds*rate)
        row = next(i for i,(_,end) in enumerate(table) if np.float32(end)>beat)
        if not rows or rows[-1]['row'] != row:
            rows.append(dict(row=row,first=n,last=n,token=tokens[row],start_beat=table[row][0],end_beat=table[row][1]))
        else:
            rows[-1]['last'] = n
    assert len(rows) == 50 and rows[6]['first'] == 5760
    return rows


def retention(count):
    rows = timeline()
    indices = set(range(0,count,60)) | {0,1,2,count-1} | set(range(1438,1443)) | set(range(5758,5763))
    for row in rows:
        indices.update((row['first'],row['last']))
    return rows, sorted(n for n in indices if 0 <= n < count)
