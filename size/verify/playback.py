#!/usr/bin/env python3
"""Uninjected wall-clock playback with bounded external audio/process telemetry.

Adapted from the read-only T30 playback.py/review_playback.py. No target hooks,
controlled clock, raw-frame capture, or DLL injection are used. Run one baseline
and one candidate with fresh copies of the same prefix and separate requested
shader-cache paths; effective driver caching is not established by this observer.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

from verify import ROOT, HERE, checked, cleanup, load, need, no_orphan_capture, now, sha, write

REFERENCE_SOURCES = {
    'tools/capture/rust/playback.py': '7d95b7f8e75bab879950159800fe64769fb37517a5cac65c4dd5c638c0b94030',
    'tools/verify/rust/review_playback.py': 'c3cf3cde2569de526bbc4ea3e1996acd691c7499db3e0253aabefaecfaf8e391',
}
LIMITATIONS = [
    'One run per executable; external approximately one-second sampling, no statistical speedup claim.',
    'First uncorked audio is an external startup-to-device-submission observation, not an internal synthesis-only or depacker timestamp.',
    'Owned-process RSS sums can double-count shared pages; GPU VRAM, kernel memory, and shared audio-server memory are excluded.',
    'Observed target VmHWM is the kernel high-water mark at sampled times; process exit can hide a later peak.',
    'Fresh copied Wine prefixes and distinct requested shader-cache paths; effective driver-cache behavior, filesystem/page caches, and ambient desktop activity are not established as cold or controlled.',
    'Private null sink measures live-clock playback submission, not physical-speaker output.',
    'No per-frame latency distribution is measured; presentation counts are from the real-clock endpoint, not capture-file I/O.',
    'Wine on Linux; native Windows execution is untested.',
]


def processes(prefix, sid):
    """Own runner session plus Wine-prefix services, including reparented services."""
    rows = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            env = (proc / 'environ').read_bytes().split(b'\0')
            if os.getsid(int(proc.name)) != sid and f'WINEPREFIX={prefix}'.encode() not in env:
                continue
            status = dict(line.split(':', 1) for line in (proc / 'status').read_text().splitlines() if ':' in line)
            rows.append(dict(pid=int(proc.name),
                             rss_bytes=int(status.get('VmRSS', '0 kB').split()[0]) * 1024,
                             hwm_bytes=int(status.get('VmHWM', '0 kB').split()[0]) * 1024))
        except OSError:
            pass
    return rows


def prefix_seed(prefix):
    names = ('system.reg', 'user.reg', 'userdef.reg',
             'drive_c/windows/system32/drivers/gm.dls', 'drive_c/windows/syswow64/drivers/gm.dls')
    return {name: sha(prefix / name) for name in names}


def stop(child, env):
    if child is not None and child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
    # This environment always names this acquisition's new private prefix.
    subprocess.run(['wineserver', '-k'], env=env, check=False, timeout=15,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run(args):
    cfg = load(args.config)
    for name, pin in REFERENCE_SOURCES.items():
        checked(Path(cfg['toolkit']) / name, pin)
    job = args.job.resolve()
    need(job.is_relative_to(ROOT / '.build'), 'benchmark job must be under this checkout/.build')
    for path in cfg.values():
        need(not job.is_relative_to(Path(path).resolve()), 'benchmark output overlaps reference input')
    need(1 <= args.timeout <= 1020, 'playback timeout must be <=1020 seconds (two-run budget)')
    exe = checked(args.exe.resolve(), args.sha256)
    need(exe.is_relative_to(ROOT / '.build'), 'preserve the executable in this checkout/.build first')
    job.parent.mkdir(parents=True, exist_ok=True)
    with (ROOT / '.build/verify-capture.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        no_orphan_capture()
        job.mkdir()
        prefix = job / 'prefix'
        subprocess.run(['cp', '-a', '--reflink=auto', str(Path(cfg['prefix_template']).resolve()), str(prefix)], check=True)
        seed = prefix_seed(prefix)
        (job / 'cache/nvidia').mkdir(parents=True)
        shutil.copyfile(__file__, job / 'playback.py')
        shutil.copyfile(HERE / 'headless.sh', job / 'headless.sh')
        sink = 'eidolon_playback_' + sha(job / 'playback.py')[:6] + '_' + job.name.replace('-', '_')
        env = {k: v for k, v in os.environ.items() if not k.startswith(('EIDOLON_RUST_', 'EIDOLON_CURVE_', 'EIDOLON_SEED_'))}
        env.update(WINEPREFIX=str(prefix), EIDOLON_SCRATCH=str(job), WINE_TIMEOUT=str(args.timeout),
                   WINEDEBUG='-all', PULSE_SINK=sink, WINEDLLOVERRIDES='winemenubuilder.exe,mscoree,mshtml=d',
                   XDG_CACHE_HOME=str(job / 'cache'), __GL_SHADER_DISK_CACHE_PATH=str(job / 'cache/nvidia'))
        command = ['bash', str(job / 'headless.sh'), str(exe), '--play']
        state = dict(schema='eidolon-size-playback-1', phase='running', pid=os.getpid(), job=str(job),
                     candidate=str(exe), candidate_sha256=sha(exe), candidate_bytes=exe.stat().st_size,
                     command=command, sources={n: sha(job / n) for n in ('playback.py', 'headless.sh')},
                     reference_sources=REFERENCE_SOURCES, config_sha256=sha(args.config), prefix_seed_sha256=seed,
                     wine_prefix=str(prefix), sink=sink, started_utc=now(),
                     wine_version=subprocess.check_output(['wine', '--version'], text=True).strip(),
                     environment={k: v for k, v in env.items() if k.startswith(('EIDOLON_', 'WINE', 'PULSE_', '__GL_')) or k == 'XDG_CACHE_HOME'},
                     process=None, first_target_seconds=None, last_target_seconds=None,
                     first_audio_seconds=None, last_audio_seconds=None, peak_target_rss_bytes=0,
                     peak_target_hwm_bytes=0, peak_owned_process_rss_bytes=0, samples=0,
                     production_accepted=False, native_windows_tested=False, limitations=LIMITATIONS)
        module = subprocess.check_output(['pactl', 'load-module', 'module-null-sink', 'sink_name=' + sink], text=True).strip()
        child, rc, seen_files = None, 125, set()
        start = time.monotonic()
        def interrupted(signum, _frame):
            raise InterruptedError(f'playback supervisor received signal {signum}')
        previous = signal.signal(signal.SIGTERM, interrupted)
        write(job / 'state.json', state)
        try:
            with (job / 'runner.log').open('wb') as log, (job / 'telemetry.jsonl').open('w') as telemetry:
                child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                state.update(runner_pid=child.pid, runner_sid=child.pid)
                write(job / 'state.json', state)
                while child.poll() is None:
                    elapsed = time.monotonic() - start
                    need(elapsed <= args.timeout + 20, 'external playback watchdog timeout')
                    owned = processes(prefix, child.pid)
                    row = dict(seconds=round(elapsed, 6), owned_processes=owned,
                               owned_rss_bytes=sum(p['rss_bytes'] for p in owned), load_average=list(os.getloadavg()))
                    state['peak_owned_process_rss_bytes'] = max(state['peak_owned_process_rss_bytes'], row['owned_rss_bytes'])
                    for p in owned:
                        if state['process'] is not None and p['pid'] != state['process']:
                            continue
                        try:
                            mappings = Path(f"/proc/{p['pid']}/maps").read_text()
                            if str(exe) not in mappings:
                                continue
                            if state['process'] is None:
                                state.update(process=p['pid'], first_target_seconds=row['seconds'])
                            state['last_target_seconds'] = row['seconds']
                            row.update(target_pid=p['pid'], target_rss_bytes=p['rss_bytes'], target_hwm_bytes=p['hwm_bytes'])
                            state['peak_target_rss_bytes'] = max(state['peak_target_rss_bytes'], p['rss_bytes'])
                            state['peak_target_hwm_bytes'] = max(state['peak_target_hwm_bytes'], p['hwm_bytes'])
                            for line in mappings.splitlines():
                                fields = line.split(maxsplit=5)
                                if len(fields) == 6 and fields[5].startswith('/'):
                                    seen_files.add(fields[5])
                        except OSError:
                            pass
                    streams = json.loads(subprocess.check_output(['pactl', '--format=json', 'list', 'sink-inputs'], text=True, timeout=10))
                    audio = [s for s in streams if s.get('properties', {}).get('application.process.id') == str(state['process'])]
                    if audio:
                        row['audio_streams'] = audio
                        if any(not s['corked'] for s in audio):
                            if state['first_audio_seconds'] is None:
                                state['first_audio_seconds'] = row['seconds']
                            state['last_audio_seconds'] = row['seconds']
                    telemetry.write(json.dumps(row) + '\n')
                    telemetry.flush()
                    state['samples'] += 1
                    time.sleep(max(0, 1 - (time.monotonic() - start - elapsed)))
                rc = child.returncode
        except BaseException as exc:
            state['supervisor_error'] = str(exc)
            stop(child, env)
            raise
        finally:
            signal.signal(signal.SIGTERM, previous)
            state.update(exit_code=rc, elapsed_seconds=time.monotonic() - start)
            subprocess.run(['pactl', 'unload-module', module], check=False)
            state.update(phase='closed', candidate_after_sha256=sha(exe),
                         runner_log_sha256=sha(job / 'runner.log'), telemetry_sha256=sha(job / 'telemetry.jsonl'),
                         mapped_files={p: sha(p) for p in sorted(seen_files) if Path(p).is_file()},
                         unavailable_mapped_files=[p for p in sorted(seen_files) if not Path(p).is_file()], closed_utc=now())
            write(job / 'state.json', state)
        return dict(job=str(job), candidate_sha256=state['candidate_sha256'], exit_code=rc, seconds=state['elapsed_seconds'])


def review(job):
    job = Path(job).resolve()
    state = load(job / 'state.json')
    result = dict(schema='eidolon-size-playback-review-1', status='FAIL', candidate_sha256=state['candidate_sha256'],
                  candidate_bytes=state['candidate_bytes'], state_sha256=sha(job / 'state.json'), job=str(job),
                  observed_utc=now(), verifier_sha256=sha(__file__), production_accepted=False,
                  native_windows_tested=False, limitations=LIMITATIONS, failures=[])
    try:
        need(state['schema'] == 'eidolon-size-playback-1' and state['phase'] == 'closed', 'playback not closed')
        need(not state.get('supervisor_error'), 'playback supervisor interrupted')
        exe = checked(state['candidate'], state['candidate_sha256'])
        need(sha(exe) == state['candidate_after_sha256'] and exe.stat().st_size == state['candidate_bytes'], 'executable closure')
        for name, pin in state['sources'].items():
            checked(job / name, pin)
        checked(job / 'runner.log', state['runner_log_sha256'])
        checked(job / 'telemetry.jsonl', state['telemetry_sha256'])
        need(state['command'] == ['bash', str(job / 'headless.sh'), str(exe), '--play'], 'uninjected command')
        for path, pin in state['mapped_files'].items():
            checked(path, pin)
        need(str(exe) in state['mapped_files'] and not any(Path(p).name.lower() == 'live.dll' for p in state['mapped_files']), 'candidate mapping or capture DLL present')
        log = (job / 'runner.log').read_text()
        endpoint = re.findall(r'EIDOLON_RUNTIME mode=playback reason=natural_exit queries=(\d+) frames=(\d+) terminal_cursor=(\d+)', log)
        need(len(endpoint) == 1, 'natural real-clock endpoint missing/ambiguous')
        queries, frames, cursor = map(int, endpoint[0])
        need(queries == frames + 1 and frames > 0 and 19845000 <= cursor < 19964544, 'natural playback terminal extent')
        wrapper = re.findall(r'^WINE_EXIT=(\d+|none) GAMESCOPE_EXIT=(\d+) SECONDS=\d+$', log, re.MULTILINE)
        result['process_exit'] = dict(capture=state['exit_code'], wrapper_records=wrapper)
        need(not re.search(r'TIMEOUT|Unhandled exception|EIDOLON_RUNTIME error:|cleanup failed:|waveOutClose failed:|PLANNED_SHORT_STOP', log), 'playback runtime error')
        rows = [json.loads(line) for line in (job / 'telemetry.jsonl').read_text().splitlines()]
        need(len(rows) == state['samples'] and len(rows) > 1 and all(a['seconds'] < b['seconds'] for a, b in zip(rows, rows[1:])), 'telemetry sample coverage/order')
        audio = [(r, s) for r in rows for s in r.get('audio_streams', []) if not s['corked']]
        need(audio, 'actual uncorked audio stream not observed')
        for _, stream in audio:
            need(stream['properties']['application.process.id'] == str(state['process']) and
                 stream['properties']['target.object'] == state['sink'] and
                 stream['sample_specification'] == 'float32le 2ch 44100Hz', 'audio stream attribution/format/sink')
        measured = dict(launcher_wall_seconds=state['elapsed_seconds'],
                        launch_to_first_uncorked_audio_seconds=audio[0][0]['seconds'],
                        target_first_seen_seconds=state['first_target_seconds'], target_last_seen_seconds=state['last_target_seconds'],
                        observed_audio_span_seconds=audio[-1][0]['seconds'] - audio[0][0]['seconds'],
                        target_peak_sampled_rss_bytes=max(r.get('target_rss_bytes', 0) for r in rows),
                        target_max_observed_hwm_bytes=max(r.get('target_hwm_bytes', 0) for r in rows),
                        owned_process_peak_sampled_rss_bytes=max(r['owned_rss_bytes'] for r in rows),
                        sample_interval_max_seconds=max(b['seconds'] - a['seconds'] for a, b in zip(rows, rows[1:])),
                        samples=len(rows), audio_observations=len(audio), frames_presented=frames, queries=queries, terminal_cursor=cursor)
        need(measured['target_peak_sampled_rss_bytes'] == state['peak_target_rss_bytes'] and
             measured['target_max_observed_hwm_bytes'] == state['peak_target_hwm_bytes'] and
             measured['owned_process_peak_sampled_rss_bytes'] == state['peak_owned_process_rss_bytes'], 'resource summary differs from raw telemetry')
        result.update(measurements=measured, prefix_seed_sha256=state['prefix_seed_sha256'], wine_version=state['wine_version'],
                      environment=state['environment'], reference_sources=state['reference_sources'],
                      evidence_sha256=dict(sources=state['sources'], runner_log=state['runner_log_sha256'], telemetry=state['telemetry_sha256']),
                      mapped_file_count=len(state['mapped_files']), mapped_candidate_sha256=state['mapped_files'][str(exe)],
                      context_log_lines=[line for line in log.splitlines() if 'gamescope version' in line or 'selecting physical device' in line])
        cache = Path(state['environment']['__GL_SHADER_DISK_CACHE_PATH'])
        result['shader_cache_observation'] = dict(configured_path=str(cache), directory_exists=cache.is_dir(),
                                                  files_observed=sum(p.is_file() for p in cache.rglob('*')) if cache.is_dir() else 0,
                                                  effective_driver_cache_behavior='not established by external telemetry; no cold-cache claim')
        need(state['exit_code'] == 0 and wrapper == [('0', '0')], 'Wine/Gamescope closure failed')
        result['cleanup'] = cleanup(state)
        result['status'] = 'UNINSTRUMENTED_PLAYBACK_MEASURED'
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result['failures'].append(str(exc))
    if state['phase'] == 'closed' and 'cleanup' not in result:
        try:
            result['cleanup'] = cleanup(state)
        except (ValueError, OSError, KeyError) as exc:
            result['failures'].append(str(exc))
    return result


def compare(args):
    baseline, candidate, media = (load(path) for path in (args.baseline, args.candidate, args.media))
    need(baseline['status'] == candidate['status'] == 'UNINSTRUMENTED_PLAYBACK_MEASURED' and
         not baseline['failures'] and not candidate['failures'], 'paired playback did not pass strict reviews')
    need(media['status'] == 'FULL_MEDIA_EXACT_PARTIAL' and media['full'] and not media['failures'] and
         media['candidate_sha256'] == candidate['candidate_sha256'], 'final full-media identity/status differs')
    need(baseline['prefix_seed_sha256'] == candidate['prefix_seed_sha256'] and
         baseline['wine_version'] == candidate['wine_version'] and
         baseline['context_log_lines'] == candidate['context_log_lines'] and
         baseline['evidence_sha256']['sources'] == candidate['evidence_sha256']['sources'], 'paired runtime/prefix/tool conditions differ')
    for key in ('WINE_TIMEOUT', 'WINEDEBUG', 'WINEDLLOVERRIDES'):
        need(baseline['environment'][key] == candidate['environment'][key], 'paired environment differs: ' + key)
    states = []
    for report in (baseline, candidate, media):
        states.append(load(checked(Path(report['job']) / 'state.json', report['state_sha256'])))
        need(not report['production_accepted'] and not any(report['cleanup'].values()), 'review cleanup/acceptance inconsistency')
    need(states[2]['closed_utc'] <= states[0]['started_utc'] and states[0]['closed_utc'] <= states[1]['started_utc'],
         'full capture and paired playbacks overlap or have the wrong order')
    metrics = ('launcher_wall_seconds', 'launch_to_first_uncorked_audio_seconds',
               'target_peak_sampled_rss_bytes', 'target_max_observed_hwm_bytes', 'owned_process_peak_sampled_rss_bytes')
    comparison = {}
    for key in metrics:
        a, b = baseline['measurements'][key], candidate['measurements'][key]
        comparison[key] = dict(baseline=a, final=b, observed_delta=b-a, observed_delta_percent=100*(b/a-1))
    result = dict(schema='eidolon-size-paired-review-1', status='FULL_MEDIA_EXACT_AND_PAIRED_PLAYBACK_OBSERVED',
                  candidate_sha256=candidate['candidate_sha256'], candidate_bytes=candidate['candidate_bytes'],
                  baseline_sha256=baseline['candidate_sha256'], baseline_bytes=baseline['candidate_bytes'],
                  observed_utc=now(), verifier_sha256=sha(__file__), production_accepted=False, native_windows_tested=False,
                  reports={name: dict(path=Path(path).name, sha256=sha(path)) for name, path in
                           [('full_media', args.media), ('baseline_playback', args.baseline), ('final_playback', args.candidate)]},
                  matched_conditions=dict(prefix_seed_sha256=baseline['prefix_seed_sha256'], wine=baseline['wine_version'],
                                          context_log_lines=baseline['context_log_lines'], source_pins=baseline['evidence_sha256']['sources'],
                                          resolution=[1920, 1080], cache_policy='fresh separate Wine prefixes and distinct requested shader-cache paths; no cold-cache claim',
                                          order='baseline then final; serialized after full capture'),
                  shader_cache_observations=dict(baseline=baseline['shader_cache_observation'], final=candidate['shader_cache_observation']),
                  observations=comparison, timed_runner_total_seconds=sum(r['measurements']['launcher_wall_seconds'] for r in (baseline, candidate)),
                  playback_runs=2, run_limit=2, cleanup_verified=True, limitations=LIMITATIONS,
                  interpretation='Observed deltas describe one sequential pair. No statistical speedup, slowdown cause, or formal performance acceptance is inferred.',
                  separate_attestations=['Clean-checkout reproducibility belongs to a separate integrating-session attestation; this report makes no claim about its completion.'],
                  remaining=['agreed formal acceptance criteria', 'native Windows execution'])
    if args.console:
        text = args.console.read_text()
        warnings = [line for line in text.splitlines() if line.startswith('Invalid ASCII character:')]
        need(all('Invalid ASCII character:' not in (Path(r['job']) / 'runner.log').read_text() for r in (baseline, candidate)), 'ASCII diagnostics also occur in target logs')
        result['observer_console'] = dict(path=str(args.console), sha256=sha(args.console), warning_count=len(warnings),
                                          warning_kinds=sorted(set(warnings)),
                                          scope='Warnings were emitted on the external observer console, not either target runner log. The pactl JSON/audio attribution checks succeeded; the triggering metadata was not isolated.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    p = sub.add_parser('run')
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--exe', type=Path, required=True)
    p.add_argument('--sha256', required=True)
    p.add_argument('--job', type=Path, required=True)
    p.add_argument('--timeout', type=int, default=1020)
    p = sub.add_parser('review')
    p.add_argument('--job', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('compare')
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--media', type=Path, required=True)
    p.add_argument('--console', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args) if args.operation == 'run' else (review(args.job) if args.operation == 'review' else compare(args))
    if args.operation != 'run':
        write(args.output, result)
    print(json.dumps(result, indent=2))
    return int(result.get('status') == 'FAIL' or result.get('exit_code', 0) != 0)


if __name__ == '__main__':
    raise SystemExit(main())
