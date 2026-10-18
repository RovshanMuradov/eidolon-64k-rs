#!/usr/bin/env python3
"""Native kkrunchy-model cost of a fragment directory's pool (fast proxy): poolcost.py DIR..."""
from pathlib import Path
import subprocess
import sys

PACK = '/home/rovshan/Work/asm/Eidolon/.tools/optimization/graphics/kkrunchy-native/pack'


def cost(data):
    return len(subprocess.run([PACK], input=data, capture_output=True, check=True).stdout)


def pool(d):
    return b''.join(f.read_bytes() + b'\0' for f in sorted(Path(d).glob('[0-9][0-9].glsl')))


if __name__ == '__main__':
    for d in sys.argv[1:]:
        p = pool(d)
        print(d, len(p), cost(p))
