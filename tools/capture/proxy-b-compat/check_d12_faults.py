#!/usr/bin/env python3
"""Reject unlabeled/unauthorized D12 metadata using disposable real-bundle copies."""
from copy import deepcopy
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--verifier-root',type=Path,default=Path.cwd())
    args=parser.parse_args()
    sys.path.insert(0,str(args.verifier_root.resolve()))
    from tools.verify import reference as ref
    m=ref.load_json(args.manifest.read_text())
    roots=dict(checkout=Path.cwd(),shared=Path(os.environ['EIDOLON_ROOT']),data=Path(os.environ['EIDOLON_DATA']))
    data=roots['data']/'reference'/m['run_id']
    ref.load_partial(args.manifest,data,roots)
    failures=[]
    with tempfile.TemporaryDirectory(prefix='d12-faults-',dir='/tmp/opencode/eidolon/T11') as scratch:
        scratch=Path(scratch)
        for name in (m['video']['index'],m['completion']['pcm']['evidence']):
            shutil.copyfile(args.manifest.parent/name,scratch/name)
        for fault in ('original-label','omitted-restoration','unknown-variant-field','extra-transformation','raw-shader-hash',
                      'effective-shader-hash','wrong-shim','missing-provenance','finalized-partial','claimed-natural-exit',
                      'merged-native-rows','full-schema-on-prefix'):
            changed=deepcopy(m)
            identity=changed['source']['restoration']
            if fault=='original-label': changed['source']['kind']='original'
            elif fault=='omitted-restoration': changed['source'].pop('restoration')
            elif fault=='unknown-variant-field': identity['unreviewed_edit']=True
            elif fault=='extra-transformation': identity['transformation']='450-explicit-output-0'
            elif fault=='raw-shader-hash': identity['raw_shader_sha256']='0'*64
            elif fault=='effective-shader-hash': identity['effective_shader_sha256']='0'*64
            elif fault=='wrong-shim': identity['shim_sha256']['opengl32.dll']='0'*64
            elif fault=='missing-provenance': changed.pop('provenance')
            elif fault=='finalized-partial': changed['completion']['finalized']=True
            elif fault=='claimed-natural-exit': changed['termination']['reason']='natural_exit'
            elif fault=='merged-native-rows':
                changed['scenes'][0]['last']=changed['scenes'][1]['last']; del changed['scenes'][1]
            elif fault=='full-schema-on-prefix': changed['schema']='eidolon-reference-draft-4'
            path=scratch/f'{fault}.json'; path.write_text(json.dumps(changed))
            try:
                ref.load_partial(path,data,roots)
            except ref.InvalidCapture as error:
                failures.append(dict(fault=fault,reason=str(error)))
            else:
                raise AssertionError(f'independent checker accepted {fault}')
        try:
            ref.load_run(args.manifest,data,roots)
        except ref.InvalidCapture:
            pass
        else:
            raise AssertionError('full validator accepted partial stage')
    print(json.dumps(dict(status='PARTIAL_ONLY',metadata_faults_rejected=len(failures),faults=failures,
                          full_validation_rejected=True,reference_accepted=False)))


if __name__=='__main__':
    main()
