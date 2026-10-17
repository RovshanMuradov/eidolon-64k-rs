#!/usr/bin/env python3
"""Generate size/crate/src/audio/score_code.rs from the recovered SCORE in size/crate/src/audio/data.rs.

Stored layout: header[16] | infos (u32) | 0xFFFFFFFF | plane p of every stream for p in 0..5,
where note-off streams (kind 0) store only plane 2, then for every note-on stream (kind 1)
the duration planes (lo, hi) in note-on order.
- Plane 2 holds timing residuals against floor((ticks*33075 - BIAS[kind])/4096).
- Note-off streams are derived from the following note-on stream of the same channel: FIFO
  pairing per note value gives each note-on a duration; offs are the note-ons sorted by
  (on tick + duration, note value or, for channel 0, note-on index). audio::score::Scheduler::fixed
  mirrors `decode` below; `main` asserts the decoded scheduler data equals the (canonicalized) original.

Dead data is canonicalized first, from a static walk of the fixed PATCH graph (`liveness`):
- controller streams whose MIDI slot (channel*128+cc) no MIDI node (opcode 29) reads are dropped;
- note-on velocities that cannot reach a voice VELOCITY node (opcode 67) are replaced: notes routed
  to arpeggiating voice managers (the arpeggiator supplies its own velocities), to voice managers
  whose voice graph has no VELOCITY node, or to no voice manager at all. A dead velocity repeats the
  previous live one of its stream; streams without any live velocity use DEAD_VELOCITY.
Note-off velocities are never stored. The full host PCM comparison is the proof that this is exact.

The original encoder (planes, floor predictors, derived note-offs) is tools/optimize/audio_score/encode.py
of the private research repository; this file adds the liveness pass.
"""
import collections
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'crate'
DEAD_VELOCITY = 100
CONSTANT_OFFSET = 3328
BIAS = {0: 8788, 1: 0, 3: 0}


def parse(S):
    at, streams = 16, []
    while True:
        info = struct.unpack_from('<I', S, at)[0]; at += 4
        if info == 0xffffffff:
            break
        n = info & 65535; stride = 5 if (info >> 24) & 15 == 1 else 4
        streams.append((info, [bytearray(S[at + i * n:at + (i + 1) * n]) for i in range(stride)]))
        at += n * stride
    assert at == len(S)
    return streams


def ticks_of(pl):
    t, out = 0, []
    for i in range(len(pl[0])):
        t += pl[0][i] | pl[1][i] << 8
        out.append(t)
    return out


def sort_key(ch, ticks, dur, vals):
    return lambda j: (ticks[j] + dur[j], j if ch == 0 else (vals[j] << 16) | j)


def expanded(streams, bias):
    """Scheduler data after tick expansion: per stream planes, lanes 0..2 = 24-bit stamp."""
    out = bytearray()
    for info, pl in streams:
        n = info & 65535; kind = (info >> 24) & 15
        pl = [bytearray(p) for p in pl]
        t = 0
        for i in range(n):
            t += pl[0][i] | pl[1][i] << 8
            r = pl[2][i] - 256 if pl[2][i] > 127 else pl[2][i]
            stamp = (((t * 33075 + 2048) >> 12) if bias is None else ((t * 33075 - bias[kind]) >> 12)) + r
            for lane in range(3):
                pl[lane][i] = (stamp >> (8 * lane)) & 255
        out += b''.join(pl)
    return bytes(out)


def encode(streams):
    # residuals against the floor predictors
    for info, pl in streams:
        kind = (info >> 24) & 15
        for i, t in enumerate(ticks_of(pl)):
            r = pl[2][i] - 256 if pl[2][i] > 127 else pl[2][i]
            q = ((t * 33075 + 2048) >> 12) + r - ((t * 33075 - BIAS[kind]) >> 12)
            assert -128 <= q < 128 and t * 33075 >= BIAS[kind]
            pl[2][i] = q & 255
    durations = {}
    for k, (info, pl) in enumerate(streams):
        if (info >> 24) & 15 != 0:
            continue
        on_info, on = streams[k + 1]
        assert on_info >> 28 == info >> 28 and (on_info >> 24) & 15 == 1 and (on_info ^ info) & 0xffff == 0
        n = info & 65535
        ton, toff = ticks_of(on), ticks_of(pl)
        pending, dur, order = collections.defaultdict(collections.deque), [None] * n, []
        events = sorted([(t, 1, i) for i, t in enumerate(ton)] + [(t, 0, i) for i, t in enumerate(toff)])
        for t, ison, i in events:
            if ison:
                pending[on[3][i]].append(i)
            else:
                j = pending[pl[3][i]].popleft(); dur[j] = toff[i] - ton[j]; order.append((i, j))
        assert all(d is not None and 0 <= d < 65536 for d in dur) and max([ton[j] + dur[j] for j in range(n)] + [0]) < 65536
        assert max(on[3] + b"\0") < 128
        regen = sorted(range(n), key=sort_key(info >> 28, ton, dur, on[3]))
        # the derived off order must reproduce the original one, including residual alignment
        assert [toff[i] for i, _ in sorted(order)] == [ton[j] + dur[j] for j in regen]
        assert bytes(pl[3]) == bytes(on[3][j] for j in regen)
        durations[k + 1] = dur
    out = bytearray(b'')
    for p in range(5):
        for info, pl in streams:
            if len(pl) > p and ((info >> 24) & 15 != 0 or p == 2):
                out += pl[p]
    for k, (info, pl) in enumerate(streams):
        if k in durations:
            out += bytes(d & 255 for d in durations[k]) + bytes(d >> 8 for d in durations[k])
    return out


def decode(header, infos, body):
    """Python mirror of Scheduler::fixed (before tick expansion)."""
    streams = []
    for info in infos:
        n = info & 65535; stride = 5 if (info >> 24) & 15 == 1 else 4
        streams.append((info, [bytearray(n) for _ in range(stride)]))
    q = 0
    for p in range(5):
        for info, pl in streams:
            if len(pl) > p and ((info >> 24) & 15 != 0 or p == 2):
                n = info & 65535; pl[p][:] = body[q:q + n]; q += n
    for k, (info, pl) in enumerate(streams):
        if (info >> 24) & 15 != 1 or k == 0 or (streams[k - 1][0] >> 24) & 15 != 0:
            continue
        n = info & 65535
        dur = [body[q + i] | body[q + n + i] << 8 for i in range(n)]; q += 2 * n
        off = streams[k - 1][1]
        ton = ticks_of(pl)
        regen = sorted(range(n), key=sort_key(info >> 28, ton, dur, pl[3]))
        prev = 0
        for i, j in enumerate(regen):
            t = ton[j] + dur[j]
            off[0][i], off[1][i] = (t - prev) & 255, (t - prev) >> 8; prev = t
            off[3][i] = pl[3][j]
    assert q == len(body)
    return streams



def liveness(P):
    """MIDI slots read by opcode-29 nodes, and per channel the voice managers as (low, high, velocity_live)."""
    def node(o):
        info = P[o]; refs = (info >> 8) & 127
        return info & 127, refs, P[o + 1:o + 1 + refs]
    def reach(o, seen):
        stack = [o]
        while stack:
            o = stack.pop()
            if o in seen or o >= CONSTANT_OFFSET: continue
            seen.add(o); stack += node(o)[2]
    everything = set(); reach(0, everything)
    read_cc = {P[o + 1 + node(o)[1]] for o in everything if node(o)[0] == 29}
    managers, offset = {}, 3 + 16 * 3
    for channel in range(16):
        ranges = []
        for vm in node(offset)[2]:
            assert node(vm)[0] == 3
            refs = node(vm)[1]
            mode = P[vm + 1 + refs] | P[vm + 2 + refs] << 16
            voice = set(); reach(P[vm + 1], voice)
            velocity = mode & 0xf0000 == 0 and any(node(o)[0] == 67 for o in voice)
            ranges.append((mode & 255, (mode >> 8) & 255, velocity))
        managers[channel] = ranges
        offset += node(offset)[1] + 1
    return read_cc, managers


def canonicalize(streams, P):
    read_cc, managers = liveness(P)
    def live(channel, note):
        # eidolon_note delivers to the last matching manager in input order
        for low, high, velocity in reversed(managers[channel]):
            if low <= note <= high: return velocity
        return False
    out = []
    for info, pl in streams:
        kind, channel, special = (info >> 24) & 15, info >> 28, (info >> 16) & 255
        if kind == 3:
            assert special < 112  # controller numbers >= 112 would trigger notes
            if channel * 128 + special not in read_cc: continue
        if kind == 1:
            known = [pl[4][i] for i in range(len(pl[4])) if live(channel, pl[3][i])]
            last = known[0] if known else DEAD_VELOCITY
            for i in range(len(pl[4])):
                if live(channel, pl[3][i]): last = pl[4][i]
                else: pl[4][i] = last
        out.append((info, pl))
    return out


def main():
    s = (ROOT / 'src/audio/data.rs').read_text()
    S = bytes(int(v) for v in re.search(r'pub static SCORE: &\[u8\] = &\[(.*?)\];', s, re.S).group(1).replace('\n', '').split(',') if v.strip())
    P = [int(v) for v in re.search(r'pub static PATCH: &\[u16\] = &\[(.*?)\];', s, re.S).group(1).replace('\n', '').split(',') if v.strip()]
    streams = canonicalize(parse(S), P)
    reference = expanded([(i, [bytearray(p) for p in pl]) for i, pl in streams], None)
    infos = [info for info, _ in streams]
    decoded = sum(len(pl) * len(pl[0]) for _, pl in streams)
    body = encode(streams)
    out = S[:16] + b''.join(struct.pack('<I', i) for i in infos) + b'\xff' * 4 + body
    assert expanded(decode(S[:16], infos, body), BIAS) == reference
    rs = ['// Generated by size/tools/encode_score.py from src/audio/data.rs SCORE (planes, derived note-offs, dead data canonicalized).\n',
          f'pub const STREAMS: usize = {len(infos)};\n', f'pub const DECODED: usize = {decoded};\n',
          f'pub const MAX_NOTES: usize = {max(i & 65535 for i in infos if (i >> 24) & 15 == 1)};\n',
          f'pub static SCORE: [u8; {len(out)}] = [\n']
    for i in range(0, len(out), 32):
        rs.append('    ' + ','.join(map(str, out[i:i + 32])) + ',\n')
    rs.append('];\n')
    (ROOT / 'src/audio/score_code.rs').write_text(''.join(rs))
    print(len(infos), len(out), decoded)


if __name__ == '__main__':
    main()
