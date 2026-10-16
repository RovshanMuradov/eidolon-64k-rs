#!/usr/bin/env python3
"""Preserve an externally interrupted T11 run and release only its runtime resources."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def processes():
    found = []
    marker = b'WINEPREFIX=/tmp/opencode/eidolon/T11/prefix'
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            environment = (proc / 'environ').read_bytes().split(b'\0')
            if marker in environment:
                env = dict(entry.decode().split('=', 1) for entry in environment if b'=' in entry)
                settings = {k: v for k, v in env.items() if k.startswith(('WINE', 'EIDOLON_B_')) or k in
                            ('AGENT', 'PULSE_SINK', 'XDG_CACHE_HOME', '__GL_SHADER_DISK_CACHE_PATH', 'LC_ALL', 'TZ')}
                found.append(dict(pid=int(proc.name), command=(proc / 'cmdline').read_bytes().replace(b'\0', b' ').decode(), settings=settings))
        except (OSError, UnicodeError):
            continue
    return found


def log_holders(path):
    holders = []
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            for fd in (proc / 'fd').iterdir():
                if os.readlink(fd) == str(path):
                    holders.append(int(proc.name))
        except OSError:
            continue
    return holders


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--shell-id', required=True)
    parser.add_argument('--finalize-recovery', action='store_true')
    args = parser.parse_args()
    assert all(c.isalnum() or c in '-_' for c in args.run_id)
    data_root = Path(os.environ['EIDOLON_DATA'])
    shared = Path(os.environ['EIDOLON_ROOT'])
    data = data_root / 'reference' / args.run_id
    destination = Path('artifacts/reference') / f'{args.run_id}.json'
    if args.finalize_recovery:
        assert not processes() and not log_holders(data / 'runner.log')
        manifest = json.loads(destination.read_text())
        recovery_path = data / 'supervisor-recovery.json'
        recovery = json.loads(recovery_path.read_text())
        for name, digest in manifest['evidence'].items():
            if Path(name).name not in ('runner.log', 'supervisor-recovery.json'):
                assert sha(data_root / name) == digest, name
        recovery['outer_runner_finalization'] = dict(
            provisional_runner_sha256=manifest['evidence'][str((data / 'runner.log').relative_to(data_root))],
            final_runner_sha256=sha(data / 'runner.log'), closed_log_handles=True,
            explanation='Outer bash retained its initial environment in /proc and wrote terminal lines after prefix-only cleanup. All log holders are now closed; native exit remains unobserved. Recovery killed the outstanding watchdog; its TIMEOUT label is not natural completion.')
        recovery_path.write_text(json.dumps(recovery, indent=2) + '\n')
        manifest['runner_terminal'] = [line for line in (data / 'runner.log').read_text(errors='replace').splitlines() if line.startswith(('WINE_EXIT=', 'TIMEOUT'))]
        manifest['evidence'] = {str(p.relative_to(data_root)): sha(p) for p in sorted(data.iterdir()) if p.is_file()}
        manifest['resources']['runner_log_handles_closed'] = True
        destination.write_text(json.dumps(manifest, indent=2) + '\n')
        print(json.dumps(dict(manifest=str(destination), recovery_finalized=True, native_exit=None)))
        return
    assert data.exists() and not destination.exists()
    before = processes()
    targets = [p for p in before if p['settings'].get('EIDOLON_B_OUTPUT') == 'Z:' + str(data)]
    assert targets or not before, 'another T11 invocation is active'
    for item in before:
        try:
            os.kill(item['pid'], signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(2)
    for item in processes():
        try:
            os.kill(item['pid'], signal.SIGKILL)
        except ProcessLookupError:
            pass
    time.sleep(1)
    assert not processes(), 'T11 resources still active'
    deadline = time.monotonic() + 60
    while log_holders(data / 'runner.log') and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not log_holders(data / 'runner.log'), 'outer runner still writing; finalize recovery after it closes'
    modules = subprocess.check_output(['pactl', 'list', 'short', 'modules'], text=True).splitlines()
    unloaded = []
    for line in modules:
        if 'module-null-sink' in line and 'sink_name=eidolon_T11_compat' in line:
            identifier = line.split()[0]
            subprocess.run(['pactl', 'unload-module', identifier], check=True)
            unloaded.append(identifier)
    assert 'eidolon_T11_compat' not in subprocess.check_output(['pactl', 'list', 'short', 'sinks'], text=True)
    events = [json.loads(line) for line in (data / 'backend.jsonl').read_text().splitlines()]
    stage = Path('/tmp/opencode/eidolon/T11') / args.run_id
    dll_sha = sha(stage / 'opengl32.dll')
    builds = [json.loads(path.read_text()) for path in (shared / '.tools/capture/B-compat').glob('*/build.json')]
    matches = [b for b in builds if b['outputs']['opengl32.dll'] == dll_sha]
    # Multiple snapshots may produce the same PE; select the bound source's
    # boundary-probe implementation, and retain every matching build ID.
    candidates = [b for b in matches if b'boundary_probe' in (Path(b['build_directory']) / 'source-snapshot/tools/capture/proxy-b-compat/core.c').read_bytes()]
    assert len(candidates) == 1
    build, = candidates
    primary = json.loads(Path('artifacts/reference/proxy-b-d9-primary-20261016.json').read_text())
    native = stage / primary['input']['exe']
    assert sha(native) == primary['input']['exe_sha256']
    failure = dict(event='supervisor_timeout', limit_ms=120000, shell_id=args.shell_id,
                   detail='Tool deadline interrupted Python/outer runner before manifest publication; remaining prefix processes released during recovery.',
                   native_exit_observed=False)
    recovery = dict(failure=failure, recovered_utc=datetime.now(timezone.utc).isoformat(),
                    processes_before=before, processes_after=[], unloaded_private_modules=unloaded,
                    successful_presents=sum(e['event'] == 'post_present' for e in events),
                    last_event=events[-1], script_sha256=sha(__file__))
    (data / 'supervisor-recovery.json').write_text(json.dumps(recovery, indent=2) + '\n')
    environment = dict(primary['environment'])
    environment['settings'] = targets[0]['settings'] if targets else {'recovery': 'native runtime already stopped; see original command and shim snapshot'}
    manifest = dict(kind='proxy-B-D9-compatibility-diagnostic', run_id=args.run_id, reference_eligible=False,
                    finalized=False, status='failed', transformation='450-compatibility',
                    substitutions=sum(e.get('transformed', False) for e in events if e['event'] == 'shader_source'),
                    input=dict(primary['input'], executed_copy=str(native)), dependency=primary['dependency'],
                    build=build, source_provenance=[e for e in events if e['event'] == 'shader_source'],
                    stage=str(stage), prefix_baseline=primary['prefix_baseline'], environment=environment,
                    command=['bash', 'tools/run', 'tools/wine-headless', str(native)],
                    reproduce=['bash', 'tools/run', 'python', 'tools/capture/proxy-b-compat/probe.py', '--run-id', '<fresh-id>', '--mode', '450-compatibility', '--first-boundary'],
                    launcher_exit=None, first_failed_check=failure,
                    runner_terminal=[line for line in (data / 'runner.log').read_text(errors='replace').splitlines() if line.startswith(('WINE_EXIT=', 'TIMEOUT'))],
                    observations=[e for e in events if e['event'] in ('failure', 'boundary_probe', 'scene_anchor_locals',
                                  'noise_atlas', 'synth_complete', 'readback_begin', 'readback_end', 'stability_check', 'epoch')],
                    evidence={str(p.relative_to(data_root)): sha(p) for p in sorted(data.iterdir()) if p.is_file()},
                    resources=dict(prefix_processes_released=True, private_sink_unloaded=True),
                    gates='Interrupted diagnostic; partial events do not establish a boundary or planned stop. Successful primary/repeat runs remain independent.')
    destination.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(dict(manifest=str(destination), status='failed', native_exit=None,
                          successful_presents=recovery['successful_presents'], resources_released=True)))


if __name__ == '__main__':
    main()
