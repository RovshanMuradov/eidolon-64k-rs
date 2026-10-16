#!/usr/bin/env python3
"""Sequential bounded live rejection controls. Requires exclusive T11 GPU slot."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from probe import sha, quiet_prefix


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--build-from',type=Path,required=True)
    args = parser.parse_args()
    assert args.tag and all(c.isalnum() or c == '-' for c in args.tag)
    measured = json.loads(args.build_from.read_text())
    build = Path(measured['build']['build_directory'])
    identity = json.loads((build/'build.json').read_text())
    assert identity == measured['build']
    expected = {'fingerprint':'completion_fingerprint_rejected_before_patch',
                'wrong-thread':'wrong_hook_thread','unknown-route':'unknown_hook_route',
                'shader-count':'shader_source_array_extent','wrong-hdc':'GL_owning_context',
                'wrong-hglrc':'GL_owning_context','preexisting-error':'GL_initial_error',
                'readback-error':'GL_readback_state_or_error','restore-error':'GL_readback_state_or_error'}
    results = []
    for fault, reason in expected.items():
        run_id = f'proxy-b-d11-negative-{fault}-{args.tag}'
        command = ['python','tools/capture/proxy-b-compat/probe.py','--run-id',run_id,
                   '--mode','450-compatibility','--frames','3','--fault',fault,'--build-from',str(args.build_from)]
        result = subprocess.run(command,check=False)
        path = Path('artifacts/reference')/f'{run_id}.json'
        m = json.loads(path.read_text())
        assert result.returncode == 1 and m['launcher_exit'] == 125 and m['status'] == 'failed', fault
        assert m['first_failed_check']['reason'] == reason, (fault,m['first_failed_check'])
        assert not m['supervisor_timeout'] and any('WINE_EXIT=125 ' in x for x in m['runner_terminal'])
        results.append(dict(fault=fault,manifest=str(path),sha256=sha(path),observed=reason))
    scratch = Path('/tmp/opencode/eidolon/T11')
    prefix = scratch/'prefix'
    for fault in ('missing','wrong','self'):
        quiet_prefix(prefix)
        run_id = f'proxy-b-d11-backend-{fault}-{args.tag}'
        stage = scratch/run_id
        stage.mkdir(exist_ok=False)
        data = Path(os.environ['EIDOLON_DATA'])/'reference'/run_id
        data.mkdir(exist_ok=False)
        for name in ('canary.exe','opengl32.dll','winmm.dll'):
            shutil.copyfile(build/name,stage/name)
        env = {k:v for k,v in os.environ.items() if not k.startswith(('EIDOLON_B_','EIDOLON_A_'))}
        backend = {'missing':'Z:/eidolon-intentionally-missing.dll','wrong':'C:/windows/system32/kernel32.dll',
                   'self':'Z:'+str(stage/'opengl32.dll')}[fault]
        env.update(AGENT='T11',WINE_TIMEOUT='60',WINE_W='1920',WINE_H='1080',
                   WINEDLLOVERRIDES='opengl32,winmm=n,b;winemenubuilder.exe,mscoree,mshtml=d',
                   EIDOLON_B_BACKEND=backend,EIDOLON_B_LOG='Z:'+str(data/'backend.jsonl'),WINEDEBUG='-all')
        env.pop('DISPLAY',None); env.pop('WAYLAND_DISPLAY',None)
        command = ['bash','tools/run','tools/wine-headless',str(stage/'canary.exe')]
        with (data/'runner.log').open('wb') as log:
            result = subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=660)
        quiet_prefix(prefix)
        assert result.returncode == 125
        events = [json.loads(x) for x in (data/'backend.jsonl').read_text().splitlines()]
        probes = [e for e in events if e['event']=='backend_probe']
        expected_reason = {'missing':'backend_load_failed','wrong':'backend_symbol_missing_or_self','self':'backend_is_proxy'}[fault]
        assert probes[0]['result'] == expected_reason, probes
        results.append(dict(fault='backend-'+fault,command=command,backend_override=backend,
                            launcher_exit=result.returncode,observations=probes,
                            evidence={str(p.relative_to(Path(os.environ['EIDOLON_DATA']))):sha(p) for p in data.iterdir()},
                            supervisor_seconds=660,runner_seconds=60))
    path = Path('artifacts/reference')/f'proxy-b-d11-negative-controls-{args.tag}.json'
    path.write_text(json.dumps(dict(kind='bounded-live-negative-controls',reference_eligible=False,
                                   build=identity,results=results,resources_released=True),indent=2)+'\n')
    print(json.dumps(dict(status='DIAGNOSTIC_ONLY',rejections=len(results),manifest=str(path))))


if __name__ == '__main__':
    main()
