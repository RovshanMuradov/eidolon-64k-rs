"""CG29 graphics blob: parse and write (format: size/crate/src/compact_graphics/README.md)."""


def uint(b, p):
    v = s = 0
    while True:
        c = b[p]
        p += 1
        v |= (c & 127) << s
        s += 7
        if c < 128:
            return v, p


def uv(v):
    o = bytearray()
    while True:
        c = v & 127
        v >>= 7
        if v:
            o.append(c | 128)
        else:
            o.append(c)
            return bytes(o)


def parse(blob):
    """Return (tables, fragments, recipes); tables are dicts with mode, stride, dec, payload."""
    assert blob[:6] == b'CG29\x01\x0c'
    p = 6
    tables = []
    for _ in range(12):
        mode, stride = blob[p], blob[p + 1]
        q = p + 2
        dec, q = uint(blob, q)
        enc, q = uint(blob, q)
        tables.append(dict(mode=mode, stride=stride, dec=dec, payload=blob[q:q + enc]))
        p = q + enc
    size, q = uint(blob, p)
    frags = blob[q:q + size].split(b'\0')[:-1]
    q += size
    count = blob[q]
    q += 1
    recipes = []
    for _ in range(count):
        k, q = uint(blob, q)
        r = []
        for _ in range(k):
            x, q = uint(blob, q)
            r.append(x)
        recipes.append(r)
    assert q == len(blob)
    return tables, frags, recipes


def write(tables, frags, recipes):
    out = bytearray(b'CG29\x01\x0c')
    for t in tables:
        out += bytes([t['mode'], t['stride']]) + uv(t['dec']) + uv(len(t['payload'])) + t['payload']
    pool = b''.join(f + b'\0' for f in frags)
    out += uv(len(pool)) + pool + bytes([len(recipes)])
    for r in recipes:
        out += uv(len(r)) + b''.join(uv(x) for x in r)
    return bytes(out)
