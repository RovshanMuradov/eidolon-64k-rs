#!/usr/bin/env python3
"""Compile only Rust, run CPU synthesis, compare bytes with immutable native PCM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

def sha(raw): return hashlib.sha256(raw).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frames',type=int,default=19964544)
    a=p.parse_args()
    assert 0<a.frames<=19964544 and a.frames%64==0
    data=Path(os.environ['EIDOLON_DATA']); build=data/'builds/T23/standalone'; build.mkdir(parents=True,exist_ok=True)
    temporary=build/'tmp'; temporary.mkdir(exist_ok=True); os.environ['TMPDIR']=str(temporary)
    command=['rustc','--edition=2021','-A','dead_code','-C','opt-level=2','-C','target-feature=+sse4.1',
             'tools/rust-audio/render.rs','-o',str(build/'render')]
    inputs={str(p):sha(p.read_bytes()) for p in Path('src/audio').glob('*.rs')}
    subprocess.run(command,check=True)
    output=build/f'pcm-{a.frames}.f32le'
    started=time.monotonic()
    run=subprocess.run([str(build/'render'),str(output),str(a.frames)],check=True,capture_output=True,text=True,timeout=360)
    elapsed=time.monotonic()-started
    manifest=Path('artifacts/reference/proxy-b-d13-detached-20261016-1-reference.json')
    ref=json.loads(manifest.read_text())
    reference=data/'reference/proxy-b-d13-detached-20261016-1/pcm.f32le'
    native=reference.read_bytes(); assert sha(native)==ref['audio']['sha256']
    actual=output.read_bytes(); expected=native[:a.frames*8]
    equal=actual==expected
    first=next((i for i,(x,y) in enumerate(zip(actual,expected)) if x!=y),None) if not equal else None
    result={'schema':'eidolon-rust-audio-standalone-v1','kind':'standalone-rust-native-comparison',
            'standalone_rust_synth':True,'frames':a.frames,'bytes':len(actual),'format':'stereo interleaved f32le 44100 Hz',
            'equal':equal,'first_mismatch_byte':first,'elapsed_seconds':elapsed,'output':str(output),
            'output_sha256':sha(actual),'reference_pcm_sha256':sha(native),'reference_manifest':str(manifest),
            'reference_manifest_sha256':sha(manifest.read_bytes()),'rust_files':inputs,
            'harness_sha256':sha(Path('tools/rust-audio/render.rs').read_bytes()),'compile_command':command,
            'rustc':subprocess.check_output(['rustc','--version'],text=True).strip(),
            'binary_sha256':sha((build/'render').read_bytes()),'stdout':run.stdout,'stderr':run.stderr,
            'fp':{'initialization_mxcsr':'0x1f80','synthesis_mxcsr':'0xffc0','caller_restored':True},
            'environment':{'resolution':None,'gpu':None,'driver':None,'wine':None},
            'scope':'Linux CPU executable, using production render entrypoint for full score; Windows runtime validation pending'}
    Path('artifacts/rust/audio/standalone.json').write_text(json.dumps(result,indent=2)+'\n')
    print(run.stdout,end=''); print(run.stderr,end='')
    print(json.dumps({k:result[k] for k in ['frames','equal','first_mismatch_byte','elapsed_seconds','output_sha256']}))
    if not equal: raise SystemExit(1)
if __name__=='__main__': main()
