#!/usr/bin/env python3
"""Bind native kernel/helper spans and source algorithms to fixed-score CPU coverage."""
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
from recover import numeric


def sha(b):
    return hashlib.sha256(b).hexdigest()


HELPERS = {
    0x401038: ('s_rand', 'sample_t.cpp', 142),
    0x401066: ('s_exp2', 'sample_t.cpp', 163),
    0x40176b: ('SynthMalloc', 'SynthAllocator.cpp', 11),
    0x401785: ('SynthFree', 'SynthAllocator.cpp', 26),
    0x4017a5: ('SynthMemSet', 'SynthAllocator.cpp', 55),
    0x4017c3: ('SynthMemCopy', 'SynthAllocator.cpp', 70),
    0x4018a6: ('GetDelayTimeFraction', 'SynthNode.cpp', 589),
    0x40190e: ('InsertArpKeys', 'SynthNode.cpp', 600),
    0x401a19: ('ClearArpVoices', 'SynthNode.cpp', 673),
    0x401a67: ('ArpeggiatorStep', 'SynthNode.cpp', 707),
    0x40265c: ('Osc_Tick', 'SynthNode.cpp', 1334),
    0x402f6d: ('Frequency_Map', 'SynthNode.cpp', 1730),
    0x403ea1: ('DELAY_init', 'SynthNode.cpp', 2722),
    0x403eb3: ('UpdateDelayParams', 'SynthNode.cpp', 2730),
    0x404097: ('SetBufferSample', 'SynthNode.cpp', 2831),
    0x4044df: ('REVERB_init / VOICEMANAGER_init folded allocation', 'SynthNode.cpp', 3020),
    0x404cf0: ('Sampler_Sample', 'SynthNode.cpp', 3492),
    0x405dbd: ('CONSTANT_tick', 'SynthNode.cpp', 5045),
    0x405de9: ('CreateNode', 'SynthNode.cpp', 5075),
    0x405e78: ('CreateNodes', 'SynthNode.cpp', 5115),
    0x405f4e: ('DestroyVoiceNodes', 'SynthNode.cpp', 5171),
}


def main():
    root, data = Path(os.environ['EIDOLON_ROOT']), Path(os.environ['EIDOLON_DATA'])
    base = json.loads(Path('analysis/audio/manifest.json').read_text())
    audit = json.loads(Path('analysis/audio/audit.json').read_text())
    checks = [json.loads(Path('analysis/audio/' + name).read_text())
              for name in ('source-check.json', 'source-check-closed.json')]
    image = (data / base['inputs']['postfix']['path']).read_bytes()
    assert sha(image) == base['inputs']['postfix']['sha256']
    node_bytes = (data / 'analysis/audio/T19/nodes.json').read_bytes()
    assert sha(node_bytes) == base['patch']['nodes_sha256']
    nodes = json.loads(node_bytes)
    source = subprocess.check_output(['git', '-C', str(root / '.tools/analysis/audio/64klang'),
                                     'show', base['source']['commit'] + ':Player/Player/SynthNode.cpp'])
    assert sha(source) == base['source']['files']['SynthNode.cpp']
    source = source.decode()
    tables = {}
    for name, code, count in [('FORMANT_Coeff', 'h', 375), ('DELAY_TIME_FRACTION', 'f', 33),
                              ('ArpStepGateFraction', 'f', 4)]:
        match = re.search(r'\b' + name + r'\[[^\]]+\]\s*=\s*\{(.*?)\};', source, re.S)
        text = re.sub(r'//[^\n]*', '', match[1])
        values = [numeric(s.strip().replace('f', '')) for s in text.split(',') if s.strip()]
        assert len(values) == count
        raw = struct.pack('<' + code * count, *values)
        offset = image.find(raw)
        assert offset >= 0 and image.find(raw, offset + 1) == -1
        tables[name] = {'va': hex(0x400000 + offset), 'bytes': len(raw), 'sha256': sha(raw),
                        'source_line': source[:match.start()].count('\n') + 1,
                        'comparison': 'complete source/native byte equality'}
    for check in checks:
        assert check['equal'] and check['frames'] == base['song']['frames']
        assert check['source_commit'] == base['source']['commit']
        assert check['input_image_sha256'] == base['inputs']['postfix']['sha256']
    assert checks[0]['actual_sha256'] == checks[1]['actual_sha256']
    assert checks[0]['coverage'] == checks[1]['coverage']
    closure = audit['event_closure']['event_reachable_samples']
    assert checks[0]['coverage']['gmdls_samples'] == closure
    seen = set(checks[0]['coverage']['node_offsets'])
    starts = sorted({int(x['tick_va'], 16) for x in nodes} | set(HELPERS) | {0x4010e3, 0x405f98})
    assembly = subprocess.check_output(['objdump', '-D', '-b', 'binary', '-m', 'i386', '-Mintel',
                                       '--adjust-vma=0x400000', '--start-address=0x401038',
                                       '--stop-address=0x405f98', str(data / 'analysis/audio/T19/postfix-copy.bin')], text=True)
    instructions = []
    for line in assembly.splitlines():
        m = re.match(r'\s*([0-9a-f]+):\s+(?:[0-9a-f]{2} )+\s*(\w+)\s*(.*)', line)
        if m:
            instructions.append((int(m[1], 16), m[2], m[3]))
    def native(start):
        end = min(x for x in starts if x > start)
        ops = [x for x in instructions if start <= x[0] < end]
        return {'start': hex(start), 'end_exclusive': hex(end),
                'sha256': sha(image[start-0x400000:end-0x400000]),
                'direct_calls': sorted({arg for _, op, arg in ops if op == 'call' and arg.startswith('0x')}),
                'scope': 'contiguous symbol interval; not a recovered CFG'}
    inventory = []
    for entry in audit['kernel_audit']:
        group = [n for n in nodes if n['name'] == entry['node_type']]
        function = entry['source_function']
        start = source.index('void SYNTHCALL ' + function + '(SynthNode* n)')
        end = source.index('\n}', start) + 2
        body = source[start:end]
        modes = []
        entered_modes = []
        if 'modePointer' in body:
            fmt = '<I' if entry['node_type'] == 'VOICEMANAGER' else '<H'
            modes = sorted({struct.unpack_from(fmt, image, 0x3edf0 + 2*n['mode_word_offset'])[0] for n in group})
            entered_modes = sorted({struct.unpack_from(fmt, image, 0x3edf0 + 2*n['mode_word_offset'])[0]
                                    for n in group if n['offset_words'] in seen})
        inventory.append({'node_type': entry['node_type'], 'source_function': function,
                          'source_lines': [source[:start].count('\n')+1, source[:end].count('\n')+1],
                          'native': native(int(entry['tick'], 16)), 'immediate_modes': [hex(v) for v in modes],
                          'source_entered_modes': [hex(v) for v in entered_modes],
                          'graph_nodes': len(group), 'source_entered_nodes': sum(n['offset_words'] in seen for n in group),
                          'numerical_scope': 'fixed-score end-to-end PCM equality; not per-call/all-input equivalence',
                          'prior_static_review': entry['status']})
    # Exact opcode anchors for reviewed recurrence, coefficient, and mapping paths.
    pins = {0x402f85: 'f6430880', 0x402fa4: 'f6430840',
            0x40351e: '660f595640', 0x403537: '660f5cc8', 0x40353e: '660f584910',
            0x40354b: '660f598690000000', 0x40355b: '83c120',
            0x4035f9: '0f294e60', 0x4036a5: '0f294660', 0x403708: '660f51c1',
            0x405a75: '660f594640', 0x405a96: '660f594e40',
            0x405aa4: '660f594e40', 0x405ac5: '660f595640', 0x405afd: '83c030'}
    for va, encoding in pins.items():
        assert image[va-0x400000:va-0x400000+len(bytes.fromhex(encoding))].hex() == encoding
    raw = Path(checks[0]['run_command'][4]).read_bytes()
    assert sha(raw) == checks[0]['actual_sha256'] and len(raw) == 159716352
    assert any(raw)
    # Detector controls on full, already independently hash-pinned PCM.
    altered = bytearray(raw)
    altered[len(raw)//2] ^= 1
    controls = {'single_bit_change_rejected': raw != altered,
                'missing_final_frame_rejected': raw != raw[:-8],
                'one_frame_shift_rejected': raw != raw[8:] + b'\0'*8}
    assert all(controls.values())
    result = {'schema': 'eidolon-kernels-fixed-score-v1', 'source_commit': base['source']['commit'],
              'input_image_sha256': sha(image), 'kernels': inventory,
              'helpers': [{'name': name, 'source_file': file, 'source_line': line, 'native': native(va)}
                          for va, (name, file, line) in HELPERS.items()],
              'recurrence_instruction_pins': {hex(k): v for k, v in pins.items()},
              'source_native_tables': tables,
              'comparison_controls': controls,
              'comparison_manifests': {name: sha(Path('analysis/audio/' + name).read_bytes())
                                       for name in ('source-check.json', 'source-check-closed.json')},
              'limits': ['No claim of all-input or internal-state equivalence.',
                         'Known native/source allocator timing and host ABI differences retained in kernels.md.',
                         'Saved diagnostic PCM agreement does not change runtime reference eligibility.']}
    Path('analysis/audio/kernels.json').write_text(json.dumps(result, indent=2) + '\n')
    print('KERNEL_INVENTORY_PASS', len(inventory), 'types', len({e['native']['start'] for e in inventory}),
          'tick kernels;', len(seen), 'entered graph nodes; full PCM equality and corruption/shift controls pass')


if __name__ == '__main__':
    main()
