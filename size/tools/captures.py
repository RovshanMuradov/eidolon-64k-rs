#!/usr/bin/env python3
"""List T30 capture jobs and their phase (a new capture may start only when none is running)."""
import json
from pathlib import Path

area = Path('/home/rovshan/Work/asm/Eidolon/data/optimization/T30/verification')
for s in sorted(area.glob('*/state.json'), key=lambda p: p.stat().st_mtime):
    try:
        d = json.loads(s.read_text())
    except ValueError:
        d = {}
    print(s.parent.name, d.get('phase'), {k: v for k, v in d.items() if k in ('frames', 'done', 'progress', 'error')})
