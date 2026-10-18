#!/usr/bin/env python3
"""Generate all size audio tables, or verify checked-in bytes with --check."""
from pathlib import Path
import subprocess
import sys

if __name__ == '__main__':
    for name in ('encode_patch.py', 'encode_score.py', 'encode_formants.py'):
        subprocess.run([sys.executable, str(Path(__file__).with_name(name)), *sys.argv[1:]], check=True)
