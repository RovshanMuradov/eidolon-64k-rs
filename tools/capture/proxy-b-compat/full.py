#!/usr/bin/env python3
"""Launch exactly one detached full acquisition with durable lifecycle records."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from observations import sha


def record(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--storage', choices=['reference', 'hashes'], required=True)
    parser.add_argument('--build-from', type=Path, required=True)
    parser.add_argument('--reference', type=Path, help='required for hash-only repeats')
    parser.add_argument('--throughput-from', type=Path, default=Path('artifacts/reference/proxy-b-d12-volume-20261016-acquisition.json'))
    parser.add_argument('--execute-job', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    assert args.run_id and all(c.isalnum() or c in '-_' for c in args.run_id)
    assert (args.storage == 'hashes') == bool(args.reference)
    shared = Path(os.environ['EIDOLON_ROOT'])
    data = Path(os.environ['EIDOLON_DATA'])
    job = data / 'reference/jobs' / args.run_id
    if not args.execute_job:
        assert args.build_from.is_file() and args.throughput_from.is_file()
        assert not (data / 'reference' / args.run_id).exists()
        for name in ('setsid', 'nohup'):
            subprocess.run([name, '--version'], check=True, stdout=subprocess.DEVNULL)
        job.mkdir(parents=True, exist_ok=False)
        command = ['setsid', 'nohup', 'bash', 'tools/run', 'python', '-u', str(Path(__file__).resolve()),
                   *sys.argv[1:], '--execute-job']
        inputs = {str(p): sha(p) for p in (Path(__file__), args.build_from, args.throughput_from,
                  Path('tools/capture/proxy-b-compat/probe.py'), Path('tools/capture/proxy-b-compat/package_d12.py'),
                  Path('tools/capture/proxy-b-compat/observations.py'), Path('tools/capture/proxy-b-compat/timeline.py'),
                  Path('tools/wine-headless'))}
        if args.reference:
            inputs[str(args.reference)] = sha(args.reference)
        record(job / 'request.json', dict(command=command, cwd=str(Path.cwd()), inputs=inputs,
               created_utc=datetime.now(timezone.utc).isoformat(),
               git_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()))
        with (job / 'job.log').open('xb') as log:
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        record(job / 'pid.json', dict(pid=child.pid, log=str(job / 'job.log'), state=str(job / 'state.json')))
        print(json.dumps(dict(status='DETACHED', pid=child.pid, log=str(job / 'job.log'), state=str(job / 'state.json'))))
        return 0

    assert os.getsid(0) == os.getpid(), 'acquisition must be its own detached session'
    state = dict(pid=os.getpid(), sid=os.getsid(0), run_id=args.run_id, phase='preflight',
                 started_utc=datetime.now(timezone.utc).isoformat(),
                 proc_start_ticks=Path('/proc/self/stat').read_text().split()[21],
                 log=str(job / 'job.log'), native_log=str(data / 'reference' / args.run_id / 'runner.log'))
    def phase(name):
        state.update(phase=name, updated_utc=datetime.now(timezone.utc).isoformat())
        record(job / 'state.json', state)
    phase('preflight')
    try:
        with (shared / '.tools/capture/T16-gpu.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for path, checksum in json.loads((job / 'request.json').read_text())['inputs'].items():
                assert sha(path) == checksum, path
            from probe import quiet_prefix
            quiet_prefix(Path('/tmp/opencode/eidolon/T16/prefix'))
            used = sum(p.stat().st_size for p in data.rglob('*') if p.is_file())
            reserve = 1_000_000_000 + 27000 * 80000 + (2 * 510 * 8294400 if args.storage == 'reference' else 0)
            assert used + reserve < 30_000_000_000 and shutil.disk_usage(data).free > reserve, (used, reserve)
            for command in (['python', '--version'], ['i686-w64-mingw32-gcc', '--version'], ['wine', '--version'], ['pactl', '--version']):
                subprocess.run(command, check=True)
            acquisition = Path('artifacts/reference') / f'{args.run_id}-acquisition.json'
            reference = Path('artifacts/reference') / f'{args.run_id}-reference.json'
            assert not acquisition.exists() and not reference.exists()
            commands = [
                ('acquiring', ['python', 'tools/capture/proxy-b-compat/probe.py', '--run-id', args.run_id,
                 '--mode', '450-compatibility', '--reference-variant', 'D9-restored-native', '--full',
                 '--storage', args.storage, '--throughput-from', str(args.throughput_from), '--build-from', str(args.build_from)]),
                ('packaging', ['python', 'tools/capture/proxy-b-compat/package_d12.py', str(acquisition)]),
                ('validating', ['python', 'tools/verify/reference.py', 'validate', str(reference), '--data-root', str(data / 'reference' / args.run_id)])]
            if args.reference:
                first = json.loads(args.reference.read_text())['run_id']
                commands.append(('comparing', ['python', 'tools/verify/reference.py', 'compare', str(args.reference), str(reference),
                     '--reference-data', str(data / 'reference' / first), '--candidate-data', str(data / 'reference' / args.run_id)]))
            for name, command in commands:
                state['command'] = command
                phase(name)
                child = subprocess.Popen(command)
                state['child_pid'] = child.pid
                record(job / 'state.json', state)
                code = child.wait()
                if code:
                    raise subprocess.CalledProcessError(code, command)
            state.update(exit_code=0, reference=str(reference), reference_accepted=False)
            phase('complete')
        return 0
    except Exception as error:
        state.update(exit_code=getattr(error, 'returncode', 1), error=repr(error), failed_phase=state['phase'])
        phase('failed')
        raise


if __name__ == '__main__':
    raise SystemExit(main())
