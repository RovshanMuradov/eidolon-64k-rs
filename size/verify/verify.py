#!/usr/bin/env python3
"""Exact kkrunchy capture/review with explicit, read-only external oracle paths.

Adapted from the pinned T30 capture/kkrunchy.py and verify/kkrunchy_review.py.
The external Python parsers and C observer remain hash-pinned, not reimplemented.
No operation invokes the private tools/run or its hardcoded capture entrypoints.
"""
import argparse
import datetime
import fcntl
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REFERENCE_PIN = '36c1f7f330682bb4f818ad22cd0dab99359ffcdf2b4abc60cfb9381d98e37c64'
PHYSICS_STATE_PIN = 'f5a9a5d47cc649b05178dc47f7bc7579e44a4327806ae6138cd2e60a5d6afc63'
PCM_PIN = '9b1aa5f18aea89e27415ce82bd142b2e66bab3adaa7db4eab64f119fd33e631d'


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked(path, pin):
    path = Path(path)
    need(re.fullmatch('[0-9a-f]{64}', pin) and sha(path) == pin, f'identity mismatch: {path}')
    return path


def load(path):
    # Reject duplicate object keys, including in candidate/config manifests.
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, f'duplicate JSON key: {key}')
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs)


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2) + '\n')


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Oracle:
    def __init__(self, config):
        self.config = Path(config).resolve()
        cfg = load(config)
        keys = ('toolkit', 'reference_checkout', 'reference_data', 'reference_shared', 'prefix_template')
        need(set(cfg) == set(keys), 'config must name all five external paths')
        self.paths = {k: Path(cfg[k]).resolve(strict=True) for k in keys}
        self.toolkit = self.paths['toolkit']
        self.pins = load(HERE / 'toolkit-pins.json')
        for path, digest in self.pins.items():
            checked(self.toolkit / path, digest)
        # Imports are read-only: suppress __pycache__ even in an external checkout.
        os.environ.update(EIDOLON_ROOT=str(self.paths['reference_shared']),
                          EIDOLON_DATA=str(self.paths['reference_data']))
        sys.path[:0] = [str(self.toolkit / 'tools/verify/rust'),
                        str(self.toolkit / 'tools/verify/optimization'), str(self.toolkit)]
        self.c = importlib.import_module('conformance')
        self.m = importlib.import_module('monitor_full')
        self.v = importlib.import_module('native_vectors')
        self.pe = importlib.import_module('pe').PE
        self.physical = importlib.import_module('full').physical
        self.native = self.c.Native(self.paths['reference_checkout'], self.paths['reference_data'])
        need(sha(self.native.path) == REFERENCE_PIN, 'reference manifest pin')
        need(sha(self.native.pcm) == PCM_PIN, 'reference PCM pin')
        # Project into memory: never use monitor_full.native_times(), which can
        # write a cache into the external data root.
        raw = b''.join(struct.pack('<5I', *item) for item in self.native.times())
        need(hashlib.sha256(raw).hexdigest() == self.m.TIME_PIN, 'native time projection pin')
        self.times = list(struct.iter_unpack('<5I', raw))
        physics = self.paths['reference_data'] / 'verification/rust/native-d28-vectors01'
        state = load(checked(physics / 'state.json', PHYSICS_STATE_PIN))
        self.physics_build = load(checked(physics / 'build.json', state['build_sha256']))
        need(self.physics_build['native_manifest_sha256'] == REFERENCE_PIN, 'physics reference pin')
        need(state['phase'] == 'closed' and state['exit_code'] == 0, 'physics oracle closure')
        physics_pin = state['output']['physics.bin']['sha256']
        raw = checked(physics / 'output/physics.bin', physics_pin).read_bytes()
        self.physics = list(zip(self.physics_build['samples'],
                                self.v.physics_records(raw, self.physics_build['samples'])))
        need(len(self.physics) == 151, 'physics oracle sample coverage')
        self.provenance = dict(paths={k: str(v) for k, v in self.paths.items()},
                               reference_manifest_sha256=REFERENCE_PIN,
                               frame_index_sha256=self.native.manifest['video']['index_sha256'],
                               pcm_sha256=PCM_PIN, native_times_sha256=self.m.TIME_PIN,
                               physics_state_sha256=PHYSICS_STATE_PIN,
                               physics_build_sha256=state['build_sha256'], physics_sha256=physics_pin,
                               toolkit_pins=self.pins)

    def writable(self, path):
        path = Path(path).resolve()
        need(path.is_relative_to(ROOT / '.build'), 'capture output must be under this checkout/.build')
        for external in self.paths.values():
            need(not path.is_relative_to(external), f'output overlaps external input: {external}')
        return path


def bundle(args):
    directory = Path(args.output).resolve()
    need(directory.is_relative_to(ROOT / '.build'), 'bundle must be under this checkout/.build')
    directory.mkdir(parents=True, exist_ok=True)
    checked(args.candidate, args.sha256)
    files = {}
    for role, source, name in [('candidate', args.candidate, 'eidolon-runtime.exe'),
                               ('unprepared', args.unprepared, 'unprepared.exe'),
                               ('prepared', args.prepared, 'prepared.exe')]:
        source = source.resolve()
        target = directory / name
        if target.exists():
            need(sha(target) == sha(source), f'existing bundle differs: {target}')
        else:
            shutil.copyfile(source, target)
        files[role] = dict(path=name, bytes=target.stat().st_size, sha256=sha(target), source=str(source))
    manifest = dict(schema='eidolon-size-verification-input-1', method='kkrunchy_k7',
                    files=files, delivered_files=['eidolon-runtime.exe'],
                    delivered_bytes=files['candidate']['bytes'], production_accepted=False)
    path = directory / 'candidate.json'
    if path.exists():
        need(load(path) == manifest, 'existing manifest differs')
    else:
        write(path, manifest)
    return dict(manifest=str(path), manifest_sha256=sha(path), **manifest)


def inputs(path, oracle):
    path = Path(path).resolve()
    m = load(path)
    need(m['schema'] == 'eidolon-size-verification-input-1' and m['method'] == 'kkrunchy_k7', 'input schema/method')
    files = {}
    for role in ('candidate', 'unprepared', 'prepared'):
        item = m['files'][role]
        target = path.parent / item['path']
        need(target.resolve().parent == path.parent, 'non-local bundle file')
        files[role] = checked(target, item['sha256'])
        need(target.stat().st_size == item['bytes'], f'{role} byte count')
    need(m['delivered_files'] == ['eidolon-runtime.exe'] and
         m['files']['candidate']['path'] == 'eidolon-runtime.exe' and
         m['delivered_bytes'] == files['candidate'].stat().st_size, 'shipped inventory')
    # Verify the entire preparation transform, not just an assertion in a manifest.
    raw = bytearray(files['unprepared'].read_bytes())
    offset = struct.unpack_from('<I', raw, 60)[0]
    raw[offset+120:offset+128] = b'\0' * 8
    pe = oracle.pe(files['unprepared'])
    for name, _, _, size, file_offset in pe.sections:
        if name.rstrip(b'\0') in (b'.eh_fram', b'.edata'):
            raw[file_offset:file_offset+size] = b'\0' * size
    need(raw == files['prepared'].read_bytes(), 'prepared input differs from allowed export/unwind clearing')
    return m, files


def replace_once(text, old, new):
    need(text.count(old) == 1, f'observer patch anchor count: {old[:60]}')
    return text.replace(old, new)


def build_observer(job, files, oracle):
    for name in ('capture.c', 'live.c', 'hook.S', 'semantic.c', 'curves.c'):
        shutil.copyfile(oracle.toolkit / 'tools/capture/rust' / name, job / name)
    u, p = oracle.pe(files['unprepared']), oracle.pe(files['candidate'])
    marker, slot = u.exports()['eidolon_runtime_event'], u.imports()['waveOutGetPosition']
    need(u.read(marker, 7) == bytes.fromhex('5589e55683ec0c'), 'marker ABI signature')
    live = '#include <GL/gl.h>\n' + (job / 'live.c').read_text()
    live = replace_once(live, 'semantic_marker(kind,payload,stack);', '''if(kind==1){
 const char *vendor=(const char*)glGetString(GL_VENDOR),*renderer=(const char*)glGetString(GL_RENDERER),*version=(const char*)glGetString(GL_VERSION);
 if(!vendor||!renderer||!version)ExitProcess(125);
 save("gl-vendor.txt",vendor,strlen(vendor));save("gl-renderer.txt",renderer,strlen(renderer));save("gl-version.txt",version,strlen(version));
 } semantic_marker(kind,payload,stack);''')
    start, end = live.index('static void **find_iat('), live.index('\n__declspec')
    live = live[:start] + f'''static void **find_iat(BYTE *base,const char *wanted){{
 if(strcmp(wanted,"waveOutGetPosition"))ExitProcess(125);
 void **slot=(void**)(base+{slot});void *expected=(void*)GetProcAddress(GetModuleHandleA("winmm.dll"),wanted);
 if(!expected||*slot!=expected)ExitProcess(125);return slot;
 }}''' + live[end:]
    live = replace_once(live, 'BYTE *base=(void*)GetModuleHandleA(NULL);BYTE *marker=(void*)GetProcAddress((HMODULE)base,"eidolon_runtime_event");',
                        f'BYTE *base=(BYTE*)GetModuleHandleA(NULL)+{u.base-p.base};BYTE *marker=base+{marker};')
    anchor = 'if(!GetEnvironmentVariableA("EIDOLON_RUST_OUTPUT",output,sizeof(output)))ExitProcess(125);'
    live = replace_once(live, anchor, anchor + f'\n save("decoded-marker.bin",marker,16);save("decoded-oep.bin",base+{u.entry},16);')
    (job / 'live.c').write_text(live)
    shutil.copyfile(oracle.toolkit / 'tools/capture/optimization/launch_kkrunchy.c', job / 'launch.c')
    shutil.copyfile(__file__, job / 'verify.py')
    shutil.copyfile(HERE / 'headless.sh', job / 'headless.sh')
    commands = [['i686-w64-mingw32-gcc', '-O2', '-msse2', '-shared', '-Wl,--no-insert-timestamp',
                 *[str(job / x) for x in ('capture.c', 'live.c', 'semantic.c', 'hook.S')],
                 '-lopengl32', '-ladvapi32', '-o', str(job / 'live.dll')],
                ['i686-w64-mingw32-gcc', '-O2', '-msse2', '-Wl,--no-insert-timestamp',
                 str(job / 'launch.c'), '-o', str(job / 'launch.exe')]]
    for command in commands:
        subprocess.run(command, check=True)
    return marker, slot, commands


def mapped_identity(job, state):
    mappings = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if f"WINEPREFIX={state['wine_prefix']}".encode() not in (proc / 'environ').read_bytes().split(b'\0'):
                continue
            lines = (proc / 'maps').read_text().splitlines()
            selected = [s for s in lines if state['candidate'] in s or str(job / 'live.dll') in s]
            if any(state['candidate'] in s for s in selected) and any(str(job / 'live.dll') in s for s in selected):
                mappings.append(dict(pid=int(proc.name), lines=selected, process_exe=os.readlink(proc / 'exe')))
        except OSError:
            pass
    if not mappings:
        return False
    write(job / 'live-identity.json', dict(candidate=state['candidate'], sha256=sha(state['candidate']),
                                          bytes=Path(state['candidate']).stat().st_size, mappings=mappings,
                                          helper_sha256=sha(job / 'live.dll')))
    return True


def no_orphan_capture():
    """A killed supervisor loses its flock; its Wine session may still be alive."""
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            entries = (proc / 'environ').read_bytes().split(b'\0')
            scratch = next((entry.split(b'=', 1)[1] for entry in entries if entry.startswith(b'EIDOLON_SCRATCH=')), None)
            if scratch:
                path = Path(os.fsdecode(scratch)).resolve()
                need(not path.is_relative_to(ROOT / '.build'), f'active/orphaned capture process {proc.name}: {path}')
        except OSError:
            pass


def capture(args, oracle):
    job = oracle.writable(args.job)
    job.parent.mkdir(parents=True, exist_ok=True)
    # One lock for all jobs of this verifier checkout; refusal is immediate.
    with (ROOT / '.build/verify-capture.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        no_orphan_capture()
        need(shutil.disk_usage(job.parent).free >= (6_000_000_000 if args.full else 1_000_000_000), 'insufficient capture storage')
        manifest, files = inputs(args.manifest, oracle)
        job.mkdir()
        out = job / 'output'
        out.mkdir()
        marker, slot, commands = build_observer(job, files, oracle)
        keep = bytes(int('raw_zst' in item) for item in oracle.native.frames)
        need(len(keep) == 27000 and sum(keep) == 510, 'raw anchor retention coverage')
        (job / 'retention.bin').write_bytes(keep)
        prefix = job / 'prefix'
        subprocess.run(['cp', '-a', '--reflink=auto', str(oracle.paths['prefix_template']), str(prefix)], check=True)
        sink = 'eidolon_verify_' + hashlib.sha256(str(job).encode()).hexdigest()[:12]
        win = lambda path: 'Z:' + str(path).replace('/', '\\')
        # Reject inherited observer modes and keep graphics caches in the job.
        env = {k: v for k, v in os.environ.items() if not k.startswith(('EIDOLON_RUST_', 'EIDOLON_CURVE_', 'EIDOLON_SEED_'))}
        env.update(WINEPREFIX=str(prefix), EIDOLON_SCRATCH=str(job), WINE_TIMEOUT='14400' if args.full else '3600',
                   WINEDEBUG='-all', PULSE_SINK=sink, EIDOLON_RUST_FRAMES='27000' if args.full else '3',
                   WINEDLLOVERRIDES='winemenubuilder.exe,mscoree,mshtml=d', XDG_CACHE_HOME=str(job / 'cache'),
                   __GL_SHADER_DISK_CACHE_PATH=str(job / 'cache/nvidia'))
        if args.full:
            env.update(EIDOLON_RUST_FULL='1', EIDOLON_RUST_KEEP=win(job / 'retention.bin'))
        command = ['bash', str(job / 'headless.sh'), str(job / 'launch.exe'), win(files['candidate']),
                   win(files['unprepared']), win(job / 'live.dll'), win(out)]
        state = dict(schema='eidolon-size-capture-1', phase='running', job=str(job), pid=os.getpid(),
                     candidate=str(files['candidate']), candidate_sha256=sha(files['candidate']),
                     candidate_bytes=files['candidate'].stat().st_size, manifest=str(args.manifest.resolve()),
                     manifest_sha256=sha(args.manifest), original=str(files['unprepared']),
                     original_sha256=sha(files['unprepared']), marker_rva=marker, position_iat_rva=slot,
                     oracle=oracle.provenance, config_sha256=sha(oracle.config),
                     sources={f.name: sha(f) for f in job.iterdir() if f.suffix in ('.c', '.S', '.py', '.sh')},
                     helper_sha256=sha(job / 'live.dll'), launcher_sha256=sha(job / 'launch.exe'),
                     retention_sha256=sha(job / 'retention.bin'), build_commands=commands, command=command,
                     wine_prefix=str(prefix), sink=sink,
                     environment={k: v for k, v in env.items() if k.startswith(('EIDOLON_', 'WINE', 'PULSE_', '__GL_')) or k == 'XDG_CACHE_HOME'},
                     wine_version=subprocess.check_output(['wine', '--version'], text=True).strip(),
                     frames_requested=27000 if args.full else 3, full=args.full,
                     production_accepted=False, native_windows_tested=False, started_utc=now())
        module = subprocess.check_output(['pactl', 'load-module', 'module-null-sink', 'sink_name=' + sink], text=True).strip()
        start, rc, seen = time.monotonic(), 125, False
        write(job / 'state.json', state)
        child = None
        def interrupted(signum, _frame):
            raise InterruptedError(f'capture supervisor received signal {signum}')
        previous_handler = signal.signal(signal.SIGTERM, interrupted)
        try:
            with (job / 'runner.log').open('wb') as log:
                child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                state.update(runner_pid=child.pid, runner_sid=child.pid)
                write(job / 'state.json', state)
                while child.poll() is None:
                    if not seen:
                        seen = mapped_identity(job, state)
                    time.sleep(.2)
                rc = child.returncode
        except BaseException as exc:
            state['supervisor_error'] = str(exc)
            if child is not None and child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            raise
        finally:
            signal.signal(signal.SIGTERM, previous_handler)
            subprocess.run(['pactl', 'unload-module', module], check=False)
            state.update(phase='closed', exit_code=rc, elapsed_seconds=time.monotonic() - start,
                         candidate_after_sha256=sha(files['candidate']), runner_log_sha256=sha(job / 'runner.log'),
                         output={str(f.relative_to(job)): dict(bytes=f.stat().st_size, sha256=sha(f)) for f in out.iterdir() if f.is_file()},
                         live_identity_sha256=sha(job / 'live-identity.json') if seen else None, closed_utc=now())
            write(job / 'state.json', state)
        return dict(job=str(job), exit_code=rc, elapsed_seconds=state['elapsed_seconds'], candidate_sha256=state['candidate_sha256'])


def cleanup(state):
    remaining = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if os.getsid(int(proc.name)) == state['runner_sid'] or (
                    f"WINEPREFIX={state['wine_prefix']}".encode() in (proc / 'environ').read_bytes().split(b'\0')):
                remaining.append(int(proc.name))
        except OSError:
            pass
    sinks = subprocess.check_output(['pactl', 'list', 'short', 'sinks'], text=True)
    result = dict(remaining_pids=remaining, sink_present=state['sink'] in sinks,
                  runner_exists=Path(f"/proc/{state['runner_pid']}").exists(),
                  supervisor_exists=Path(f"/proc/{state['pid']}").exists())
    need(not remaining and not result['sink_present'] and not result['runner_exists'] and
         not result['supervisor_exists'], f'capture cleanup: {result}')
    return result


def process_exit(log, capture_exit):
    """Require exactly one clean child and wrapper closure; no substring passes."""
    child = re.findall(r'^CHILD_EXIT (\d+) stages=(\d{3})$', log, re.MULTILINE)
    wrapper = re.findall(r'^WINE_EXIT=(\d+|none) GAMESCOPE_EXIT=(\d+) SECONDS=\d+$', log, re.MULTILINE)
    return dict(capture=capture_exit, child_records=child, wrapper_records=wrapper,
                child_stages_complete=child == [('0', '111')],
                wine=wrapper[-1][0] if wrapper else None,
                gamescope=int(wrapper[-1][1]) if wrapper else None,
                clean=capture_exit == 0 and child == [('0', '111')] and wrapper == [('0', '0')])


def review(args, oracle):
    job = Path(args.job).resolve()
    state = load(job / 'state.json')
    result = dict(schema='eidolon-size-review-1', job=str(job), observed_utc=now(),
                  candidate_sha256=state['candidate_sha256'], delivered_bytes=state['candidate_bytes'],
                  capture_exit_code=state.get('exit_code'), full=state['full'], frames_requested=state['frames_requested'],
                  manifest_sha256=state['manifest_sha256'], state_sha256=sha(job / 'state.json'),
                  oracle=oracle.provenance, production_accepted=False, native_windows_tested=False,
                  verifier_sha256=sha(__file__), status='FAIL', failures=[],
                  remaining=['formal milestone acceptance', 'matched solo performance/resource checks',
                             'clean checkout rebuild of the final integrated candidate', 'native Windows execution'])
    out = job / 'output'
    try:
        need(state['phase'] == 'closed', 'capture has not closed')
        need(not state.get('supervisor_error'), 'capture supervisor was interrupted')
        need(type(state['full']) is bool and state['frames_requested'] == (27000 if state['full'] else 3), 'capture mode/coverage')
        need(state['oracle'] == oracle.provenance, 'oracle/toolkit paths or pins changed')
        checked(state['candidate'], state['candidate_sha256'])
        manifest, files = inputs(checked(state['manifest'], state['manifest_sha256']), oracle)
        need(files['candidate'] == Path(state['candidate']) and files['unprepared'] == Path(state['original']), 'capture/bundle identity')
        need(state['candidate_sha256'] == manifest['files']['candidate']['sha256'] and
             state['original_sha256'] == manifest['files']['unprepared']['sha256'] and
             state['candidate_bytes'] == files['candidate'].stat().st_size, 'capture/bundle pins or size differ')
        for name, pin in state['sources'].items():
            checked(job / name, pin)
        checked(job / 'live.dll', state['helper_sha256'])
        checked(job / 'launch.exe', state['launcher_sha256'])
        checked(job / 'retention.bin', state['retention_sha256'])
        need((job / 'retention.bin').read_bytes() == bytes(int('raw_zst' in item) for item in oracle.native.frames), 'retention mask differs from oracle')
        checked(job / 'runner.log', state['runner_log_sha256'])
        for name, item in state['output'].items():
            checked(job / name, item['sha256'])
            need((job / name).stat().st_size == item['bytes'], 'output extent changed')
        need(state['candidate_after_sha256'] == state['candidate_sha256'], 'candidate changed during capture')
        result['evidence_sha256'] = dict(capture_sources=state['sources'], helper=state['helper_sha256'],
                                         launcher=state['launcher_sha256'], retention=state['retention_sha256'],
                                         runner_log=state['runner_log_sha256'], live_identity=state['live_identity_sha256'],
                                         original_pe=state['original_sha256'], prepared_pe=manifest['files']['prepared']['sha256'],
                                         events=state['output'].get('output/events.bin', {}).get('sha256'),
                                         decoded_image=state['output'].get('output/decoded-image.bin', {}).get('sha256'))
        pe = oracle.pe(files['unprepared'])
        need(state['marker_rva'] == pe.exports()['eidolon_runtime_event'] and
             state['position_iat_rva'] == pe.imports()['waveOutGetPosition'], 'capture routing differs from pinned original PE')
        for stage in range(3):
            a = (out / f'stage{stage}-before.bin').read_bytes()
            b = (out / f'stage{stage}-after.bin').read_bytes()
            need(len(a) == len(b) == 576 and a[:36] == b[:36] and a[64:] == b[64:], f'decoder/OEP restoration stage {stage}')
        result['decoder_stages_restored'] = 3
        need((out / 'decoded-marker.bin').read_bytes() == pe.read(state['marker_rva'], 16) and
             (out / 'decoded-oep.bin').read_bytes() == pe.read(pe.entry, 16), 'decoded original marker/entry fingerprints')
        decoded, compared = (out / 'decoded-image.bin').read_bytes(), []
        prepared = oracle.pe(files['prepared'])
        for name, _, rva, size, _ in prepared.sections:
            name = name.rstrip(b'\0').decode()
            if name not in ('.text', '.data', '.rdata', '.eh_fram', '.edata'):
                continue
            expected, actual = bytearray(prepared.read(rva, size)), bytearray(decoded[rva:rva+size])
            marker = state['marker_rva'] - rva
            if 0 <= marker < size:
                need(actual[marker] == 0xe9 and actual[marker+5:marker+7] == b'\x90\x90', 'installed marker branch')
                actual[marker:marker+7] = expected[marker:marker+7]
            need(actual == expected, 'decoded section differs: ' + name)
            compared.append(name)
        need('.text' in compared and '.rdata' in compared, 'decoded section coverage')
        result['decoded_sections_exact'] = compared
        live = load(checked(job / 'live-identity.json', state['live_identity_sha256']))
        need(live['sha256'] == state['candidate_sha256'] and live['helper_sha256'] == state['helper_sha256'] and live['mappings'], 'mapped image identities')
        try:
            oracle.c.exact_files(oracle.native.pcm, out / 'pcm.f32le', oracle.c.PCM_BYTES)
        except ValueError as exc:
            match = re.search(r'byte mismatch at (\d+)', str(exc))
            offset = int(match[1]) if match else min(oracle.c.PCM_BYTES, (out / 'pcm.f32le').stat().st_size)
            result['pcm_mismatch'] = dict(first_byte_offset=offset, sample_frame=offset // 8,
                                          channel=('L', 'R')[(offset // 4) % 2],
                                          expected_bytes=oracle.c.PCM_BYTES, actual_bytes=(out / 'pcm.f32le').stat().st_size)
            raise
        result.update(pcm_bytes_exact=oracle.c.PCM_BYTES, pcm_sha256=sha(out / 'pcm.f32le'))
        records, pending = oracle.m.bounded_records((out / 'events.bin').read_bytes(), True)
        summary, hashes = oracle.m.prefix(records, oracle.native, oracle.times)
        result.update(observations=summary, pending_bytes=pending)
        for key in ('first_frame_mismatch', 'first_time_mismatch'):
            if summary[key] is not None:
                summary[key]['sample_cursor'] = summary[key]['n'] * 735
        if summary['frame_mismatches'] or summary['time_mismatches']:
            result['failures'].append('native frame/time mismatch')
        requested = state['frames_requested']
        need(summary['post_presents'] == summary['frame_hashes'] == requested, 'frame coverage')
        need(summary['queries'] == requested + int(state['full']), 'query coverage')
        anchors, raw_failures = 0, []
        for n in range(requested):
            words = struct.unpack('<18i', (out / f'gl-{n:05d}.bin').read_bytes())
            need(words[:9] == words[9:], f'GL restoration frame {n}')
            record = oracle.native.frames[n]
            raw = out / f'frame-{n:05d}.raw'
            if not state['full'] or 'raw_zst' in record:
                need(raw.stat().st_size == 8294400 and sha(raw) == hashes[n], f'captured raw/ledger identity frame {n}')
                if 'raw_zst' in record:
                    try:
                        oracle.m.exact_retained(oracle.native.directory / record['raw_zst'], raw, record['sha256'])
                        anchors += 1
                    except ValueError as exc:
                        raw_failures.append(dict(n=n, error=str(exc)))
        result.update(raw_anchors_exact=anchors, raw_anchor_failures=raw_failures, gl_restoration_frames=requested)
        if raw_failures:
            result['failures'].append('retained native raw byte mismatch')
        physics_differences, count = [], 0
        for n, expected in oracle.physics:
            if n >= requested:
                continue
            actual = records[3+5*n][1][28:]
            count += 1
            if actual != expected:
                words = [i for i, (a, b) in enumerate(zip(struct.unpack('<64I', actual), struct.unpack('<64I', expected))) if a != b]
                physics_differences.append(dict(n=n, sample_cursor=n*735, differing_u32_indices=words))
        result.update(physics_samples=count, physics_differences=physics_differences)
        if physics_differences:
            result['failures'].append('native sampled physics mismatch')
        for label, first, second, parts in (
                ('marker FP', 'marker-before-fx.bin', 'marker-restored-fx.bin', [(0, 512)]),
                ('marker GPR', 'marker-before-gpr.bin', 'marker-restored-gpr.bin', [(0, 36)]),
                ('position FP', 'position-before-fx.bin', 'position-after-fx.bin', [(0, 512)]),
                ('position GPR', 'position-before-gpr.bin', 'position-after-gpr.bin', [(0, 28), (32, 36)])):
            oracle.physical(out, label, first, second, parts)
        result['hook_physical_restoration'] = True
        log = (job / 'runner.log').read_text(errors='replace')
        result['process_exit'] = process_exit(log, state['exit_code'])
        result['gl'] = {name: (out / f'gl-{name}.txt').read_text() for name in ('vendor', 'renderer', 'version')}
        result['timing_observations'] = dict(runner_seconds=state['elapsed_seconds'],
                                            markers={k: int(v) for k, v in re.findall(r'RUNTIME_TIMING kind=(\d+) elapsed_ms=(\d+)', log)},
                                            scope='instrumented capture; concurrent host work; not a solo benchmark')
        errors = [line for line in log.splitlines() if re.search(r'HOOK_(?:FP|GPR)_MISMATCH|LAUNCH_FAILURE|EIDOLON_RUNTIME error:|CAPTURE_GL_|CAPTURE_EVENT.*rc=[1-9]|Unhandled exception|TIMEOUT after|waveOut cleanup failed:|waveOutClose failed:', line)]
        need(not errors, f'runtime errors: {errors}')
        if state['full']:
            need(summary['endpoint'] and summary['terminal_stability'] and 'PLANNED_SHORT_STOP' not in log, 'natural full endpoint')
            need(count == 151 and anchors + len(raw_failures) == 510, 'full oracle coverage')
        else:
            need('PLANNED_SHORT_STOP frames=3' in log and not summary['endpoint'], 'bounded smoke endpoint')
        result['media_bytes_and_sampled_state_exact'] = not result['failures']
        need(result['process_exit']['clean'], 'process exit/decoder closure')
        result['cleanup'] = cleanup(state)
        result['status'] = ('FULL_MEDIA_EXACT_PARTIAL' if state['full'] else 'SHORT_EXACT_PARTIAL') if not result['failures'] else 'MEDIA_MISMATCH'
    except (ValueError, OSError, KeyError, TypeError, struct.error, oracle.c.zstandard.ZstdError) as exc:
        result['failures'].append(str(exc))
    if state['phase'] == 'closed' and 'cleanup' not in result:
        try:
            result['cleanup'] = cleanup(state)
        except (ValueError, OSError, KeyError) as exc:
            result['failures'].append(str(exc))
            result['status'] = 'FAIL'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    p = sub.add_parser('bundle', help='preserve and hash exploratory PE inputs')
    for name in ('candidate', 'unprepared', 'prepared', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--sha256', required=True)
    for operation in ('oracle', 'capture', 'review'):
        p = sub.add_parser(operation)
        p.add_argument('--config', type=Path, required=True)
        if operation != 'oracle':
            p.add_argument('--job', type=Path, required=True)
        if operation == 'capture':
            p.add_argument('--manifest', type=Path, required=True)
            p.add_argument('--full', action='store_true')
        else:
            p.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.operation == 'bundle':
        result = bundle(args)
    else:
        oracle = Oracle(args.config)
        result = oracle.provenance if args.operation == 'oracle' else (capture(args, oracle) if args.operation == 'capture' else review(args, oracle))
    if getattr(args, 'output', None) and args.operation != 'bundle':
        write(args.output, result)
    print(json.dumps(result, indent=2))
    return int(result.get('status') in ('FAIL', 'MEDIA_MISMATCH') or result.get('exit_code', 0) != 0)


if __name__ == '__main__':
    raise SystemExit(main())
