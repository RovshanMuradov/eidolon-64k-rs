#!/usr/bin/env python3
"""Read-only process reconciliation and bounded log-tail monitoring for one job."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from full import record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_id')
    args = parser.parse_args()
    assert args.run_id and all(c.isalnum() or c in '-_' for c in args.run_id)
    root = Path(os.environ['EIDOLON_DATA']) / 'reference'
    job = root / 'jobs' / args.run_id
    state = json.loads((job / 'state.json').read_text())
    pid_record = json.loads((job / 'pid.json').read_text())
    assert state['run_id'] == args.run_id and state['pid'] == pid_record['pid']
    pid = state['pid']
    process = Path(f'/proc/{pid}')
    alive = False
    identity_matches = False
    if process.exists():
        try:
            # Fields after comm start at field3; comm can contain spaces.
            fields = (process / 'stat').read_text().rsplit(')', 1)[1].split()
            identity_matches = fields[19] == state['proc_start_ticks'] and int(fields[3]) == state['sid'] == pid
            alive = identity_matches and fields[0] not in ('Z', 'X')
        except FileNotFoundError:
            pass
    result = dict(run_id=args.run_id, checked_utc=datetime.now(timezone.utc).isoformat(),
                  pid=pid, sid=state['sid'], process_identity_matches=identity_matches, alive=alive,
                  phase=state['phase'], child_pid=state.get('child_pid'),
                  log=state['log'], state=str(job / 'state.json'), native_log=state['native_log'])
    backend = root / args.run_id / 'backend.jsonl'
    if backend.exists():
        try:
            with backend.open('rb') as stream:
                size = os.fstat(stream.fileno()).st_size
                start = max(0, size - 262144)
                stream.seek(start)
                lines = stream.read(size - start).split(b'\n')
            # Ignore only a cut first/last line; the live writer owns them.
            events = [json.loads(line) for line in lines[1 if start else 0:-1] if line]
            result.update(backend_bytes=size,
                          last_complete_sequence=max((e.get('seq', 0) for e in events), default=None),
                          last_present_in_tail=max((e['n'] for e in events if e['event'] == 'post_present'), default=None),
                          failures_in_tail=[e for e in events if e['event'] == 'failure'])
        except FileNotFoundError:
            result['backend_transition'] = 'closed log moved during observation'
    result['needs_attention'] = bool(result.get('failures_in_tail')) or state['phase'] == 'failed' or (
        not alive and state['phase'] != 'complete')
    if 'exit_code' in state:
        result['exit_code'] = state['exit_code']
    record(job / 'monitor.json', result)
    print(json.dumps(result))
    return int(result['needs_attention'])


if __name__ == '__main__':
    raise SystemExit(main())
