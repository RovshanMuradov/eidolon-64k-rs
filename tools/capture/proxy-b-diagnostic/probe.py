#!/usr/bin/env python3
"""D7 exact error attribution; every outcome remains a failed diagnostic, not G1 PASS."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    assert args.run_id and all(c.isalnum() or c in '-_' for c in args.run_id)
    data_root = Path(os.environ['EIDOLON_DATA'])
    data = data_root / 'reference' / args.run_id
    destination = Path('artifacts/reference') / f'{args.run_id}.json'
    assert not destination.exists()
    assert sum(p.stat().st_size for p in data_root.rglob('*') if p.is_file()) + 200_000_000 < 30_000_000_000
    data.mkdir(parents=True, exist_ok=False)
    subprocess.run(['python', 'tools/capture/prepare-native.py'], check=True)
    build = Path(subprocess.check_output(['python', 'tools/capture/proxy-b-diagnostic/build.py'], text=True).strip())
    build_manifest = json.loads((build / 'build.json').read_text())
    original_path = Path('artifacts/reference/proxy-b-g1-20261016.json')
    original = json.loads(original_path.read_text())
    stage = Path('/tmp/opencode/eidolon/T2') / args.run_id
    stage.mkdir(exist_ok=False)
    for name in ('opengl32.dll', 'winmm.dll'):
        shutil.copyfile(build / name, stage / name)
        assert sha(stage / name) == build_manifest['outputs'][name]
    native = Path('/tmp/opencode/eidolon/T2/input') / original['input']['exe']
    assert sha(native) == original['input']['exe_sha256']
    shutil.copyfile(native, stage / native.name)
    assert sha(stage / native.name) == original['input']['exe_sha256']
    prefix = Path('/tmp/opencode/eidolon/T2/prefix')
    baseline = {str(p.relative_to(prefix)): sha(p) for p in [prefix / f for f in
                ('system.reg', 'user.reg', 'userdef.reg', 'drive_c/windows/system32/drivers/gm.dls',
                 'drive_c/windows/syswow64/drivers/gm.dls')]}
    env = {k: v for k, v in os.environ.items() if not k.startswith(('EIDOLON_A_', 'EIDOLON_B_'))}
    env.update(AGENT='T2', WINE_TIMEOUT='300', WINE_W='1920', WINE_H='1080',
               WINEDLLOVERRIDES='opengl32,winmm=n,b;winemenubuilder.exe,mscoree,mshtml=d',
               WINEDEBUG='-all,+loaddll', EIDOLON_B_LOG='Z:' + str(data / 'backend.jsonl'),
               EIDOLON_B_BOOTSTRAP='capture-probe', EIDOLON_B_OUTPUT='Z:' + str(data),
               EIDOLON_B_FRAMES='3', PULSE_SINK='eidolon_T2_diagnostic',
               XDG_CACHE_HOME='/tmp/opencode/eidolon/T2/cache',
               __GL_SHADER_DISK_CACHE_PATH='/tmp/opencode/eidolon/T2/cache/nvidia')
    env.pop('DISPLAY', None)
    env.pop('WAYLAND_DISPLAY', None)
    command = ['bash', 'tools/run', 'tools/wine-headless', str(stage / native.name)]
    started = datetime.now(timezone.utc).isoformat()
    sink = subprocess.check_output(['pactl', 'load-module', 'module-null-sink',
                                    'sink_name=eidolon_T2_diagnostic', 'rate=44100', 'channels=2'], text=True).strip()
    try:
        with (data / 'runner.log').open('wb') as log:
            result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
    finally:
        subprocess.run(['pactl', 'unload-module', sink], check=True)
    events = [json.loads(line) for line in (data / 'backend.jsonl').read_text().splitlines()] if (data / 'backend.jsonl').exists() else []
    failure = next((e for e in events if e['event'] == 'failure'), None)
    manifest = dict(kind='proxy-B-D7-GL-error-diagnosis', run_id=args.run_id,
                    reference_eligible=False, diagnostic_incomplete=True, status='G1_failed',
                    original_failure_manifest=str(original_path), original_failure_sha256=sha(original_path),
                    input=original['input'], dependency=original['dependency'], build=build_manifest,
                    bundle={p: sha(p) for p in original['bundle']}, stage=str(stage), prefix_baseline=baseline,
                    environment=dict(os=platform.platform(), wine=subprocess.check_output(['wine', '--version'], text=True).strip(),
                                     packages=subprocess.check_output(['pacman', '-Q', 'wine', 'gamescope', 'nvidia-utils', 'lib32-nvidia-utils'], text=True).splitlines(),
                                     gpu=subprocess.check_output(['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'], text=True).strip(),
                                     display=original['environment']['display'], lc_all='C', tz='UTC',
                                     settings={k: v for k, v in env.items() if k.startswith(('WINE', 'EIDOLON_B_')) or k in
                                               ('AGENT', 'PULSE_SINK', 'XDG_CACHE_HOME', '__GL_SHADER_DISK_CACHE_PATH')}),
                    reproduce=['bash', 'tools/run', 'python', 'tools/capture/proxy-b-diagnostic/probe.py', '--run-id', '<fresh-id>'],
                    command=command, started_utc=started, finished_utc=datetime.now(timezone.utc).isoformat(),
                    launcher_exit=result.returncode, first_failed_check=failure,
                    runner_terminal=[line for line in (data / 'runner.log').read_text(errors='replace').splitlines() if line.startswith(('WINE_EXIT=', 'TIMEOUT'))],
                    observations=[e for e in events if e['event'] not in ('lookup', 'clock')],
                    evidence={str(p.relative_to(data_root)): sha(p) for p in sorted(data.iterdir()) if p.is_file()},
                    D2=original['D2'], gates='All acceptance gates remain unpassed; diagnostic stops at first attributed GL error before pixels.')
    destination.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(dict(manifest=str(destination), native_exit=result.returncode, failure=failure,
                         gl=[e for e in events if e['event'].startswith('gl_')])))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
