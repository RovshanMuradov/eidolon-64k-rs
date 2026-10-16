#!/usr/bin/env python3
"""D9 compatibility-modified diagnostic; never publishes an accepted reference."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import zipfile
import math
import signal
import time
from timeline import retention
from observations import events as read_events, pack


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def tree(path):
    return {str(p.relative_to(path)): ('link:' + os.readlink(p) if p.is_symlink() else sha(p))
            for p in sorted(path.rglob('*')) if p.is_symlink() or p.is_file()}


def quiet_prefix(prefix):
    marker = f'WINEPREFIX={prefix}'.encode()
    for process in Path('/proc').glob('[0-9]*/environ'):
        try:
            assert marker not in process.read_bytes().split(b'\0'), f'busy prefix: {process.parent}'
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--mode', choices=['unchanged', '450-compatibility'], required=True)
    parser.add_argument('--frames', type=int, default=3)
    parser.add_argument('--first-boundary', action='store_true')
    parser.add_argument('--active-volume', action='store_true')
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--storage', choices=['reference','hashes'], default='reference')
    parser.add_argument('--reference-variant',choices=['D9-restored-native'])
    parser.add_argument('--throughput-from', type=Path)
    parser.add_argument('--build-from', type=Path, help='reuse an immutable measured run build, not a new link')
    parser.add_argument('--fault', choices=['wrong-thread','unknown-route','wrong-hdc','wrong-hglrc',
                        'preexisting-error','readback-error','restore-error','fingerprint','shader-count',
                        'exception-gpr','exception-fp'])
    args = parser.parse_args()
    assert args.run_id and all(c.isalnum() or c in '-_' for c in args.run_id)
    assert 1 <= args.frames <= 600
    assert not args.full or (not args.active_volume and not args.first_boundary and not args.fault and
                            args.mode=='450-compatibility' and args.reference_variant=='D9-restored-native' and
                            args.throughput_from)
    assert args.full or args.storage=='reference'
    assert not args.first_boundary or (args.mode == '450-compatibility' and args.frames == 3)
    assert not args.first_boundary or (args.throughput_from and not args.fault)
    assert not args.active_volume or (not args.first_boundary and args.mode == '450-compatibility' and
                                      args.frames == 3 and args.throughput_from and not args.fault and
                                      args.reference_variant == 'D9-restored-native')
    stage_frames = 27000 if args.full else 5763 if args.active_volume else 1443 if args.first_boundary else args.frames
    rows, retained = retention(stage_frames, full=args.full)
    if args.full:
        assert len(retained)==510
    if args.storage=='hashes':
        retained=[]
    data_root = Path(os.environ['EIDOLON_DATA'])
    data = data_root / 'reference' / args.run_id
    destination = Path('artifacts/reference') / f'{args.run_id}{"-acquisition" if args.reference_variant else ""}.json'
    assert not destination.exists()
    # Include retained raw plus worst-case Zstandard extent, PCM, atlas and
    # the measured ~82 MB ordered observation stream before allocating a stage.
    reserve = 1_000_000_000 + 2*len(retained)*8_294_400 + stage_frames*80000
    assert sum(p.stat().st_size for p in data_root.rglob('*') if p.is_file()) + reserve < 30_000_000_000
    pinned_run = args.build_from or (args.throughput_from if not args.full else None)
    if pinned_run:
        pinned = json.loads(pinned_run.read_text())
        build = Path(pinned['build']['build_directory'])
    else:
        build = Path(subprocess.check_output(['python', 'tools/capture/proxy-b-compat/build.py'], text=True).strip())
    build_manifest = json.loads((build / 'build.json').read_text())
    if pinned_run:
        assert build_manifest == pinned['build']
    for name,digest in build_manifest['outputs'].items():
        assert sha(build/name) == digest, name
    runner = Path(__file__)
    runner_snapshot = Path(os.environ['EIDOLON_ROOT'])/'.tools/capture/runner-snapshots'/sha(runner)/runner.name
    runner_snapshot.parent.mkdir(parents=True,exist_ok=True)
    if runner_snapshot.exists():
        assert runner_snapshot.read_bytes() == runner.read_bytes()
    else:
        runner_snapshot.write_bytes(runner.read_bytes())
    original_path = Path('artifacts/reference/proxy-b-g1-20261016.json')
    original = json.loads(original_path.read_text())
    scratch = Path('/tmp/opencode/eidolon/T16')
    prefix = scratch / 'prefix'
    baseline = Path(os.environ['EIDOLON_ROOT']) / '.tools/capture/T11-prefix-baseline'
    inventory = baseline.with_suffix('.json')
    scratch.mkdir(parents=True, exist_ok=True)
    if not baseline.exists():
        source = scratch / 'prefix-baseline'
        quiet_prefix(source)
        subprocess.run(['cp', '-a', '--reflink=auto', str(source), str(baseline)], check=True)
        snapshot = tree(baseline)
        inventory.write_text(json.dumps(snapshot, sort_keys=True, indent=2) + '\n')
    expected = json.loads(inventory.read_text())
    assert tree(baseline) == expected
    quiet_prefix(prefix)
    if prefix.exists():
        prefix.rename(scratch / f'prefix-before-{args.run_id}')
    subprocess.run(['cp', '-a', '--reflink=auto', str(baseline), str(prefix)], check=True)
    assert tree(prefix) == expected
    stage = scratch / args.run_id
    stage.mkdir(exist_ok=False)
    for name in ('opengl32.dll', 'winmm.dll'):
        shutil.copyfile(build / name, stage / name)
        assert sha(stage / name) == build_manifest['outputs'][name]
    archive = Path(os.environ['EIDOLON_ROOT']) / original['input']['archive']
    assert sha(archive) == original['input']['archive_sha256']
    with zipfile.ZipFile(archive) as z:
        (stage / original['input']['exe']).write_bytes(z.read(original['input']['exe']))
    native = stage / original['input']['exe']
    exe_before_sha256 = sha(native)
    assert exe_before_sha256 == original['input']['exe_sha256']
    bank_manifest = json.loads(Path('artifacts/reference/dependencies/gm-dls.json').read_text())
    bank_hash = sha(data_root / 'reference/dependencies/gm.dls')
    for arch in ('system32', 'syswow64'):
        assert sha(prefix / f'drive_c/windows/{arch}/drivers/gm.dls') == bank_hash
    data.mkdir(parents=True, exist_ok=False)
    (data/'retention.txt').write_text(''.join(f'{n}\n' for n in retained))
    env = {k: v for k, v in os.environ.items() if not k.startswith(('EIDOLON_A_', 'EIDOLON_B_'))}
    parent_settings = {k: v for k,v in env.items() if k.startswith('WINE')}
    runner_seconds = 600
    supervision = dict(runner_seconds=runner_seconds, cleanup_margin_seconds=600, tool='background; no external deadline')
    if args.first_boundary or args.active_volume or args.full:
        measured = json.loads(args.throughput_from.read_text())
        assert measured['status'] in ('partial','complete')
        if not args.full:
            assert all(measured['build']['outputs'][name] == build_manifest['outputs'][name]
                       for name in ('opengl32.dll','winmm.dll')), 'throughput must measure the identical shims'
        rate, = [e for e in measured['observations'] if e['event'] == 'throughput']
        assert rate['frames'] >= 60 and rate['wall_ticks'] > 0
        seconds_per_frame = rate['wall_ticks'] / rate['frequency'] / rate['frames']
        multiplier = 8 if args.full else 4
        runner_seconds = math.ceil(stage_frames * seconds_per_frame * multiplier + 600)
        supervision.update(runner_seconds=runner_seconds, measured_seconds_per_frame=seconds_per_frame,
                           throughput_manifest=str(args.throughput_from), throughput_sha256=sha(args.throughput_from),
                            measured_build_id=measured['build']['build_id'],
                            multiplier=multiplier, startup_allowance_seconds=600)
    supervision['python_supervisor_seconds'] = runner_seconds + 600
    env.update(AGENT='T16', WINE_TIMEOUT=str(runner_seconds), WINE_W='1920', WINE_H='1080',
               WINEPREFIX=str(prefix), WINEARCH='win64',
               WINEDLLOVERRIDES='opengl32,winmm=n,b;winemenubuilder.exe,mscoree,mshtml=d',
               WINEDEBUG='-all,+loaddll', EIDOLON_B_LOG='Z:' + str(data / 'backend.jsonl'),
               EIDOLON_B_BOOTSTRAP='capture-probe', EIDOLON_B_OUTPUT='Z:' + str(data),
                EIDOLON_B_FRAMES=str(args.frames), EIDOLON_B_COMPAT=args.mode,
                EIDOLON_B_RETENTION='Z:' + str(data/'retention.txt'),
                PULSE_SINK='eidolon_T16_compat', LC_ALL='C', TZ='UTC',
               XDG_CACHE_HOME=str(stage / 'cache'), __GL_SHADER_DISK_CACHE_PATH=str(stage / 'cache/nvidia'))
    env.pop('DISPLAY', None)
    env.pop('WAYLAND_DISPLAY', None)
    if args.first_boundary or args.active_volume:
        env['EIDOLON_B_BOUNDARY_PROBE'] = str(stage_frames)
    if args.full:
        env['EIDOLON_B_FULL']='27000'
    if args.fault:
        env['EIDOLON_B_FAULT'] = args.fault
        if args.fault == 'fingerprint':
            env['EIDOLON_B_BAD_FINGERPRINT'] = '1'
    command = ['bash', 'tools/run', 'tools/wine-headless', str(native)]
    started = datetime.now(timezone.utc).isoformat()
    monotonic_start = time.monotonic()
    sink = subprocess.check_output(['pactl', 'load-module', 'module-null-sink',
                                    'sink_name=eidolon_T16_compat', 'rate=44100', 'channels=2'], text=True).strip()
    cleanup_errors = []
    try:
        with (data / 'runner.log').open('wb') as log:
            process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                launcher_exit = process.wait(timeout=supervision['python_supervisor_seconds'])
                supervisor_timeout = False
            except subprocess.TimeoutExpired:
                supervisor_timeout = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                subprocess.run(['wineserver','-k'], env=env, check=False)
                launcher_exit = 124
    finally:
        sink_result = subprocess.run(['pactl', 'unload-module', sink], check=False)
        if sink_result.returncode:
            cleanup_errors.append(f'private sink unload exit {sink_result.returncode}; module {sink}')
    try:
        quiet_prefix(prefix)
        prefix_released = True
    except AssertionError as error:
        prefix_released = False
        cleanup_errors.append(str(error))
    # Stream every observation; retain only bounded summaries in Git. The full
    # byte-exact ordered log stays hash-bound in data, including on failure.
    observations=[]; sources=[]; event_counts={}; last_seq=0
    omitted={'lookup','clock','shader_source','pre_present','post_present','frame_state','scene_state',
             'scene_pass','clock_routes_checked','node_rng','node_probe_restoration','node_coverage'}
    for e in read_events(data/'backend.jsonl') if (data/'backend.jsonl').exists() else []:
        assert e['seq']==last_seq+1
        last_seq=e['seq']; name=e['event']; event_counts[name]=event_counts.get(name,0)+1
        if name=='shader_source':
            sources.append(e)
        if name in omitted or (name=='program_use' and e['program']!=2 and not e['post_error']):
            continue
        if name=='scene_anchor_locals' and e['n'] not in {0,1,2,1438,1439,1440,1441,1442,5758,5759,5760,5761,5762,26999}:
            continue
        observations.append(e)
    events=observations
    stream=pack(data/'backend.jsonl') if args.full and (data/'backend.jsonl').exists() else None
    if stream:
        stream['events']=last_seq; stream['event_counts']=event_counts
    failure = next((e for e in events if e['event'] == 'failure'), None)
    endpoint=[e for e in events if e['event']=='native_endpoint']
    full_ok=(len(endpoint)==1 and event_counts.get('native_exit_forward')==1 and
             event_counts.get('pre_present')==event_counts.get('post_present')==27000 and
             not event_counts.get('planned_partial_stop'))
    if args.full and not full_ok and not failure:
        failure=dict(event='host_failure',reason='missing_complete_native_endpoint')
    bundle = {p: sha(p) for p in original['bundle']}
    bundle.update(build_manifest['sources'])
    manifest = dict(kind='proxy-B-D9-compatibility-diagnostic', run_id=args.run_id,
                     reference_eligible=False, finalized=False,
                     staged_scope=dict(sequential_frames=stage_frames,retained_indices=retained,native_rows=rows),
                     reference_variant=args.reference_variant,
                     executed_file_observation=dict(path=str(native),before_sha256=exe_before_sha256,
                                                    after_sha256=sha(native)),
                     status='failed' if failure or launcher_exit or cleanup_errors else 'complete' if args.full else 'partial',
                     storage=args.storage, full_run=args.full, ordered_stream=stream,
                    transformation=args.mode, substitutions=sum(e['transformed'] for e in sources),
                    input=dict(original['input'], executed_copy=str(native)), dependency=bank_manifest, build=build_manifest, bundle=bundle,
                    host_runner=dict(path=str(runner_snapshot),sha256=sha(runner_snapshot)),
                    source_provenance=sources, stage=str(stage),
                    prefix_baseline=dict(recipe='persistent copy of stopped T11/T2 baseline; cp -a --reflink=auto; verify full tree before each invocation; launcher applies pinned registry defaults',
                                         directory=str(baseline), inventory=str(inventory), inventory_sha256=sha(inventory),
                                         fresh_tree_equal=True),
                    environment=dict(os=platform.platform(), wine=subprocess.check_output(['wine', '--version'], text=True).strip(),
                                     packages=subprocess.check_output(['pacman', '-Q', 'wine', 'gamescope', 'nvidia-utils', 'lib32-nvidia-utils'], text=True).splitlines(),
                                     gpu=subprocess.check_output(['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'], text=True).strip(),
                                     display=original['environment']['display'], parent_settings=parent_settings,
                                     settings={k: v for k, v in env.items() if k.startswith(('WINE', 'EIDOLON_B_')) or k in
                                               ('AGENT', 'PULSE_SINK', 'XDG_CACHE_HOME', '__GL_SHADER_DISK_CACHE_PATH', 'LC_ALL', 'TZ')}),
                      reproduce=['bash', 'tools/run', 'python', 'tools/capture/proxy-b-compat/probe.py', '--run-id', '<fresh-id>', '--mode', args.mode, '--frames', str(args.frames)] + ([('--full' if args.full else '--active-volume' if args.active_volume else '--first-boundary'),'--throughput-from',str(args.throughput_from)] if args.first_boundary or args.active_volume or args.full else []) + (['--storage',args.storage] if args.full else []) + (['--reference-variant',args.reference_variant] if args.reference_variant else []) + (['--build-from',str(args.build_from)] if args.build_from else []) + (['--fault',args.fault] if args.fault else []),
                    command=command, started_utc=started, finished_utc=datetime.now(timezone.utc).isoformat(),
                    launcher_exit=launcher_exit, first_failed_check=failure, supervision=supervision,
                    supervisor_timeout=supervisor_timeout, elapsed_seconds=time.monotonic()-monotonic_start,
                    runner_terminal=[line for line in (data / 'runner.log').read_text(errors='replace').splitlines() if line.startswith(('WINE_EXIT=', 'TIMEOUT'))],
                     observations=observations,
                    evidence={str(p.relative_to(data_root)): sha(p) for p in sorted(data.iterdir()) if p.is_file()},
                    D2=original['D2'], resources=dict(prefix_processes_released=prefix_released,
                         private_sink_unloaded=sink_result.returncode == 0, errors=cleanup_errors),
                    gates='Diagnostic observations only; G1 ABI/canaries, G2-G4 and T10 eligibility require independent review.')
    destination.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(dict(manifest=str(destination), launcher_exit=launcher_exit, failure=failure,
                         programs=sum(e['event'] == 'shader_program' for e in events),
                         failed_links=[e['program'] for e in events if e['event'] == 'shader_program' and not e['link_status']],
                          frames=event_counts.get('post_present',0))))
    return 1 if failure or launcher_exit or cleanup_errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
