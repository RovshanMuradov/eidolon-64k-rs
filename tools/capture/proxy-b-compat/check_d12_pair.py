#!/usr/bin/env python3
"""Use the independent owner's D12 loader/comparator without relaxing partial status."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference',type=Path)
    parser.add_argument('repeat',type=Path)
    parser.add_argument('--verifier-root',type=Path,default=Path.cwd())
    args=parser.parse_args()
    sys.path.insert(0,str(args.verifier_root.resolve()))
    from tools.verify import reference as ref
    roots=dict(checkout=Path.cwd(),shared=Path(os.environ['EIDOLON_ROOT']),data=Path(os.environ['EIDOLON_DATA']))
    runs=[]
    for path in (args.reference,args.repeat):
        manifest=ref.load_json(path.read_text())
        run=ref.load_partial(path,roots['data']/'reference'/manifest['run_id'],roots)
        runs.append(run)
    reasons=ref.compare_runs(*runs)
    assert reasons==['partial diagnostics cannot pass full comparison'],reasons
    checker=Path(ref.__file__)
    print(json.dumps(dict(status='PARTIAL_ONLY',frames=len(runs[0].frames),all_comparable_fields_equal=True,
         full_comparison_rejection=reasons,checker=str(checker),checker_sha256=hashlib.sha256(checker.read_bytes()).hexdigest(),
         reference_accepted=False)))


if __name__=='__main__':
    main()
