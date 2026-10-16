#!/usr/bin/env python3
"""Acquire/package fresh D12 full runs sequentially under one pinned build."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


def run(argv):
    subprocess.run(argv, check=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--series',required=True)
    parser.add_argument('--runs',type=int,choices=[1,3],default=3)
    parser.add_argument('--throughput-from',type=Path,default=Path('artifacts/reference/proxy-b-d12-volume-20261016-acquisition.json'))
    args=parser.parse_args()
    assert args.series and all(c.isalnum() or c in '-_' for c in args.series)
    data=Path(os.environ['EIDOLON_DATA'])
    used=sum(p.stat().st_size for p in data.rglob('*') if p.is_file())
    reserve=args.runs*(1_000_000_000+27000*80000)+2*510*8294400
    assert used+reserve<30_000_000_000, (used,reserve)
    assert shutil.disk_usage(data).free>reserve
    for command in (['python','--version'],['i686-w64-mingw32-gcc','--version'],['wine','--version'],['pactl','--version']):
        run(command)
    acquisitions=[]; references=[]
    for i in range(args.runs):
        name=f'{args.series}-{i+1}'
        acquisition=Path('artifacts/reference')/f'{name}-acquisition.json'
        reference=Path('artifacts/reference')/f'{name}-reference.json'
        assert not acquisition.exists() and not reference.exists()
        command=['python','tools/capture/proxy-b-compat/probe.py','--run-id',name,'--mode','450-compatibility',
                 '--reference-variant','D9-restored-native','--full','--storage','reference' if i==0 else 'hashes',
                 '--throughput-from',str(args.throughput_from)]
        if acquisitions:
            command+=['--build-from',str(acquisitions[0])]
        run(command)
        acquisitions.append(acquisition)
        run(['python','tools/capture/proxy-b-compat/package_d12.py',str(acquisition)])
        run(['python','tools/verify/reference.py','validate',str(reference),'--data-root',str(data/'reference'/name)])
        references.append(reference)
        if i:
            run(['python','tools/verify/reference.py','compare',str(references[0]),str(reference),
                 '--reference-data',str(data/'reference'/f'{args.series}-1'),'--candidate-data',str(data/'reference'/name)])
    print(json.dumps(dict(status='FULL_ACQUISITIONS_CLOSED',references=[str(p) for p in references],reference_accepted=False)))


if __name__=='__main__':
    main()
