#!/usr/bin/env python3
"""Two sequential native exception-resumption faults; requires the sole GPU slot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-from',type=Path,required=True)
    parser.add_argument('--tag',required=True)
    args=parser.parse_args()
    assert all(c.isalnum() or c in '-_' for c in args.tag)
    summary_path=Path('artifacts/reference')/f'proxy-b-d12-exception-controls-{args.tag}.json'
    assert not summary_path.exists()
    tool=Path(__file__)
    snapshot=Path(os.environ['EIDOLON_ROOT'])/'.tools/capture/runner-snapshots'/sha(tool)/tool.name
    snapshot.parent.mkdir(parents=True,exist_ok=True)
    if snapshot.exists():
        assert snapshot.read_bytes()==tool.read_bytes()
    else:
        snapshot.write_bytes(tool.read_bytes())
    manifests=[]; results=[]
    for fault in ('exception-gpr','exception-fp'):
        run_id=f'proxy-b-d12-{fault}-{args.tag}'
        command=['python','tools/capture/proxy-b-compat/probe.py','--run-id',run_id,'--mode','450-compatibility',
                 '--build-from',str(args.build_from),'--fault',fault]
        result=subprocess.run(command,check=False)
        assert result.returncode==1,(fault,result.returncode)
        path=Path('artifacts/reference')/f'{run_id}.json'
        m=json.loads(path.read_text())
        assert m['launcher_exit']==125 and m['first_failed_check']['reason']=='physical_exception_resume_canary'
        assert not m['supervisor_timeout'] and m['resources']['prefix_processes_released'] and m['resources']['private_sink_unloaded']
        manifests.append(str(path))
        results.append(dict(fault=fault,manifest=str(path),sha256=sha(path),native_exit=125))
    subprocess.run(['python','tools/capture/proxy-b-compat/check_native.py','--controls',*manifests],check=True)
    summary=dict(kind='bounded-native-exception-controls',reference_eligible=False,
                 measured_build_manifest=dict(path=str(args.build_from),sha256=sha(args.build_from)),
                 host_tool=dict(path=str(snapshot),sha256=sha(snapshot)),results=results,
                 accepted_frames=0,resources_released=True,
                 scope='Physical resumption after live completion-CONTEXT EAX or MXCSR mutation; not arbitrary exception coverage.')
    summary_path.write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(dict(status='DIAGNOSTIC_ONLY',bounded_rejections=2,manifest=str(summary_path),reference_accepted=False)))


if __name__=='__main__':
    main()
