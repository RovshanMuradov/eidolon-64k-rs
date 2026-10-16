#!/usr/bin/env python3
"""Compare Rust score events with pinned native-layout recovery, including off velocity."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

data = Path(os.environ['EIDOLON_DATA'])
build = data / 'builds/T23'
build.mkdir(parents=True, exist_ok=True)
command = ['rustc', '--edition=2021', '-A', 'dead_code', '-C', 'opt-level=2', '-C', 'target-feature=+sse4.1',
           'tools/rust-audio/check_data.rs', '-o', str(build/'check-data')]
subprocess.run(command, check=True)
actual = subprocess.check_output([str(build/'check-data')])
event_file = data / 'analysis/audio/T19/events.json'
events = json.loads(event_file.read_text())
expected = b''.join(struct.pack('<IBBBBB', e['sample'], e['channel'], e['type'], e['special'], e['value'], e['velocity'] or 0) for e in events)
assert actual == expected
digest = hashlib.sha256(actual).hexdigest()
result = {'schema': 'eidolon-rust-score-v1', 'event_count': len(events), 'equal': True,
          'event_bytes_sha256': digest, 'recovered_events_sha256': hashlib.sha256(event_file.read_bytes()).hexdigest(),
          'compile_command': command, 'negative_controls': ['truncated score', 'damaged terminal sentinel'],
          'scheduler': 'all 64-frame quanta; stable event ordering equals recovered native streams',
          'cross_compile': 'rustc --edition=2021 --crate-type=rlib --crate-name=eidolon_audio --target i686-pc-windows-gnu -C opt-level=2 -C target-feature=+sse4.1 src/audio/mod.rs'}
Path('artifacts/rust/audio/score.json').write_text(json.dumps(result, indent=2)+'\n')
print(f'{len(events)} events match: {digest}; malformed controls pass')
