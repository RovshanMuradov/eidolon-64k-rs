#!/usr/bin/env python3
"""Install the system gm.dls into a Wine prefix; the size-optimized build reads it like the original."""
import sys
from pathlib import Path

import capture_original
import headless

if __name__ == '__main__':
    prefix = Path(sys.argv[1])
    headless.prepare_prefix(prefix)
    capture_original.install_bank(prefix, capture_original.sample_bank())
