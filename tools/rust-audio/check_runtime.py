#!/usr/bin/env python3
"""Verify render lifetime, thread isolation and caller FP controls on the CPU host."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
build=Path(os.environ['EIDOLON_DATA'])/'builds/T23/standalone'
build.mkdir(parents=True,exist_ok=True)
tmp=build/'tmp'; tmp.mkdir(exist_ok=True); os.environ['TMPDIR']=str(tmp)
command=['rustc','--edition=2021','-A','dead_code','-C','opt-level=2','-C','target-feature=+sse4.1',
         'tools/rust-audio/check_runtime.rs','-o',str(build/'check-runtime')]
subprocess.run(command,check=True)
result=subprocess.run([str(build/'check-runtime')],check=True,text=True,capture_output=True)
Path('artifacts/rust/audio/runtime-check.json').write_text(json.dumps({
    'schema':'eidolon-rust-runtime-check-v1','command':command,'stdout':result.stdout,
    'prefix_frames':262144,'synthesis_runs':4,'caller_mxcsr':['0x1f80','0x3f80','0x5f80','0x7f80'],
    'rust_files':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('src/audio').glob('*.rs')},
    'harness_sha256':hashlib.sha256(Path('tools/rust-audio/check_runtime.rs').read_bytes()).hexdigest()},indent=2)+'\n')
print(result.stdout,end='')
