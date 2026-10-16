#!/usr/bin/env python3
"""Reconcile graphics recovery with existing D12/G5 files; never execute target.

The independent whole-bundle gate remains tools/verify/review_d12.py. This
focused check decodes startup physics/FP and the already-attested GL ledger.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ['EIDOLON_DATA'])
RUNS = ['proxy-b-d12-volume-20261016', 'proxy-b-d12-volume-repeat-20261016']


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def checked(path, digest):
    with path.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == digest, str(path)
    return path


def one(events, event, **fields):
    values = [e for e in events if e['event'] == event and all(e[k] == v for k,v in fields.items())]
    assert len(values) == 1, (event, fields, len(values))
    return values[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    native = json.loads((ROOT/'reports/evidence/reverse/manifest.json').read_text())['runtime_diagnostic']['files']
    image = checked(DATA/native['postfix']['path'], native['postfix']['sha256']).read_bytes()
    word = lambda a: struct.unpack_from('<I', image, a-0x400000)[0]
    text = lambda a: image[a-0x400000:image.index(0,a-0x400000)].decode('ascii')
    assert word(0x4096c0+49*4)==0x40514d and word(0x4096c0+42*4)==0x404dd0
    records = []
    expected = bytearray(256)
    for i, (name_address, rotation_address, parameters) in enumerate([
            (0x42111c,0x42208c,0x436490), (0x42127c,0x4220a4,0x4364c0),
            (0x421a54,0x422a9c,0x4364b0), (0x421f2c,0x423454,0x4364a0)]):
        raw = image[parameters-0x400000:parameters-0x400000+16]
        expected[64*i+32:64*i+48] = raw
        records.append({'base': hex(0xb17bdf0+64*i), 'position_uniform': text(name_address),
                        'rotation_uniform': text(rotation_address),
                        'parameters_address': hex(parameters),
                        'parameters_f32_bits': list(struct.unpack('<4I',raw))})
    tables_raw = (DATA/'analysis/graphics/engine-tables.json').read_bytes()
    assets = json.loads((ROOT/'analysis/graphics/assets.json').read_text())
    assert sha(tables_raw) == assets['decoded']['sha256']
    tables = json.loads(tables_raw)
    fourth = []
    for row in tables['rows']:
        names = [u['uniform'] for u in row['uniforms']]
        assert len(names) == len(set(names))
        for record in records:
            record.setdefault('active_rows', [])
            if record['position_uniform'] in names:
                record['active_rows'].append(row['row'])
        for u in row['uniforms']:
            a = int(u['address'],16)
            if word(a+0x54) > 3:
                fourth.append({'row':row['row'], 'uniform':u['uniform'], 'descriptor':hex(a),
                               'foreign_gate_value':word(a+0x54), 'offset':word(a+32), 'length':word(a+36)})
    assert records[3]['position_uniform'] == 'uEvilCharacterPos3' and records[3]['active_rows'] == []
    assert fourth == [{'row':49,'uniform':'uAngles','descriptor':'0x4357b8',
                       'foreign_gate_value':17,'offset':0,'length':0}]
    fault = native['fault_state']
    raw = checked(DATA/fault['path'], fault['sha256']).read_bytes()
    offset = 0xb17bde0-int(fault['mapped_base'],16)
    assert raw[offset:offset+16] == bytes(16)
    runs = []
    for run in RUNS:
        path = ROOT/'artifacts/reference'/f'{run}.json'
        manifest = json.loads(path.read_text())
        directory = DATA/'reference'/run
        events = manifest['observations']

        def evidence(name):
            file = directory/name
            return checked(file,manifest['evidence'][str(file.relative_to(DATA))])

        # Bind producer interpretation to the immutable executed source snapshot.
        build = manifest['build']
        for name in ('native.c','consumer.c','core.c','stage.c'):
            key = 'source-snapshot/tools/capture/proxy-b-compat/'+name
            checked(Path(build['build_directory'])/key,build['outputs'][key])
        entry = evidence('native-entry-physics.bin').read_bytes()
        first = evidence('native-first-query-physics.bin').read_bytes()
        assert entry == bytes(256) and first == expected
        assert evidence('native-first-query-previous-seconds.bin').read_bytes() == bytes(4)
        fp = {}
        for phase in ('entry-main','prethread-main','first-query-main'):
            raw = evidence(f'native-{phase}-fx.bin').read_bytes()
            cw, = struct.unpack_from('<H',raw)
            mxcsr, = struct.unpack_from('<I',raw,24)
            assert cw == 0x27f and mxcsr & ~0x3f == 0x1f80
            fp[phase] = {'x87_cw':cw,'mxcsr':mxcsr,'mxcsr_control':mxcsr & ~0x3f}
        interior = evidence('resume-1-fx.bin').read_bytes()
        assert struct.unpack_from('<H',interior)[0] == 0x27f
        assert struct.unpack_from('<I',interior,24)[0] == 0xffc0
        shaders = manifest['source_provenance']
        assert len(shaders) == 235
        changed = []
        for e in shaders:
            a = int(e['pointer'],16)
            raw = text(a).encode('ascii')
            stem = f"shader-{e['creation']:03d}-{e['index']:03d}"
            assert evidence(stem+'-raw.glsl').read_bytes() == raw
            effective = evidence(stem+'-effective.glsl').read_bytes()
            if e['transformed']:
                assert a == 0x409918 and raw.startswith(b'#version 450\n')
                assert effective == b'#version 450 compatibility\n'+raw[13:]
                changed.append([e['creation'],e['index'],hex(a)])
            else:
                assert effective == raw
        assert changed == [[2,0,'0x409918']]
        programs = [e for e in events if e['event']=='shader_program']
        assert len(programs)==31 and all(e['link_status']==1 and e['api_error']==0 for e in programs)
        context = one(events,'compat_context')
        assert context['profile_mask']==2 and context['flags']==0
        draw = one(events,'first_draw_state')
        assert draw['viewport']==[0,0,16384,128] and draw['draw_buffers']==[0x8ce0]+[0]*7
        assert draw['color_mask']==[1]*4 and draw['blend']==draw['srgb']==0
        assert draw['clamp_fragment_color']==0x891d and draw['fbo_status']==0x8cd5
        consumers = []
        for n in range(5760,5763):
            volume = one(events,'consumer_volume',n=n)
            assert volume['program_index']==20 and volume['unit']==0 and volume['sampler']==0
            assert volume['dimensions']==[128]*3 and volume['filter_wrap']==[0x2601]*2+[0x2901]*3
            assert volume['sha256']==volume['upload_sha256']==one(events,'volume_upload')['source_sha256']
            evidence(volume['file'])
            attachments = [one(events,'consumer_attachment',n=n,draw_buffer_index=i) for i in range(3)]
            for i,e in enumerate(attachments):
                assert e['attachment']==0x8ce0+i and e['texture']==10+i
                assert e['internal_format']==0x8814 and e['dimensions']==[1920,1080]
                evidence(e['file'])
            consumers.append({'frame':n,'program_index':20,'volume_matches_upload':True,
                              'draw_buffers':[e['attachment'] for e in attachments],
                              'texture_handles':[e['texture'] for e in attachments]})
        runs.append({'run_manifest':str(path.relative_to(ROOT)),
                     'initial_physics_matches_native_parameter_copies':True, 'fp':fp,
                     'shader_fragments':235, 'linked_programs':31,'changed_sources':changed,
                     'context':{k:context[k] for k in ('version','glsl','profile_mask','flags')},
                     'first_draw':{k:draw[k] for k in ('viewport','draw_buffers','blend','srgb','clamp_fragment_color')},
                     'cloud_consumers':consumers})
    result = {'schema':'eidolon-graphics-g5-reconciliation-v1','status':'SAVED_G5_STATE_RECONCILED',
              'native_provenance':'reports/evidence/reverse/manifest.json',
              'whole_bundle_check':'bash tools/run python tools/verify/review_d12.py',
              'node_rng_owner':{'dispatch_id':49,'tick':'0x40514d','type':'GLITCH',
                                'node_offset':'0x190','counter_handoff':'audio-to-graphics-sync.md'},
              'physics_records':records,'unused_fourth_component_evaluations':fourth,
              'reset_vector':{'address':'0x0b17bde0','f32_bits':[0]*4,
                              'saved_witness':'runtime_diagnostic.files.fault_state',
                              'g5_direct_snapshot':False},'runs':runs,
              'limitations':['No recorded post-update physics vectors or fragment-output name locations',
                             'G5 bounded evidence does not establish G6 or Rust equivalence',
                             'Reset vector has a T1 saved witness, not a G5 direct observation']}
    target = ROOT/'analysis/graphics/saved-state.json'
    if args.write:
        target.write_text(json.dumps(result,indent=2)+'\n')
    else:
        assert json.loads(target.read_text())==result
    print(json.dumps({'status':result['status'],'runs':len(runs),'physics_records':4,
                      'linked_programs_per_run':31,'consumer_draws_per_run':3}))


if __name__ == '__main__':
    main()
