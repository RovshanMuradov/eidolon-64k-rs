#!/usr/bin/env python3
"""Read-only B audit; preserve A failure logs and verify released resources."""
from datetime import datetime, timezone
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import zstandard

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda:file.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def main():
    root=Path(os.environ['EIDOLON_ROOT']);data=Path(os.environ['EIDOLON_DATA'])
    ids=['frida-a-g1-20261016','frida-a-g1-ancestor-20261016','frida-a-g1-runnable-20261016']
    checks=[];compressed={}
    for run_id in ids:
        path=Path('artifacts/reference')/(run_id+'.json');manifest=json.loads(path.read_text())
        assert manifest['status']=='G1_failed' and manifest['launcher_exit']==125
        for name,digest in manifest['evidence'].items():assert sha(data/name)==digest,name
        directory=root/'.tools/capture/A'/manifest['build']['build_id']
        for name,digest in manifest['build']['outputs'].items():assert sha(directory/name)==digest,name
        stage=Path(manifest['stage'])
        assert sorted(p.name for p in stage.iterdir())==[manifest['input']['exe']]
        assert sha(stage/manifest['input']['exe'])==manifest['input']['exe_sha256']
        assert manifest['environment']['settings']['WINEDLLOVERRIDES'].startswith('opengl32,winmm=b;')
        injection=json.loads((data/'reference'/run_id/'injection.json').read_text())
        assert injection['status']=='failed'
        log=(data/'reference'/run_id/'runner.log').read_text()
        assert 'A_RENDEZVOUS' in log and 'WINE_EXIT=125 GAMESCOPE_EXIT=139' in log
        assert not (data/'reference'/run_id/'events.jsonl').exists()
        assert 'proxy-demo' not in log and 'eidolon-a.dll' not in log
        for dll in ('opengl32','winmm'):
            loaded=[line for line in log.lower().splitlines() if f'\\{dll}.dll" at' in line]
            assert len(loaded)==1 and loaded[0].endswith(': builtin'),loaded
        evidence=data/'reference'/run_id
        for source in evidence.iterdir():
            if source.name not in ('runner.log','inject.log','injection.json','attach-access.json','rendezvous.json'):continue
            target=Path('reports/evidence/capture')/(run_id+'-'+source.name+'.zst')
            target.write_bytes(zstandard.ZstdCompressor(level=19).compress(source.read_bytes()))
            assert zstandard.ZstdDecompressor().decompress(target.read_bytes())==source.read_bytes()
            compressed[str(target)]={'sha256':sha(target),'original_sha256':sha(source),'bytes':source.stat().st_size}
        checks.append({'manifest':str(path),'sha256':sha(path),'failure':injection,
                       'stop':'launcher rejected missing injection acknowledgment before synth; native 125',
                       'frames':0,'helper_loaded':False,'B_proxies_inactive':True})
    latest=json.loads((Path('artifacts/reference')/(ids[-1]+'.json')).read_text())
    access=json.loads((data/'reference'/ids[-1]/'attach-access.json').read_text())
    assert access['ptrace_scope']=='1' and access['ancestor_read_bytes']=='558bec81ec24040000'
    assert 'TracerPid:\t0\n' in access['target_status'] and 'State:\tR (running)' in access['target_status']
    latest_log=(data/'reference'/ids[-1]/'runner.log').read_text()
    assert 'A_DEBUGGER_DETACHED' in latest_log
    directory=root/'.tools/capture/A'/latest['build']['build_id']
    snapshots={}
    for name,digest in latest['build']['sources'].items():
        assert sha(name)==digest,name
        target=directory/'source-snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(name,target);snapshots[str(target)]=sha(target)
        if name.endswith('.py'):ast.parse(Path(name).read_text(),filename=name)
    spec=importlib.util.spec_from_file_location('pe_exports','tools/capture/proxy-b/build.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    exports=module.exports(directory/'eidolon-a.dll')
    assert any('EidolonInitialize' in names for names in exports.values())
    subprocess.run(['node','--check','tools/capture/frida-a/bootstrap.js'],check=True)
    b_path=Path('artifacts/reference/proxy-b-g1-20261016.json');b=json.loads(b_path.read_text())
    for name,digest in b['evidence'].items():assert sha(data/name)==digest,name
    for name,digest in b['build']['sources'].items():assert sha(name)==digest,name
    for name,digest in b['build']['outputs'].items():assert sha(Path(b['build']['build_directory'])/name)==digest,name
    runtime=[]
    for process in Path('/proc').glob('[0-9]*'):
        try:
            env=(process/'environ').read_bytes().split(b'\0');comm=(process/'comm').read_text().strip()
            if b'WINEPREFIX=/tmp/opencode/eidolon/T2/prefix' in env or comm in ('gamescope','gamescopereaper'):
                runtime.append({'pid':int(process.name),'comm':comm})
        except (FileNotFoundError,ProcessLookupError,PermissionError):pass
    sinks=json.loads(subprocess.check_output(['pactl','--format=json','list','sinks','short'],text=True))
    assert not runtime and not any(s['name'].startswith('eidolon_T2') for s in sinks)
    report={'kind':'A-failure-audit','reference_eligible':False,'runs':checks,
            'final_failure_gate':'G1a actual Frida attach/injection; no script/helper execution',
            'prior_attempts':'Sibling injector denied proc mem; ancestor plus pending Wine debug event did not respond. Final runnable detached target is readable but Frida ptrace pokedata returns EIO.',
            'causal_limit':'The exact Frida error is preserved. Its internal failing address and WoW64 compatibility cause remain unknown.',
            'gates':{'G1':'failed at actual injection; ABI/clock/state and negative controls unrun',
                     'G2':'A unrun; immutable B full PCM remains for T10',
                     'G3':'unrun; native GL enum/call/context diagnostics implemented but unreachable',
                     'G4':'unrun; no controlled frame zero, boundaries or endpoint',
                     'G5':'no real pixel bundle','G6':'unrun'},
            'static_checks':{'helper_architecture':'PE32 i386','helper_exports':exports,
                             'python_ast':'pass','bootstrap_javascript_syntax':'pass'},
            'B_immutable_manifest_sha256':sha(b_path),'B_immutable_evidence':b['evidence'],
            'source_snapshots':snapshots,'compressed_evidence':compressed,
            'runtime_release':{'checked_utc':datetime.now(timezone.utc).isoformat(),
                               'T2_runtime_processes':runtime,'private_audio_sink_present':False},
            'next':'Coordinator evaluates both failed mechanisms; T10 reviews preserved B PCM.'}
    path=Path('artifacts/reference/frida-a-failure-review.json')
    path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'audit':'PASS for failure integrity only','review':str(path),
                      'G1':'failed','A_frames':0,'B_evidence':'unchanged','runtime_processes':0}))

if __name__=='__main__':main()
