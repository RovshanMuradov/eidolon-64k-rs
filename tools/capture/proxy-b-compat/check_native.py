#!/usr/bin/env python3
"""Recheck physical/native/consumer raw observations; producer diagnostic only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inspect(path,control=False):
    m=json.loads(path.read_text())
    data=Path(os.environ['EIDOLON_DATA'])/'reference'/m['run_id']
    events=[json.loads(line) for line in (data/'backend.jsonl').read_text().splitlines()]
    get=lambda name: [e for e in events if e['event']==name]
    for name,digest in m['evidence'].items():
        with (Path(os.environ['EIDOLON_DATA'])/name).open('rb') as stream:
            assert hashlib.file_digest(stream,'sha256').hexdigest()==digest,name
    assert not m['supervisor_timeout'] and m['resources']['prefix_processes_released'] and m['resources']['private_sink_unloaded']
    resumed=get('native_resumed')
    assert [e['kind'] for e in resumed]==[0,1,2]
    for e in resumed:
        kind=e['kind']
        context=(data/f'resume-{kind}-expected-context.bin').read_bytes()
        gpr=struct.unpack('<9I',(data/f'resume-{kind}-gpr.bin').read_bytes())
        fx=(data/f'resume-{kind}-fx.bin').read_bytes()
        expected=[struct.unpack_from('<I',context,offset)[0] for offset in (156,160,180,196,164,168,172,176,192)]
        expected[8]&=~0x10000
        expected[3]-=8  # saved PUSHAD ESP: original resume ESP minus fake return and EFLAGS
        fp_offsets=list(range(5))+list(range(6,32))+list(range(160,288))
        fp_offsets += [32+16*i+j for i in range(8) for j in range(10)]
        equal=list(gpr)==expected and all(fx[i]==context[204+i] for i in fp_offsets)
        assert equal==e['equal'] and sha(fx)==e['fx_sha256']
        assert e['observed_esp']==gpr[3]+8==e['expected_esp']
        assert equal or (control and kind==2)
    assert resumed[1]['mxcsr']==0xffc0 and resumed[1]['x87_cw']==0x27f
    resolver,=get('resolver_control')
    assert resolver['expected']==resolver['by_name']==resolver['by_ordinal'] and resolver['expected']
    assert resolver['routed']==resolver['expected_routed'] and resolver['routed']
    assert resolver['calls']==5 and resolver['missing_name']==resolver['missing_ordinal']==0
    for e in get('native_state'):
        raw=(data/e['file']).read_bytes()
        assert len(raw)==e['bytes'] and sha(raw)==e['sha256']
    assert (data/'native-prethread-tick.bin').read_bytes()==struct.pack('<I',1)
    rng=(data/'native-prethread-rng.bin').read_bytes()
    assert len(rng)==0x520 and struct.unpack_from('<4I',rng,16)==(1,0,31337,0)
    assert struct.unpack_from('<4I',rng,48)==(16007,0,16007,0)
    assert struct.unpack_from('<2d',rng,64)==(2**-31,2**-31)
    if control:
        assert m['launcher_exit']==125 and m['first_failed_check']['reason']=='physical_exception_resume_canary'
        assert not resumed[2]['equal'] and not get('pre_present')
        return m,events
    assert m['status']=='partial' and m['launcher_exit']==0
    exit_event,=get('native_thread_exit')
    assert exit_event['exit_code']==exit_event['expected_eax']
    assert (data/'native-first-query-previous-seconds.bin').read_bytes()==b'\0'*4
    records=get('node_rng'); restores=get('node_probe_restoration'); coverage=get('node_coverage')
    summary,=get('node_summary')
    assert summary['pending']==0 and len(coverage)==summary['activations']
    assert {e['activation'] for e in coverage}==set(range(1,summary['activations']+1))
    assert len(records)==len(restores)==sum(summary['retained'])
    payload=(data/'node-state.bin').read_bytes() if records else b''
    canaries=(data/'node-canaries.bin').read_bytes() if restores else b''
    paired={}
    for i,(record,restoration) in enumerate(zip(records,restores)):
        assert (record['kind'],record['activation'])==(restoration['kind'],restoration['activation'])
        assert record['offset']==i*48 and restoration['offset']==i*1096
        raw=payload[i*48:(i+1)*48]; canary=canaries[i*1096:(i+1)*1096]
        assert sha(raw)==record['sha256'] and sha(canary)==restoration['sha256']
        assert canary[:36]==canary[36:72] and canary[72:584]==canary[584:1096] and restoration['equal']
        assert record['tid']==exit_event['synth_tid']
        key=record['activation']
        paired.setdefault(key,{})[record['kind']]=raw
    for e in coverage:
        phases=paired[e['activation']]
        assert 0 in phases
        assert e['first_swap_before']==e['first_swap_after']==int(1 in phases)
        if 1 in phases:
            assert 2 in phases and phases[1][16:32]==phases[2][16:32]
    consumers=get('consumer_volume')
    if m['staged_scope']['sequential_frames']==5763:
        assert [e['n'] for e in consumers]==[5760,5761,5762]
        for e in consumers:
            raw=(data/e['file']).read_bytes()
            assert len(raw)==33554432 and sha(raw)==e['sha256']==e['upload_sha256']
            assert e['dimensions']==[128]*3 and e['internal_format']==0x8814
            assert e['filter_wrap']==[0x2601,0x2601,0x2901,0x2901,0x2901]
            assert e['cloud_location']>=0 and e['unit']==0 and e['program_index']==20 and e['program']==22 and e['draw_fbo']==10
        assert [e['n'] for e in get('consumer_draw_complete')]==[5760,5761,5762]
        for e in get('consumer_attachment'):
            raw=(data/e['file']).read_bytes()
            assert len(raw)==e['bytes'] and sha(raw)==e['sha256']
        for e in get('consumer_restoration'):
            before=(data/f"consumer-{e['n']:05d}-{e['phase']}-before-state.bin").read_bytes()
            after=(data/f"consumer-{e['n']:05d}-{e['phase']}-after-state.bin").read_bytes()
            assert before==after and len(before)==116 and sha(before)==e['before_sha256']==e['after_sha256'] and e['equal']
    print(json.dumps(dict(run_id=m['run_id'],status='DIAGNOSTIC_ONLY',physical_resumptions=3,resolver_calls=5,
                         nodes=summary,active_consumers=len(consumers),reference_accepted=False)))
    return m,events


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifests',nargs='+',type=Path)
    parser.add_argument('--controls',action='store_true')
    args=parser.parse_args()
    results=[inspect(path,args.controls) for path in args.manifests]
    if len(results)==2 and not args.controls:
        (a,ae),(b,be)=results
        directories=[Path(os.environ['EIDOLON_DATA'])/'reference'/m['run_id'] for m in (a,b)]
        names=[p.name for p in directories[0].glob('native-*.bin') if 'hook-' not in p.name and '-fx' not in p.name]
        names += [p.name for p in directories[0].glob('consumer-*') if '-state.bin' not in p.name]
        names += ['node-state.bin']
        for name in names:
            with (directories[0]/name).open('rb') as x,(directories[1]/name).open('rb') as y:
                while True:
                    left,right=x.read(1048576),y.read(1048576)
                    assert left==right,name
                    if not left: break
        normalized=lambda events: [(e['kind'],e['node_order'],e['activation'],e['tick'],e['sha256']) for e in events if e['event']=='node_rng']
        assert normalized(ae)==normalized(be)
        print(json.dumps(dict(status='DIAGNOSTIC_ONLY',native_consumer_equal_files=len(names),reference_accepted=False)))


if __name__=='__main__':
    main()
