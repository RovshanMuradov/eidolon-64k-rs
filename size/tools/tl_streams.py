"""Split the mode-7 timeline payload of a CG29 blob into its named streams."""
import struct

NAMES = ['track', 'ref', 'count', 'time', 'val', 'sel', 'raw']


def split(payload):
    lengths = struct.unpack_from('<6H', payload, 0)
    pos = 12
    out = {}
    for name, n in zip(NAMES, lengths):
        out[name] = payload[pos:pos + n]
        pos += n
    out['raw'] = payload[pos:]
    return out


def join(streams):
    return b''.join(struct.pack('<H', len(streams[k])) for k in NAMES[:6]) + b''.join(streams[k] for k in NAMES)
