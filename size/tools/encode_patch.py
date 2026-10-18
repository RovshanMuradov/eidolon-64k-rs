#!/usr/bin/env python3
"""Generate size/crate/src/audio/patch_code.rs: an isomorphic relayout of the fixed PATCH.

The root, channel roots and consecutive channel chain walked by voice.rs keep their
original offsets (33 records, ending at word 104). All other records are laid out in BFS
order of first reference; constants are renumbered (mono and stereo regions separately)
in order of first reference. Offsets are only cache identities elsewhere, so the graph and
PCM are unchanged; the check below proves the relayout is a structure-preserving bijection.

Streams (u16 LE): info[RECORDS] | refs[REFS] | modes[MODES] | rest.
ref code: 0 = next new record (BFS), 1..RECORDS = record slot+1,
RECORDS+1 = next new mono constant, RECORDS+2 = next new stereo constant,
RECORDS+3+k = constant k (k<200 mono at 3328+2k, else stereo at 3728+4(k-200)).
"""
import struct
from audio_inputs import CRATE as ROOT, MODE_WORDS as ML, emit, patch_words, records

MONO = list(range(3328, 3728, 2))
STEREO = list(range(3728, 3836, 4))


def size(P, r):
    return 1 + ((P[r] >> 8) & 127) + ML.get(P[r] & 127, 0)


def refs(P, r):
    return P[r + 1:r + 1 + ((P[r] >> 8) & 127)]


def coff(k):
    return 3328 + 2 * k if k < 200 else 3728 + 4 * (k - 200)


def decode(words, N, R, M, rest_len):
    """Mirror of audio::runtime::patch()."""
    info = words[:N]
    starts, at = [], 0
    for w in info:
        starts.append(at); at += 1 + ((w >> 8) & 127) + ML.get(w & 127, 0)
    out = [0] * (at + rest_len)
    ii, mi = N, N + R
    nn, nm, ns = PINNED, 0, 200
    for r in range(N):
        w = info[r]; p = starts[r]; out[p] = w; p += 1
        for _ in range((w >> 8) & 127):
            x = words[ii]; ii += 1
            if x == 0:
                v = starts[nn]; nn += 1
            elif x <= N:
                v = starts[x - 1]
            elif x == N + 1:
                v = coff(nm); nm += 1
            elif x == N + 2:
                v = coff(ns); ns += 1
            else:
                v = coff(x - N - 3)
            out[p] = v; p += 1
        for _ in range(ML.get(w & 127, 0)):
            out[p] = words[mi]; mi += 1; p += 1
    for j in range(rest_len):
        out[at + j] = words[mi + j]
    return out


PINNED = 0


def main():
    global PINNED
    P = patch_words()
    recs = records(P)
    o = 51
    for _ in range(16):
        o += size(P, o)
    pinned = [r for r in recs if r < o]
    PINNED = len(pinned)
    order, placed, q = list(pinned), set(pinned), 0
    while q < len(order):
        for x in refs(P, order[q]):
            if x < 3328 and x not in placed:
                placed.add(x); order.append(x)
        q += 1
    order += [r for r in recs if r not in placed]
    assert len(order) == len(set(order)) == len(recs)
    N = len(order)
    slot = {r: i for i, r in enumerate(order)}
    first = {}
    for r in order:
        for x in refs(P, r):
            if x >= 3328 and x not in first:
                first[x] = len(first)
    cnew = {}
    for region, base in ((MONO, 0), (STEREO, 200)):
        for k, off in enumerate(sorted(region, key=lambda o: (first.get(o, 1 << 30), o))):
            cnew[off] = base + k
    info, codes, modes = [], [], []
    nn, nm, ns, seen = PINNED, 0, 200, set()
    for r in order:
        info.append(P[r])
        for x in refs(P, r):
            if x >= 3328:
                k = cnew[x]
                if x not in seen and k in (nm, ns):
                    seen.add(x)
                    if k < 200:
                        codes.append(N + 1); nm += 1
                    else:
                        codes.append(N + 2); ns += 1
                else:
                    codes.append(N + 3 + k); seen.add(x)
            elif slot[x] == nn and slot[x] >= PINNED:
                codes.append(0); nn += 1
            else:
                codes.append(1 + slot[x])
        k = (P[r] >> 8) & 127
        modes += P[r + 1 + k:r + 1 + k + ML.get(P[r] & 127, 0)]
    consts = [0] * 508
    for off in MONO:
        n = cnew[off]; consts[coff(n) - 3328:coff(n) - 3328 + 2] = P[off:off + 2]
    for off in STEREO:
        n = cnew[off]; consts[coff(n) - 3328:coff(n) - 3328 + 4] = P[off:off + 4]
    rest = consts + P[3836:]
    words = info + codes + modes + rest
    out = decode(words, N, len(codes), len(modes), len(rest))
    # isomorphism check: new offset -> original offset
    newoff = {}
    at = 0
    for r in order:
        newoff[at] = r; at += size(P, r)
    for off in MONO + STEREO:
        newoff[coff(cnew[off])] = off
    assert len(newoff) == len(recs) + len(MONO) + len(STEREO)
    assert len(set(newoff.values())) == len(newoff)
    assert at == 3328 and len(out) == len(P)
    for r in pinned:
        assert newoff.get(r) == r, 'pinned record moved'
    for no, r in newoff.items():
        if r < 3328:
            assert out[no] == P[r]
            k = (P[r] >> 8) & 127
            for a, b in zip(out[no + 1:no + 1 + k], P[r + 1:r + 1 + k]):
                assert newoff[a] == b, 'reference not preserved'
            m = ML.get(P[r] & 127, 0)
            assert out[no + 1 + k:no + 1 + k + m] == P[r + 1 + k:r + 1 + k + m]
        else:
            n = 2 if r < 3728 else 4
            assert out[no:no + n] == P[r:r + n]
    assert out[3836:] == P[3836:]
    code = struct.pack('<%dH' % len(words), *words)
    rs = ['// Generated by size/tools/encode_patch.py from size/crate/src/audio/data.rs PATCH (isomorphic relayout).\n',
          f'pub const RECORDS: usize = {N};\npub const PINNED: usize = {PINNED};\npub const REFS: usize = {len(codes)};\n',
          f'pub const MODES: usize = {len(modes)};\npub const WORDS: usize = {len(P)};\n',
          'pub static MODE_WORDS: [u8; 128] = [' + ','.join(str(ML.get(i, 0)) for i in range(128)) + '];\n',
          f'pub static CODE: [u8; {len(code)}] = [\n']
    for i in range(0, len(code), 32):
        rs.append('    ' + ','.join(map(str, code[i:i + 32])) + ',\n')
    rs.append('];\n')
    emit(ROOT / 'src/audio/patch_code.rs', ''.join(rs))
    print(N, PINNED, len(codes), len(modes), len(rest), len(code))


if __name__ == '__main__':
    main()
