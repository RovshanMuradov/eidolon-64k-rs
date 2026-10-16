#!/usr/bin/env python3
"""Bounded source/native kernel audit, static event/sample closure and saved RNG check."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest', type=Path)
    args = ap.parse_args()
    root, data = Path(os.environ['EIDOLON_ROOT']), Path(os.environ['EIDOLON_DATA'])
    previous = json.loads(Path('analysis/audio/manifest.json').read_text())
    base = data / 'analysis/audio/T19'
    image = (data / previous['inputs']['postfix']['path']).read_bytes()
    assert sha(image) == previous['inputs']['postfix']['sha256']
    nodes_bytes, events_bytes = (base / 'nodes.json').read_bytes(), (base / 'events.json').read_bytes()
    assert sha(nodes_bytes) == previous['patch']['nodes_sha256']
    assert sha(events_bytes) == previous['song']['events_sha256']
    nodes = {n['offset_words']: n for n in json.loads(nodes_bytes)}
    events = json.loads(events_bytes)
    patch = image[0x3edf0:0x40c30]
    mode = lambda node: struct.unpack_from('<I', patch, node['mode_word_offset'] * 2)[0]
    constants = previous['patch']['mono_offset_words']
    controllers, at = [], 51
    for channel in range(16):
        node = nodes[at]
        assert node['id'] == 2
        controllers.append(node)
        at += len(node['refs']) + 1
    routing, missed, active = Counter(), [], set()
    for e in events:
        if e['type'] == 3:
            assert e['special'] < 112  # no extra MIDI-CC-trigger notes in this score
            continue
        target = None
        for offset in reversed(controllers[e['channel']]['refs']):
            n = nodes[offset]
            assert n['id'] == 3
            flags = mode(n)
            if (flags & 255) <= e['value'] <= ((flags >> 8) & 255):
                target = offset
                break
        if target is None:
            missed.append(e)
        else:
            routing[target, e['type']] += 1
            if e['type'] == 1:
                active.add(target)
    assert not missed
    managers = []
    for channel, controller in enumerate(controllers):
        for offset in controller['refs']:
            n, flags = nodes[offset], mode(nodes[offset])
            managers.append({'channel': channel, 'offset': offset, 'mode': hex(flags),
                             'note_range': [flags & 255, (flags >> 8) & 255],
                             'on_count': routing[offset, 1], 'off_count': routing[offset, 0],
                             'arpeggiator': bool(flags & 0xf0000)})

    def closure(roots, prune=False):
        seen, queue = set(), list(roots)
        while queue:
            offset = queue.pop()
            if offset in seen or offset >= constants:
                continue
            seen.add(offset)
            n = nodes[offset]
            refs = n['refs']
            if prune and n['id'] == 3 and offset not in active:
                refs = refs[1:]  # voice-root edge instantiated only after a routed note
            queue.extend(refs)
        return seen

    roots = [0] + [n['offset_words'] for n in controllers]
    full, event_reachable = closure(roots), closure(roots, True)
    assert full == set(nodes)
    gmdls = lambda offsets: sorted({mode(nodes[o]) & 65535 for o in offsets if nodes[o]['id'] == 52})
    samples = []
    for offset, n in nodes.items():
        if n['id'] == 42:
            parent = nodes[n['refs'][0]]
            assert parent['id'] == 52 and (mode(n) & 7) == 1
            samples.append({'sampler': offset, 'mode_low16': mode(n) & 65535,
                            'gmdls_node': parent['offset_words'], 'sample': mode(parent) & 65535,
                            'event_reachable': offset in event_reachable})
    assert set(gmdls(full)) == {s['sample'] for s in samples}
    assert not any(n['id'] in (41, 50, 54, 56) for n in nodes.values())

    # Pins bind reviewed arithmetic/control instruction ranges to this snapshot.
    reviewed = {
        'MUL': (0x403726, 0x40376e, 'mulpd'), 'ADD': (0x40376e, 0x4037b6, 'addpd'),
        'SUB': (0x4037b6, 0x4037fe, 'subpd'), 'MIN': (0x4037fe, 0x403846, 'minpd'),
        'MAX': (0x403846, 0x40388e, 'maxpd'), 'NEG': (0x40388e, 0x4038c8, 'xorps'),
        'DIV': (0x4038c8, 0x403920, 'divpd'), 'CLIP': (0x403920, 0x40397e, 'minpd'),
        'MIX': (0x40397e, 0x4039df, 'subpd'), 'MONO': (0x4039df, 0x403a22, 'movhlps'),
        'ENVFOLLOWER': (0x403a22, 0x403b3d, 'blendvpd'),
        'COMPARE': (0x403b3d, 0x403bd0, 'cmpneqpd'),
        'EVENTSIGNAL': (0x403bd0, 0x403c13, 'cmpneqpd'),
        'PROCESS': (0x403c13, 0x403c6f, 'ptest'),
        'MIDISIGNAL': (0x403c6f, 0x403c97, 'mulpd'),
        'GMDLS': (0x405b12, 0x405b62, 'movzx'),
        'VOICEPARAM': (0x405dbe, 0x405de9, 'mulpd')}
    source_dir = root / '.tools/analysis/audio/64klang'
    src = {}
    for name in ('sample_t.h', 'sample_t.cpp', 'SynthNode.cpp'):
        raw = subprocess.check_output(['git', '-C', str(source_dir), 'show',
                                        f"{previous['source']['commit']}:Player/Player/{name}"])
        assert sha(raw) == previous['source']['files'][name]
        src[name] = raw.decode()
    assembly = subprocess.check_output(['objdump', '-D', '-b', 'binary', '-m', 'i386', '-Mintel',
                                       '--adjust-vma=0x400000', '--start-address=0x401000',
                                       '--stop-address=0x408647', str(base / 'postfix-copy.bin')], text=True)
    instructions = []
    for line in assembly.splitlines():
        m = re.match(r'\s*([0-9a-f]+):\s+(?:[0-9a-f]{2} )+\s*(\w+)\s*(.*)', line)
        if m:
            instructions.append((int(m[1], 16), m[2], m[3]))
    audit = []
    aliases = {'SYNTHROOT': 'MUL', 'MULTIADD': 'NOTECONTROLLER',
               'VOICE_NOTE': 'VOICEPARAM', 'VOICE_ATTACKVELOCITY': 'VOICEPARAM'}
    for name in sorted({n['name'] for n in nodes.values()}):
        entries = [n for n in nodes.values() if n['name'] == name]
        function = aliases.get(name, name)
        tick = int(entries[0]['tick_va'], 16)
        match = re.search(r'void SYNTHCALL ' + function + r'_tick\(SynthNode\* n\)', src['SynthNode.cpp'])
        assert match, name
        line = src['SynthNode.cpp'][:match.start()].count('\n') + 1
        item = {'node_type': name, 'count': len(entries), 'tick': hex(tick),
                'source_function': function + '_tick', 'source_line': line,
                'status': 'dispatch/graph mapped; detailed numeric audit pending'}
        if function in reviewed:
            start, end, opcode = reviewed[function]
            assert tick == start
            body = [i for i in instructions if start <= i[0] < end]
            assert any(i[1] == opcode for i in body)
            assert body[-1][1] == 'ret'
            item.update(status='reviewed operation/control correspondence; not PCM proof',
                        native_end_exclusive=hex(end), native_sha256=sha(image[start-0x400000:end-0x400000]))
        if name in ('SAMPLER', 'GLITCH'):
            item['status'] = 'sample source / RNG subpaths reviewed; whole-kernel numeric audit pending'
        if name == 'VOICEMANAGER':
            item['status'] = 'note queues, low-byte note-off and guarded voice creation reviewed; numeric audit pending'
        if name == 'OSCILLATOR':
            item['status'] = 'wrapper input order, 16-sample updates, seven-call random-phase init and unison loop reviewed; Osc_Tick helper pending'
        audit.append(item)
    assert struct.unpack_from('<I', image, 0x96c0 + 49 * 4)[0] == 0x40514d
    assert struct.unpack_from('<I', image, 0x96c0 + 42 * 4)[0] == 0x404dd0
    critical_pins = {0x401d6a: '0fb67c8640',  # off queue reads only note byte
                     0x402024: '83be8401000000',  # on-count guards voice creation
                     0x401fe2: '0fb74c4802',  # voice root comes from first patch reference
                     0x40206f: '8b0085c0',  # active count guards ticking voices
                     0x402c90: '8b4614240f3c01',  # (tick & 15) == 1
                     0x402d1d: '6a078d56605f',  # seven random-phase initializations
                     0x401771: 'ff1510904000'}  # zero-initializing allocator call
    for address, encoding in critical_pins.items():
        assert image[address-0x400000:address-0x400000+len(bytes.fromhex(encoding))].hex() == encoding
    # Closed direct-call inventory in the reviewed initialized application code.
    note_calls = [hex(pc) for pc, op, arg in instructions if op == 'call' and arg == '0x4012eb']
    assert note_calls == ['0x401538', '0x401552', '0x4015a7']

    manifest_path = Path('artifacts/reference/proxy-b-d12-volume-20261016.json')
    saved = json.loads(manifest_path.read_text())
    run = data / 'reference' / saved['run_id']
    pin_records = {}

    def checked(path):
        raw = path.read_bytes()
        key = str(path.relative_to(data))
        assert sha(raw) == saved['evidence'][key]
        pin_records[key] = {'bytes': len(raw), 'sha256': sha(raw)}
        return raw

    node_state = checked(run / 'node-state.bin')
    log = checked(run / 'backend.jsonl')
    observations = [json.loads(line) for line in log.splitlines() if b'"event":"node_rng"' in line]
    assert len(observations) == 24 and [e['kind'] for e in observations] == [0]*22 + [1, 2]
    for i, e in enumerate(observations):
        assert e['offset'] == 48 * i and e['bytes'] == 48
        assert sha(node_state[e['offset']:e['offset'] + 48]) == e['sha256']
    assert observations[-2]['activation'] == observations[-1]['activation'] == 22
    assert observations[-2]['tick'] == observations[-1]['tick'] == 17463553
    probe = base / 'source-probe'
    probe.mkdir(exist_ok=True)
    # Only platform headers/calling-convention spelling change; numerical source is intact.
    header = src['sample_t.h'].replace('#include <intrin.h>', '#include <immintrin.h>\n#define _MM_ALIGN16\n#define __int64 long long\n#define __fastcall')
    implementation = src['sample_t.cpp'].replace('#include "SynthNode.h"', '#define SYNTH_SAMPLERATE 44100')
    (probe / 'sample_t.h').write_text(header)
    (probe / 'sample_t.cpp').write_text(implementation)
    binary = probe / 'rng-probe'
    command = ['g++', '-O2', '-msse4.1', '-ffp-contract=off', '-fno-fast-math', '-I', str(probe),
               'tools/analysis/audio/rng_probe.cpp', '-o', str(binary)]
    subprocess.run(command, check=True)
    numerical = subprocess.check_output([str(binary), str(run / 'node-state.bin')], text=True, timeout=30).strip()
    result = {'schema': 'eidolon-audio-audit-v1', 'base_manifest': 'analysis/audio/manifest.json',
              'event_closure': {'routed_events': sum(routing.values()), 'unrouted_events': len(missed),
                                'managers': managers, 'active_managers': sorted(active),
                                'cc_trigger_events': 0, 'node_counts': [len(full), len(event_reachable)],
                                'all_graph_samples': gmdls(full), 'event_reachable_samples': gmdls(event_reachable),
                                'samplers': samples,
                                'critical_instruction_pins': {hex(k): v for k, v in critical_pins.items()},
                                'direct_note_dispatch_calls': note_calls,
                                'ignored_note_off_velocity': '0x401d6a reads low byte only; source SynthNode.cpp:879..881,936',
                                'limitation': 'Conservative graph closure; dynamic PROCESS/voice/envelope branches can suppress use.'},
              'kernel_audit': audit,
              'rng': {'owner': 'GLITCH id49', 'tick': '0x40514d', 'state_offset': '0x190',
                      'source_lines': [3792, 3802, 3908, 3927], 'saved_manifest': str(manifest_path),
                      'saved_manifest_sha256': sha(manifest_path.read_bytes()), 'saved_files': pin_records,
                      'source_command': command, 'cpu_result': numerical,
                      'scope': '22 retained initializations and one first swap, not all 104 swaps or full PCM'},
              'limitations': ['Dispatch identity is not whole-kernel equivalence.',
                              'Source/native differences include deferred-free placement; arithmetic NaN operand ordering needs retention.',
                              'PCM reference remains independent; no acceptance criteria changed.']}
    (base / 'audit-summary.json').write_text(json.dumps(result, indent=2) + '\n')
    if args.manifest:
        args.manifest.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'routed_note_events': sum(routing.values()), 'active_managers': len(active),
                      'graph_nodes_before_after': [len(full), len(event_reachable)],
                      'samples_before_after': [gmdls(full), gmdls(event_reachable)],
                      'reviewed_types': sum('operation/control' in x['status'] for x in audit),
                      'numerical_check': numerical}, indent=2))


if __name__ == '__main__':
    main()
