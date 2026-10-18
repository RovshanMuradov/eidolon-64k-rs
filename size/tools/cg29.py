"""CG29 graphics blob: parse and write (format: size/crate/src/compact_graphics/README.md)."""


def uint(b, p):
    v = 0
    for s in range(0, 35, 7):
        if p >= len(b):
            raise ValueError('truncated ULEB32')
        c = b[p]
        p += 1
        if s == 28 and c > 15:
            raise ValueError('ULEB32 overflow')
        v |= (c & 127) << s
        if c < 128:
            if s and c == 0:
                raise ValueError('noncanonical ULEB32')
            return v, p
    raise ValueError('unterminated ULEB32')


def uv(v):
    if type(v) is not int or not 0 <= v <= 0xffffffff:
        raise ValueError('ULEB32 value out of range')
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
    if blob[:6] != b'CG29\x01\x0c':
        raise ValueError('incompatible CG29 magic/version/table count')
    p = 6
    tables = []
    for _ in range(12):
        if p + 2 > len(blob):
            raise ValueError('truncated table header')
        mode, stride = blob[p], blob[p + 1]
        if mode > 7:
            raise ValueError('unknown table mode')
        q = p + 2
        dec, q = uint(blob, q)
        enc, q = uint(blob, q)
        if q + enc > len(blob):
            raise ValueError('truncated table payload')
        tables.append(dict(mode=mode, stride=stride, dec=dec, payload=blob[q:q + enc]))
        p = q + enc
    size, q = uint(blob, p)
    if q + size >= len(blob):
        raise ValueError('truncated shader pool/recipe count')
    pool = blob[q:q + size]
    if not pool or pool[-1:] != b'\0':
        raise ValueError('shader pool must end with NUL')
    frags = pool.split(b'\0')[:-1]
    q += size
    count = blob[q]
    if not count:
        raise ValueError('empty program set')
    q += 1
    recipes = []
    for _ in range(count):
        k, q = uint(blob, q)
        if not k or k > len(blob) - q:
            raise ValueError('invalid recipe length')
        r = []
        for _ in range(k):
            x, q = uint(blob, q)
            if x >= len(frags):
                raise ValueError('recipe fragment index out of range')
            r.append(x)
        recipes.append(r)
    if q != len(blob):
        raise ValueError('trailing bytes after recipes')
    return tables, frags, recipes


def write(tables, frags, recipes):
    if len(tables) != 12 or not frags or not 0 < len(recipes) < 256:
        raise ValueError('invalid table/fragment/program count')
    if any(b'\0' in f for f in frags):
        raise ValueError('embedded NUL in shader fragment')
    for r in recipes:
        if not r or any(type(i) is not int or not 0 <= i < len(frags) for i in r):
            raise ValueError('invalid recipe')
    out = bytearray(b'CG29\x01\x0c')
    for t in tables:
        out += bytes([t['mode'], t['stride']]) + uv(t['dec']) + uv(len(t['payload'])) + t['payload']
    pool = b''.join(f + b'\0' for f in frags)
    out += uv(len(pool)) + pool + bytes([len(recipes)])
    for r in recipes:
        out += uv(len(r)) + b''.join(uv(x) for x in r)
    result = bytes(out)
    parse(result)
    return result
