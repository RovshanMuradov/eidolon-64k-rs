#!/usr/bin/env python3
"""Build and pack the size build with a different graphics blob: measure.py BLOB [GL_NAMES_RS] [--keep DIR].

Prints the kkrunchy line and the trimmed file size. Reuses the packer that `make size` built.
With --keep DIR, the unprepared PE and the shipped EXE are copied to DIR."""
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build  # noqa: E402

args = sys.argv[1:]
keep = None
if '--keep' in args:
    i = args.index('--keep')
    keep = Path(args[i + 1])
    del args[i:i + 2]
blob = Path(args[0]).resolve()
names = Path(args[1]).resolve() if len(args) > 1 else None
tree = build.stage()
shutil.copyfile(blob, tree / 'src/data/graphics.cg29')
if names:
    shutil.copyfile(names, tree / 'src/gl_names.rs')
pe = build.build_pe(tree)
import os  # noqa: E402
packer = build.WORK / 'packer/kkrunchy.exe'
source, out = build.WORK / 'input.exe', build.WORK / 'packed.exe'
source.write_bytes(build.prepare(pe))
out.unlink(missing_ok=True)
win = lambda p: 'Z:' + str(p).replace('/', '\\')
env = dict(os.environ, WINEPREFIX=str(build.WORK / 'wine-prefix'), WINEARCH='win64', WINEDEBUG='-all',
           WINEDLLOVERRIDES='winemenubuilder.exe,mscoree,mshtml=d')
log = build.run(['wine', packer, '--out', win(out), win(source)], build.WORK, env)
print('\n'.join(l for l in log.splitlines() if '=>' in l or 'packed' in l))
packed = build.trim(out.read_bytes())
print('file', len(packed))
if keep:
    keep.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(build.WORK / 'target/i686-pc-windows-gnu/sizecoded/eidolon-runtime.exe', keep / 'unprepared.exe')
    (keep / 'eidolon-runtime.exe').write_bytes(packed)
