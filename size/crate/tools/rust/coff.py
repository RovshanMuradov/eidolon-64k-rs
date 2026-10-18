"""Small i386 COFF reader and stable anonymous-rdata renamer for the size link."""
import hashlib
import struct


def sections(data):
    if len(data) < 20 or struct.unpack_from('<H', data)[0] != 0x14c:
        raise ValueError('expected a regular i386 COFF object')
    count = struct.unpack_from('<H', data, 2)[0]
    symptr, nsym = struct.unpack_from('<II', data, 8)
    optional = struct.unpack_from('<H', data, 16)[0]
    strtab = symptr + nsym * 18
    if 20 + optional + 40 * count > len(data):
        raise ValueError('truncated COFF section table')
    result = []
    for index in range(count):
        header = 20 + optional + 40 * index
        raw = data[header:header + 8]
        if raw.startswith(b'/'):
            start = strtab + int(raw[1:].rstrip(b'\0'))
            name = data[start:data.index(b'\0', start)].decode('ascii')
        else:
            name = raw.rstrip(b'\0').decode('ascii')
        size, pointer = struct.unpack_from('<II', data, header + 16)
        relocations = struct.unpack_from('<H', data, header + 32)[0]
        if pointer and pointer + size > len(data):
            raise ValueError(f'truncated COFF section {name}')
        result.append(dict(name=name, header=header, size=size, relocations=relocations,
                           content=data[pointer:pointer + size] if pointer else b''))
    return result


def anonymous_digest(section):
    # This definition preserves the recovered lay2 names exactly. Relocation
    # symbol indices are intentionally excluded: they change with crate hashes.
    return hashlib.sha1(section['content'] + struct.pack('<I', section['relocations'])).hexdigest()


def rename_anonymous_rdata(data):
    """Content-derived eight-byte names, independent of section enumeration order.

    A collision is an error, including equal contents. Incrementing a colliding
    hash would silently assign different identities after an object reorder.
    The manifest also records full digests, so a new four-hex prefix collision
    cannot impersonate a previous member.
    """
    entries = sections(data)
    used = {s['name'] for s in entries if s['name'].startswith('.rd$')}
    output = bytearray(data)
    digests = {}
    for section in entries:
        if section['name'] != '.rdata':
            continue
        digest = anonymous_digest(section)
        name = '.rd$' + digest[:4]
        if name in used:
            raise ValueError(f'anonymous-rdata identity collision: {name}; regenerate layout identities explicitly')
        used.add(name)
        digests[name] = digest
        start = section['header']
        output[start:start + 8] = name.encode('ascii')
    return bytes(output), digests
