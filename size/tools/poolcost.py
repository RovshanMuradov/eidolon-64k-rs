#!/usr/bin/env python3
"""Optional native pool proxy: EIDOLON_POOL_PACKER=/path/to/pack poolcost.py DIR...

The executable reads stdin and emits packed bytes to stdout. It is NOT needed for
frozen reconstruction, validation or whole-EXE measurement. Search calls are capped
at 200 evaluations/process (including the baseline), with at most four workers.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

WORKERS = 4
_lock = threading.Lock()
_used = 0
_limit = 200
_seed = None
_pack = None


def start(output, seed=None):
    """One immutable experiment per output path; no shared pm2/rn2 checkpoints."""
    global _used, _limit, _seed, _pack
    if Path(output).exists():
        raise FileExistsError(f'experiment output already exists: {output}')
    _limit = int(os.environ.get('EIDOLON_SHADER_MAX_EVALS', '200'))
    if not 1 <= _limit <= 200:
        raise ValueError('EIDOLON_SHADER_MAX_EVALS must be in 1..200')
    _used, _seed = 0, seed
    _pack = packer()


def packer():
    requested = os.environ.get('EIDOLON_POOL_PACKER')
    path = shutil.which(requested) if requested else None
    if not path:
        raise ValueError('set EIDOLON_POOL_PACKER to an explicit native stdin/stdout pack tool')
    return path


def remaining():
    with _lock:
        return _limit - _used


def metadata():
    return dict(seed=_seed, evaluation_limit=_limit, evaluations=_used, workers=WORKERS,
                proxy='packed shader pool only; not whole EXE',
                packer_sha256=hashlib.sha256(Path(_pack).read_bytes()).hexdigest())


def cost(data):
    global _used
    tool = _pack or packer()
    with _lock:
        if _used >= _limit:
            raise ValueError('shader proxy evaluation budget exhausted')
        _used += 1
    return len(subprocess.run([tool], input=data, capture_output=True, check=True, timeout=60).stdout)


def pool(d):
    return b''.join(f.read_bytes() + b'\0' for f in sorted(Path(d).glob('[0-9][0-9].glsl')))


if __name__ == '__main__':
    for d in sys.argv[1:]:
        p = pool(d)
        print(d, len(p), cost(p))
