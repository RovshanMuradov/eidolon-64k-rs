#!/usr/bin/env python3
"""Publish a newly acquired, explicitly labeled D12 partial prefix in dependency order.

The immutable acquisition record remains separate from the published producer
envelope. Prior diagnostic versions cannot enter this path.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys

import zstandard
from observations import events as read_events


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def encoded(value):
    return (json.dumps(value,indent=2,sort_keys=True)+'\n').encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def write(path,raw):
    if not isinstance(raw,bytes):
        raw=encoded(raw)
    if path.exists():
        assert path.read_bytes()==raw,path
    else:
        with path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('acquisition',type=Path)
    args=parser.parse_args()
    acquisition=args.acquisition.resolve()
    m=json.loads(acquisition.read_text())
    assert m['reference_variant']=='D9-restored-native' and acquisition.name.endswith('-acquisition.json')
    full=m.get('full_run',False)
    assert m['status']==('complete' if full else 'partial') and m['launcher_exit']==0 and not m['supervisor_timeout']
    assert not m['reference_eligible'] and not m['finalized'] and m['first_failed_check'] is None
    assert m['resources']['prefix_processes_released'] and m['resources']['private_sink_unloaded'] and not m['resources']['errors']
    roots=dict(checkout=Path.cwd(),shared=Path(os.environ['EIDOLON_ROOT']),data=Path(os.environ['EIDOLON_DATA']))
    data=roots['data']/'reference'/m['run_id']
    artifacts=acquisition.parent
    for name,checksum in m['evidence'].items():
        assert sha(roots['data']/name)==checksum,name
    backend=data/(m['ordered_stream']['path'] if full else 'backend.jsonl')
    needed={'pre_present','post_present','failure','fault_injected','native_endpoint','native_exit_forward',
            'planned_partial_stop','native_state','native_resumed','initial_resources','epoch','compat_context',
            'shader_source','shader_program','loaded_module_bytes','scene_anchor_locals','synth_complete',
            'readback_begin','readback_end','stability_check','synth_launch','synth_thread','native_thread_exit',
            'wave_open','wave_prepare','wave_write','full_run'}
    events=[]; positions=[]; expected_seq=1
    for e in read_events(backend):
        if 'seq' not in e:
            assert e['event']=='backend_probe' and e['result']=='distinct_backend' and e['error']==0
            continue
        assert e['seq']==expected_seq
        expected_seq+=1
        if e['event'] in needed:
            events.append(e)
        if e['event']=='clock' and e['api']=='waveOutGetPosition':
            assert e['value']==e['n']*735 and e['wType']==2
            positions.append(e['n'])
    get=lambda name: [e for e in events if e['event']==name]
    def one(name):
        event,=get(name)
        return event
    def binding(path,root):
        path=Path(path).resolve()
        return dict(root=root,path=str(path.relative_to(roots[root])),sha256=sha(path))
    stop=one('native_endpoint' if full else 'planned_partial_stop'); count=stop['frames']
    assert count==(27000 if full else 5763)==m['staged_scope']['sequential_frames'] and stop['exit_code']==0
    if full:
        assert positions==list(range(27001)) and not get('planned_partial_stop')
        assert stop['queries']==27001 and stop['sample_cursor']==19845000 and stop['last_present']==26999
        assert stop['caller']==0x40861e and stop['eax']==0xffffffff and stop['edi']==0
        assert stop['seconds_f32_bits']==0x43e10000 and stop['beat_f32_bits']==0x44160000
        assert one('full_run')['wrapper_stop_enabled'] is False
        assert one('native_exit_forward')['registers_fp_equal'] and one('native_exit_forward')['tail_jump_original_slot']
        for kind in ('gpr','fx'):
            assert (data/f'native-exit-before-{kind}.bin').read_bytes()==(data/f'native-exit-after-{kind}.bin').read_bytes()
    else:
        assert not stop['finalized']
    frames=get('pre_present')
    assert [e['n'] for e in frames]==[e['n'] for e in get('post_present')]==list(range(count))
    assert not get('failure') and not get('fault_injected') and all(e['state_equal'] for e in frames)
    assert any(line.startswith('WINE_EXIT=0 ') for line in m['runner_terminal'])

    # Only the exact executed build snapshots and separately snapshotted host
    # runner enter the immutable identity; changing checkout scripts cannot
    # retroactively change a run's build/tool provenance.
    build=m['build']; build_dir=Path(build['build_directory'])
    for name,checksum in build['outputs'].items():
        assert sha(build_dir/name)==checksum,name
    runner=Path(m['host_runner']['path'])
    assert sha(runner)==m['host_runner']['sha256']
    package_source=Path(__file__).resolve()
    package_snapshot=roots['shared']/'.tools/capture/package-tools'/sha(package_source)/package_source.name
    package_snapshot.parent.mkdir(parents=True,exist_ok=True)
    write(package_snapshot,package_source.read_bytes())
    inventory=dict(build_id=build['build_id'],build_sources=build['sources'],original_sources=build['original_sources'],
                   outputs=build['outputs'],host_runner_sha256=m['host_runner']['sha256'],
                   launcher_sha256=sha('tools/wine-headless'),package_sha256=sha(package_snapshot),
                   python=sys.version,zstandard=zstandard.__version__)
    capture_tool_sha256=digest(inventory)
    write(data/'capture-tool-inventory.json',inventory)

    index=[]; compressor=zstandard.ZstdCompressor(level=3)
    for e in frames:
        n=e['n']; assert e['clock_tick']==n and e['audio_position']==n*735
        row=dict(n=n,tick=n,clock_tick=n,audio_position=n*735,audio_position_num=n*44100,audio_position_den=60,sha256=e['sha256'])
        raw=data/f'frame-{n:05d}.rgba'
        assert raw.exists()==(n in m['staged_scope']['retained_indices'])
        if raw.exists():
            assert raw.stat().st_size==8294400 and sha(raw)==e['sha256']
            packed=data/f'frame-{n:05d}.raw.zst'
            if not packed.exists():
                write(packed,compressor.compress(raw.read_bytes()))
            decoder=zstandard.ZstdDecompressor().decompressobj()
            decoded=decoder.decompress(packed.read_bytes())
            assert decoder.eof and not decoder.unused_data and decoded==raw.read_bytes()
            row['raw_zst']=packed.name
        index.append(row)
    index_path=artifacts/f"{m['run_id']}-frames.jsonl"
    write(index_path, ''.join(json.dumps(row,separators=(',',':'))+'\n' for row in index).encode())
    pcm_names=('synth_complete','readback_begin','readback_end','stability_check')
    pcm_events={name:one(name) for name in pcm_names}
    assert (data/'pcm.f32le').stat().st_size==159716352
    audio=dict(path='pcm.f32le',sha256=sha(data/'pcm.f32le'),sample_format='f32le',sample_rate=44100,
               channels=['L','R'],layout='interleaved',sample_frames=19964544,start_sample=0)
    assert audio['sha256']==pcm_events['readback_end']['sha256']==pcm_events['stability_check']['sha256']
    envelope_path=artifacts/f"{m['run_id']}-pcm-observations.json"
    write(envelope_path,dict(kind='D9-restored-native-pcm-observations',run_id=m['run_id'],reference_eligible=False,
          acquisition=binding(acquisition,'checkout'),input=m['input'],dependency=m['dependency'],build_id=build['build_id'],
          backend=binding(backend,'data'),observations=[e for e in events if e['event'] in (*pcm_names,
          'synth_launch','synth_thread','native_thread_exit','wave_open','wave_prepare','wave_write','epoch','planned_partial_stop',
          'native_endpoint','native_exit_forward')]))
    complete=pcm_events['synth_complete']
    pcm=dict(submitted_bytes=pcm_events['readback_begin']['bytes'],initial_tick=complete['initial_tick'],final_tick=complete['final_tick'],
             final_cursor_offset=int(complete['final_cursor'],16)-int(pcm_events['readback_begin']['base'],16),
             events={name:e['seq'] for name,e in pcm_events.items()},stable_sha256=audio['sha256'],
             evidence=envelope_path.name,evidence_sha256=sha(envelope_path))

    shims={name:build['outputs'][name] for name in ('opengl32.dll','winmm.dll')}
    source=dict(kind='D9-restored-native',exe_sha256=m['input']['exe_sha256'],
                inputs=dict(archive=m['input']['archive_sha256'],bank=m['dependency']['bank']['sha256'],
                            host_runner=m['host_runner']['sha256'],launcher=sha('tools/wine-headless'),
                            package=sha(package_snapshot),**build['sources'],**build['original_sources']),
                restoration=dict(decision='D12',transformation='450-compatibility',
                    raw_shader_sha256='57cdc43590d369b0744da71530cf879b6099cc6d80797809b59abd0fa5cc2182',
                    effective_shader_sha256='cb62ed7fd0878836b763b892f64cb9e4a789f49f304d32d0a2fc334aecb433ea',shim_sha256=shims))
    termination=dict(reason='natural_exit' if full else 'partial_stop',end_tick=count,audio_position=count*735,audio_position_num=count*44100,
                     audio_position_den=60,exit_code=0,timeline_end_tick=None,
                      evidence=('native_ExitProcess_call_0x408618_after_query27000_and_present26999;native_exit0' if full else
                                'planned_partial_stop_at_next_waveOutGetPosition_after_5763_successful_presents;native_exit0'))
    initial={e['phase']+'-'+e['role']:e['sha256'] for e in get('native_state')}
    fp={}
    for name in ('entry-main','prethread-main','first-query-main'):
        raw=(data/f'native-{name}-fx.bin').read_bytes()
        fp[name]=dict(x87_cw=struct.unpack_from('<H',raw)[0],mxcsr=struct.unpack_from('<I',raw,24)[0])
    for e in get('native_resumed'):
        fp['physical-resume-'+str(e['kind'])]=dict(x87_cw=e['x87_cw'],mxcsr=e['mxcsr'])
    initial.update(prefix_baseline=m['prefix_baseline']['inventory_sha256'],native_resources=one('initial_resources')['sha256'],
                   fp_controls=fp,build_id=build['build_id'])
    conditions=dict(environment=dict(os=m['environment']['os'],arch='PE32 i386; fresh Wine win64 WoW64 prefix',
         wine=m['environment']['wine'],gpu=m['environment']['gpu'].split(',')[0].strip(),
         driver=m['environment']['gpu'].split(',')[1].strip(),
         graphics_api=one('compat_context')['version']+'; GLSL '+one('compat_context')['glsl'],
         gamescope=next(p for p in m['environment']['packages'] if p.startswith('gamescope ')),
         display=dict(kind='gamescope-headless',width=1920,height=1080,launcher='tools/wine-headless',wine_virtual_desktop=False)),
         settings=dict(prefix_recipe=m['prefix_baseline']['recipe'],prefix_inventory_sha256=m['prefix_baseline']['inventory_sha256'],
            initial_observations=initial,build_id=build['build_id'],clock_epoch_ms=one('epoch')['E'],
            runtime={k:v for k,v in m['environment']['settings'].items() if k not in ('EIDOLON_B_LOG','EIDOLON_B_OUTPUT',
            'EIDOLON_B_RETENTION','XDG_CACHE_HOME','__GL_SHADER_DISK_CACHE_PATH','WINE_TIMEOUT')},
            cache_policy='fresh per-run cache directories',capture_resolution=[1920,1080],native_state_reset=False,
            instrumentation='one-shot bootstrap rendezvous; interior/completion acquisition INT3; physical resume/RET witnesses; three fingerprint-bound S2 instruction trampolines; no hardware breakpoints or driver callbacks'),
         clock=dict(numerator=1,denominator=60,method='native waveOutGetPosition cursor735*n; exact shared millisecond/QPC epoch; all original frames rendered'),
         rng=dict(method='native initialization and node-local RNG without resets; prethread0x520 bytes plus tick and per-activation input/global/node observations',
                  initial_state_sha256=sha(data/'native-prethread-rng.bin')),initial_state_sha256=digest(initial))
    command=[m['run_id'] if arg=='<fresh-id>' else arg for arg in m['reproduce']]
    layout=frames[0]
    manifest=dict(schema='eidolon-reference-draft-4' if full else 'eidolon-partial-reference-draft-4',run_id=m['run_id'],source=source,
          capture=dict(kind='controlled-reference' if full else 'controlled-partial',tool_sha256=capture_tool_sha256,command=command),conditions=conditions,
         video=dict(width=1920,height=1080,row_stride=7680,pixel_format='rgba8',row_order='bottom-up',
                    color_space=f"native attachment GL_{layout['encoding']:04x}; framebuffer sRGB {layout['sRGB_enabled']}",
                     frame_count=count,index=index_path.name,index_sha256=sha(index_path),storage=m.get('storage','reference')),
         audio=audio,scenes=[dict(id=f"row-{r['row']:02d}",first=r['first'],last=min(r['last'],count-1))
                            for r in m['staged_scope']['native_rows'] if r['first']<count],termination=termination,
          completion=dict(finalized=full,frames_observed=count,frames_hashed=count,audio_sample_frames=19964544,
                         dropped_frames=stop['dropped_frames'],dropped_audio_sample_frames=stop['dropped_audio_sample_frames'],errors=stop['errors'],pcm=pcm))
    observations=dict(acquisition=binding(acquisition,'checkout'),ordered_runtime=binding(backend,'data'),
                      native_exit=binding(data/'runner.log','data'),tool_inventory=binding(data/'capture-tool-inventory.json','data'),
                      pcm_completion=binding(envelope_path,'checkout'))
    for name in ('node-state.bin','node-canaries.bin','native-prethread-rng.bin','native-entry-physics.bin','native-first-query-physics.bin'):
        observations[name]=binding(data/name,'data')
    target,=[e for e in get('shader_source') if e['transformed']]
    loaded={e['role']:e['file_sha256'] for e in get('loaded_module_bytes')}
    identity=m['executed_file_observation']
    assert identity['before_sha256']==identity['after_sha256']==source['exe_sha256']
    final_source=(stop if full else get('scene_anchor_locals')[-1])['original_source_sha256']
    assert target['raw_sha256']==final_source==source['restoration']['raw_shader_sha256']
    assert {name:loaded[name.removesuffix('.dll')+'-shim'] for name in shims}==shims
    producer=dict(m,acquisition=binding(acquisition,'checkout'),package_tool=binding(package_snapshot,'shared'),
       reference_contract=dict(schema=manifest['schema'],source=source,capture_tool_sha256=capture_tool_sha256,
             video_index_sha256=sha(index_path),frame_count=count,audio_sha256=audio['sha256'],termination=termination,finalized=full,
            exe_before_sha256=identity['before_sha256'],exe_after_sha256=identity['after_sha256'],
             target_memory_before_sha256=target['raw_sha256'],target_memory_after_sha256=final_source,
            loaded_shim_sha256={name:loaded[name.removesuffix('.dll')+'-shim'] for name in shims},observations=observations))
    producer_path=artifacts/f"{m['run_id']}.json"
    write(producer_path,producer)

    image_path=roots['data']/'reverse/confirmed-debug/postfix-00400000.bin'
    assert sha(image_path)=='da9cc65b64aa7d322807d93cb4361bc864a10f00ed47246f5df96fb5b9ecf504'
    calls=[]
    for program in get('shader_program'):
        creation=program['creation']; sources=[e for e in get('shader_source') if e['creation']==creation]
        assert [e['index'] for e in sources]==list(range(len(sources)))
        ret=int(sources[0]['caller'],16)
        calls.append(dict(sequence=creation,stage=sources[0]['stage'],count=len(sources),caller=f'0x{ret-2:08x}',
            **{'return':f'0x{ret:08x}'},source_addresses=[f"0x{int(e['pointer'],16):08x}" for e in sources],
            input=[binding(data/f"shader-{creation:03d}-{e['index']:03d}-raw.glsl",'data') for e in sources],
            forwarded=[binding(data/f"shader-{creation:03d}-{e['index']:03d}-effective.glsl",'data') for e in sources],
            forward_calls=program['forward_calls'],program=program['program']))
    exe=data/'native-input.exe'
    if not exe.exists():
        shutil.copyfile(identity['path'],exe)
    assert sha(exe)==source['exe_sha256']
    inputs={name:binding(build_dir/'source-snapshot'/name,'shared') for name in dict(build['original_sources'],**build['sources'])}
    for name in build['outputs']:
        if not name.startswith('source-snapshot/') and not name.endswith(('.dll','.exe')):
            inputs[name]=binding(build_dir/name,'shared')
    inputs['executing-host-runner']=binding(runner,'shared')
    inputs['D12-package-tool']=binding(package_snapshot,'shared')
    sidecar=dict(schema='eidolon-d9-eligibility-1',kind='compatibility-modified-diagnostic',decision='D9',run_id=m['run_id'],
         reference_eligible=False,run_manifest=binding(producer_path,'checkout'),
         inputs=dict(exe=binding(exe,'data'),archive=binding(roots['shared']/m['input']['archive'],'shared'),
                     bank=binding(roots['data']/'reference/dependencies/gm.dls','data'),launcher=binding('tools/wine-headless','checkout')),
         build=dict(inputs=inputs,outputs={name:binding(build_dir/name,'shared') for name in build['outputs'] if name.endswith(('.dll','.exe'))},
                    compiler=build['compiler'],commands=build['commands']),transformation='450-compatibility',calls=calls,fallback=None)
    sidecar_path=artifacts/f"{m['run_id']}-eligibility.json"; write(sidecar_path,sidecar)
    manifest['provenance']=dict(eligibility=binding(sidecar_path,'checkout'),native_image=binding(image_path,'data'))
    final=artifacts/f"{m['run_id']}-{'reference' if full else 'partial-reference'}.json"; write(final,manifest)
    print(json.dumps(dict(status='PUBLISHED_FULL_FOR_REVIEW' if full else 'PUBLISHED_PARTIAL_FOR_REVIEW',manifest=str(final),frames=count,
                          raw_frames=sum('raw_zst' in row for row in index),reference_accepted=False)))


if __name__=='__main__':
    main()
