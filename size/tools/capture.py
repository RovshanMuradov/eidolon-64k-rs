#!/usr/bin/env python3
"""Start a detached T30 kkrunchy capture: capture.py JOB CANDIDATE_DIR [--full]; review: capture.py --review JOB."""
import subprocess
import sys

VT = '/home/rovshan/Work/asm/Eidolon/data/optimization/T30/vt'
args = sys.argv[1:]
if args[0] == '--review':
    job = args[1]
    r = subprocess.run(['bash', 'tools/run', 'python', 'tools/verify/optimization/kkrunchy_review.py',
                        f'/home/rovshan/Work/asm/Eidolon/data/optimization/T30/verification/{job}', '--output', f'/home/rovshan/Work/asm/Eidolon/data/optimization/T30/verification/{job}-review.json'],
                       cwd=VT, capture_output=True, text=True)
    print(r.returncode, r.stdout[-3000:], r.stderr[-3000:])
    sys.exit(r.returncode)
job, bundle = args[0], args[1]
extra = ['--full'] if '--full' in args else []
log = open(f'{VT}/../verification/{job}.log', 'w')
subprocess.Popen(['bash', 'tools/run', 'python', 'tools/capture/optimization/kkrunchy.py', job, '--bundle', bundle,
                  *extra], cwd=VT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                 start_new_session=True)
print('started', job)
