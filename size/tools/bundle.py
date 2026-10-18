#!/usr/bin/env python3
"""Create T30 capture inputs/candidate dirs from a measure.py --keep directory: bundle.py KEEP TAG NOTE."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

T30 = Path('/home/rovshan/Work/asm/Eidolon/data/optimization/T30')
keep, tag, note = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
pe = keep / 'unprepared.exe'
exe = keep / 'eidolon-runtime.exe'
pe_sha, exe_sha = sha(pe), sha(exe)
inputs = T30 / 'inputs' / f'{pe_sha[:16]}-{tag}'
cand = T30 / 'candidates' / f'{exe_sha[:16]}-{tag}'
inputs.mkdir(parents=True)
cand.mkdir(parents=True)
shutil.copyfile(pe, inputs / 'eidolon-runtime.exe')
build = {'mode': tag, 'directory': str(inputs), 'pe': {'sha256': pe_sha, 'bytes': pe.stat().st_size},
         'source': 'eidolon-public research/graphics', 'note': note}
(inputs / 'build.json').write_text(json.dumps(build, indent=2) + '\n')
shutil.copyfile(exe, cand / 'eidolon-runtime.exe')
manifest = {
    'method': 'kkrunchy_k7',
    'build_manifest': str(inputs / 'build.json'),
    'build_manifest_sha256': sha(inputs / 'build.json'),
    'preparation': 'zero export directory; observer code remains at original RVA; zero unused .eh_fram/.edata; '
                   'trailing zero padding trimmed',
    'original_pe': {'sha256': pe_sha, 'bytes': pe.stat().st_size},
    'shipped_pe': {'sha256': exe_sha, 'bytes': exe.stat().st_size},
    'delivered_bytes': exe.stat().st_size,
    'delivered_files': ['eidolon-runtime.exe'],
    'excluded_system_file': 'gm.dls',
    'production_accepted': False,
    'manifest_file': 'candidate-v2.json',
}
(cand / 'candidate-v2.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(cand)
