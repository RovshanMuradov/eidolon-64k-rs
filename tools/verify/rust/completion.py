#!/usr/bin/env python3
"""Independent Step3 evidence audit under the approved D28 semantic mapping."""
import json
from pathlib import Path
import struct
from conformance import CHECKOUT,DATA,PIN,Native,load,checked,sha,need


def full_gate(full):
    p=full['progress']
    need(full['status']=='CLOSED_EXACT_FILES' and full['complete_capture'] is True and full['natural_exit_log'] is True,'full natural capture gate')
    for k in ('post_presents','frame_hashes','matching_frame_hashes'):need(type(p[k]) is int and p[k]==27000,'full frame coverage: '+k)
    need(p['queries']==27001 and p['frame_mismatches']==p['time_mismatches']==0 and p['endpoint'] and p['terminal_stability'],'full clock/endpoint')
    need(full['retained_raws_byte_compared']==510 and full['pcm']=='EXACT_NATIVE_PCM' and full['gl_restoration_witnesses']==27000,'full byte/GL coverage')
    need(not full['errors'] and set(full['physical_restoration'])=={'entry_gpr','entry_fp','marker_gpr','marker_fp'} and all(v is True for v in full['physical_restoration'].values()),'full physical restoration')
    need(not any(full['cleanup'].values()),'full capture cleanup')


def sampled_gate(curves,native):
    need(curves['status']=='SAMPLED_NATIVE_CURVES_AND_PHYSICS_EXACT','paired curve verification')
    need(curves['physics_samples']==native['physics_frames']==151 and curves['curve_draws']==native['sampled_curve_draws']==302,'bounded sample coverage')
    need(curves['float_words']==native['curve_float_words']==3824 and native['physics_differences']==0,'exact native vector coverage')
    need(not any(curves['cleanup'].values()) and native['cleanup_verified'] is True,'paired state cleanup')


def audit():
    root=CHECKOUT/'artifacts/verification/rust'
    names=('full-progress','rebuild','build-closure','standalone','playback','resource-closure','resource-d26-all02','live-d28-scalars-full01','native-d28-vectors01','curves','control-gl','control-position','live-fp-reject','live-entry-reject','live-d28-seed-reject')
    evidence={name:load(root/(name+'.json')) for name in names}
    bindings={name:dict(path=str((root/(name+'.json')).relative_to(CHECKOUT)),sha256=sha(root/(name+'.json'))) for name in names}
    candidate=load(CHECKOUT/'artifacts/rust/engine/candidate.json');bundle=Path(candidate['directory'])
    checked(bundle/'candidate.json',candidate['manifest_sha256']);exe=checked(bundle/'eidolon-runtime.exe',candidate['executable_sha256']);native=Native()
    need(sha(native.path)==PIN and native.manifest['audio']['sha256']=='9b1aa5f18aea89e27415ce82bd142b2e66bab3adaa7db4eab64f119fd33e631d','accepted native pin')
    full=evidence['full-progress'];full_gate(full)
    checked(DATA/'verification/rust/live-d26-full01/state.json',full['state_snapshot_sha256'])
    need(full['candidate_sha256']==candidate['executable_sha256'],'full production identity')
    for name in ('playback','live-d28-scalars-full01','native-d28-vectors01','live-d28-seed-reject','control-gl','control-position'):
        proof=evidence[name];job=proof.get('job',name)
        state=load(checked(DATA/'verification/rust'/job/'state.json',proof['state_sha256']))
        need(state['phase']=='closed','open evidence job')
        if 'candidate_sha256' in state:need(state['candidate_sha256']==candidate['executable_sha256'],'different production image')
    curves=evidence['curves'];sampled_gate(curves,evidence['native-d28-vectors01'])
    pointer=load(root/'curve-job.json');curve_state=load(checked(pointer['state'],curves['state_sha256']));need(curves['candidate_sha256']==candidate['executable_sha256'],'paired curve image')
    identity=load(root/'curve-live-identity.json')
    need(identity['candidate_sha256']==candidate['executable_sha256'] and identity['helper_sha256']==curve_state['helper_sha256'] and any(m['candidate_mapped'] and m['helper_mapped'] for m in identity['mappings']),'observed production/helper mapping')
    bindings['curve_live_identity']=dict(path='artifacts/verification/rust/curve-live-identity.json',sha256=sha(root/'curve-live-identity.json'))
    scalar=evidence['live-d28-scalars-full01'];need(scalar['status']=='SEMANTIC_FULL_EXACT' and scalar['frames']==27000 and scalar['uniform_passes']==513000 and scalar['cleanup_verified'],'full time/cloud uniforms')
    need(all(scalar[k] is True for k in ('ready_seed','ready_tick','previous_seconds','initial_physics')),'D28 observed live initialization')
    correspondence=load(CHECKOUT/'artifacts/rust/state/correspondence.json');need(correspondence['executable_sha256']==candidate['executable_sha256'],'D28 static source/binary mapping')
    image=checked(correspondence['native_image']['path'],correspondence['native_image']['sha256']).read_bytes()
    constants=native.states['prethread/rng'].read_bytes()
    need(constants[:16]==struct.pack('<4I',1023,1023,0,0) and constants[32:48]==bytes([255])*16,'native immutable bias/mask')
    for i in range(79):
        literal=image[0x90b8+8*i:0x90c0+8*i];need(len(literal)==8 and constants[48+16*i:64+16*i]==literal*2,'native duplicated constant vector')
    for path,digest in correspondence['source_sha256'].items():need(evidence['build-closure']['inputs'][path]==digest,'D28 mapped source/compiler provenance')
    bindings['D28_correspondence']=dict(path='artifacts/rust/state/correspondence.json',sha256=sha(CHECKOUT/'artifacts/rust/state/correspondence.json'))
    rebuild=evidence['rebuild'];need(rebuild['status']=='INDEPENDENT_CLEAN_BUILD_EXACT' and rebuild['candidate_sha256']==candidate['executable_sha256'],'reproducible production image')
    built=load(checked(DATA/rebuild['result'],rebuild['sha256']));checked(built['executable'],candidate['executable_sha256'])
    need(evidence['build-closure']['rebuild_result_sha256']==rebuild['sha256'] and evidence['build-closure']['production_identity']['sha256']==candidate['executable_sha256'] and len(evidence['build-closure']['inputs'])==132,'compiler input closure')
    need(evidence['standalone']['status']=='EXACT_NATIVE_PCM' and evidence['standalone']['standalone_rust_synth'] is True,'independent Rust audio')
    resource=evidence['resource-closure'];trace=evidence['resource-d26-all02']
    need(resource['runtime_resource_closure'] is True and resource['capture_review_sha256']==bindings['resource-d26-all02']['sha256'] and resource['cleanup_verified'],'runtime resource inventory')
    need(trace['all_syscalls'] is True and not any(trace[k] for k in ('successful_async_engines','unknown_syscalls','unresolved_successful_opens','unterminated_pids')),'complete syscall coverage')
    checked(DATA/'verification/rust/resource-d26-all02/state.json',trace['state_sha256']);checked(DATA/trace['inventory'],trace['inventory_sha256'])
    for name in ('control-gl','control-position'):
        p=evidence[name];need(p['status']=='PHYSICAL_FAULT_REJECTED' and p['exit_code']==125 and p['accepted_pixels']==0 and p['cleanup_verified'],'physical '+name)
    for name in ('live-fp-reject','live-entry-reject'):
        p=evidence[name];need(p['status']=='FAULT_REJECTED' and p['exit_code']==125 and p['checks']['physical_fault_changed_and_rejected'] and p['checks']['pixels']==0,'physical '+name)
    need(evidence['live-d28-seed-reject']['status']=='SEED_PHYSICAL_FAULT_REJECTED','physical seed rejection')
    playback=evidence['playback'];need(playback['status']=='UNINSTRUMENTED_PLAYBACK_BASELINE' and playback['cleanup_verified'] and playback['terminal_cursor']==19845000 and playback['terminal_audio_seconds']==450,'actual playback')
    need(playback['executable_bytes']==exe.stat().st_size==728576 and all(playback[k]>0 for k in ('launch_to_first_audio_seconds','mean_present_fps','host_process_peak_hwm_bytes')),'baseline size/startup/speed/memory')
    used=sum(p.stat().st_size for p in DATA.rglob('*') if p.is_file());need(used<30000000000,'30GB budget')
    result=dict(schema='eidolon-step3-independent-audit-1',status='STEP3_INDEPENDENT_VERIFICATION_PASS',candidate_sha256=candidate['executable_sha256'],reference_manifest_sha256=PIN,
                reference_variant='D9-restored-native',state_mapping_decision='D28',production_verification_passed=True,production_accepted=False,coordinator_step3_acceptance='pending',evidence=bindings,
                coverage=dict(full_frames=27000,byte_compared_raw_anchors=510,pcm_bytes=159716352,time_cloud_draws=513000,later_physics_samples=151,curve_draws=302,curve_float_words=3824,native_static_duplicated_constant_vectors=79),
                baseline=dict(executable_bytes=728576,startup_seconds=playback['launch_to_first_audio_seconds'],presents_per_audio_second=playback['mean_present_fps'],host_peak_hwm_bytes=playback['host_process_peak_hwm_bytes']),
                limitations=['Later physics/curve certification is exactly151 scene-edge frames and draw ordinals9/18; unobserved hidden state is not certified','Native entry storage and contiguous constant-array layout are replaced only by D28 exact live-field/lifetime correspondence; static constants are not runtime dumps','Mutable runtime file hashes have post-run scope; playback uses a private null sink and external <=1.065s sampling','Prior full-media/rebuild/runtime reviews are carried forward through their hash-bound results and immutable state records; this audit does not duplicate acquisitions'],
                verifier_sources={name:sha(CHECKOUT/'tools/verify/rust'/name) for name in ('completion.py','curves.py','native_vectors.py','semantic.py','monitor_full.py','conformance.py')},
                data_bytes=used,remaining_verification_blockers=[])
    (root/'completion.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':audit()
