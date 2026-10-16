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


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
    args = parser.parse_args()
    assert args.run_id and all(c.isalnum() or c in '-_' for c in args.run_id)
    assert 1 <= args.frames <= 600
    data_root = Path(os.environ['EIDOLON_DATA'])
    data = data_root / 'reference' / args.run_id
    destination = Path('artifacts/reference') / f'{args.run_id}.json'
    assert not destination.exists()
    assert sum(p.stat().st_size for p in data_root.rglob('*') if p.is_file()) + 250_000_000 + args.frames * 8_294_400 < 30_000_000_000
    build = Path(subprocess.check_output(['python', 'tools/capture/proxy-b-compat/build.py'], text=True).strip())
    build_manifest = json.loads((build / 'build.json').read_text())
    original_path = Path('artifacts/reference/proxy-b-g1-20261016.json')
    original = json.loads(original_path.read_text())
    scratch = Path('/tmp/opencode/eidolon/T11')
    prefix, baseline = scratch / 'prefix', scratch / 'prefix-baseline'
    scratch.mkdir(parents=True, exist_ok=True)
    if not baseline.exists():
        source = Path('/tmp/opencode/eidolon/T2/prefix')
        quiet_prefix(source)
        subprocess.run(['cp', '-a', '--reflink=auto', str(source), str(baseline)], check=True)
        snapshot = tree(baseline)
        (scratch / 'prefix-baseline.json').write_text(json.dumps(snapshot, sort_keys=True, indent=2) + '\n')
    expected = json.loads((scratch / 'prefix-baseline.json').read_text())
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
    assert sha(native) == original['input']['exe_sha256']
    bank_manifest = json.loads(Path('artifacts/reference/dependencies/gm-dls.json').read_text())
    bank_hash = sha(data_root / 'reference/dependencies/gm.dls')
    for arch in ('system32', 'syswow64'):
        assert sha(prefix / f'drive_c/windows/{arch}/drivers/gm.dls') == bank_hash
    data.mkdir(parents=True, exist_ok=False)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('EIDOLON_A_', 'EIDOLON_B_'))}
    env.update(AGENT='T11', WINE_TIMEOUT='300', WINE_W='1920', WINE_H='1080',
               WINEDLLOVERRIDES='opengl32,winmm=n,b;winemenubuilder.exe,mscoree,mshtml=d',
               WINEDEBUG='-all,+loaddll', EIDOLON_B_LOG='Z:' + str(data / 'backend.jsonl'),
               EIDOLON_B_BOOTSTRAP='capture-probe', EIDOLON_B_OUTPUT='Z:' + str(data),
               EIDOLON_B_FRAMES=str(args.frames), EIDOLON_B_COMPAT=args.mode,
               PULSE_SINK='eidolon_T11_compat', LC_ALL='C', TZ='UTC',
               XDG_CACHE_HOME=str(stage / 'cache'), __GL_SHADER_DISK_CACHE_PATH=str(stage / 'cache/nvidia'))
    env.pop('DISPLAY', None)
    env.pop('WAYLAND_DISPLAY', None)
    command = ['bash', 'tools/run', 'tools/wine-headless', str(native)]
    started = datetime.now(timezone.utc).isoformat()
    sink = subprocess.check_output(['pactl', 'load-module', 'module-null-sink',
                                    'sink_name=eidolon_T11_compat', 'rate=44100', 'channels=2'], text=True).strip()
    try:
        with (data / 'runner.log').open('wb') as log:
            result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
    finally:
        subprocess.run(['pactl', 'unload-module', sink], check=True)
    quiet_prefix(prefix)
    events = [json.loads(line) for line in (data / 'backend.jsonl').read_text().splitlines()] if (data / 'backend.jsonl').exists() else []
    failure = next((e for e in events if e['event'] == 'failure'), None)
    sources = [e for e in events if e['event'] == 'shader_source']
    bundle = {p: sha(p) for p in original['bundle']}
    bundle.update({str(p): sha(p) for p in Path('tools/capture/proxy-b-compat').glob('*') if p.is_file()})
    manifest = dict(kind='proxy-B-D9-compatibility-diagnostic', run_id=args.run_id,
                    reference_eligible=False, finalized=False,
                    status='failed' if failure or result.returncode else 'partial',
                    transformation=args.mode, substitutions=sum(e['transformed'] for e in sources),
                    input=dict(original['input'], executed_copy=str(native)), dependency=bank_manifest, build=build_manifest, bundle=bundle,
                    source_provenance=sources, stage=str(stage),
                    prefix_baseline=dict(recipe='cp -a --reflink=auto stopped T2 prefix; restore identical full tree before each invocation',
                                         inventory=str(scratch / 'prefix-baseline.json'), inventory_sha256=sha(scratch / 'prefix-baseline.json'),
                                         fresh_tree_equal=True),
                    environment=dict(os=platform.platform(), wine=subprocess.check_output(['wine', '--version'], text=True).strip(),
                                     packages=subprocess.check_output(['pacman', '-Q', 'wine', 'gamescope', 'nvidia-utils', 'lib32-nvidia-utils'], text=True).splitlines(),
                                     gpu=subprocess.check_output(['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'], text=True).strip(),
                                     display=original['environment']['display'],
                                     settings={k: v for k, v in env.items() if k.startswith(('WINE', 'EIDOLON_B_')) or k in
                                               ('AGENT', 'PULSE_SINK', 'XDG_CACHE_HOME', '__GL_SHADER_DISK_CACHE_PATH', 'LC_ALL', 'TZ')}),
                    reproduce=['bash', 'tools/run', 'python', 'tools/capture/proxy-b-compat/probe.py', '--run-id', '<fresh-id>', '--mode', args.mode, '--frames', str(args.frames)],
                    command=command, started_utc=started, finished_utc=datetime.now(timezone.utc).isoformat(),
                    launcher_exit=result.returncode, first_failed_check=failure,
                    runner_terminal=[line for line in (data / 'runner.log').read_text(errors='replace').splitlines() if line.startswith(('WINE_EXIT=', 'TIMEOUT'))],
                    observations=[e for e in events if e['event'] not in ('lookup', 'clock', 'shader_source')
                                  and not (e['event'] == 'program_use' and e['program'] == 1 and not e['post_error'])],
                    evidence={str(p.relative_to(data_root)): sha(p) for p in sorted(data.iterdir()) if p.is_file()},
                    D2=original['D2'], resources=dict(prefix_processes_released=True, private_sink_unloaded=True),
                    gates='Diagnostic observations only; G1 ABI/canaries, G2-G4 and T10 eligibility require independent review.')
    destination.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(dict(manifest=str(destination), native_exit=result.returncode, failure=failure,
                         programs=sum(e['event'] == 'shader_program' for e in events),
                         failed_links=[e['program'] for e in events if e['event'] == 'shader_program' and not e['link_status']],
                         frames=sum(e['event'] == 'post_present' for e in events))))
    return 1 if failure or result.returncode else 0


if __name__ == '__main__':
    raise SystemExit(main())
