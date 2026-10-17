#!/usr/bin/env python3
"""Export existing immutable EXEs through the pinned headless capture adapters.

Run through tools/run. Each original/rust command performs one acquisition.
Raw RGBA is checked against reference1 before lossy video encoding; PCM stays
float32 bit-exact. These viewing copies are not acceptance/performance results.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get('EIDOLON_DATA', ROOT / 'data'))
DEST = DATA / 'videos'
LOCK = ROOT / 'handoff/gpu-solo.lock'
OWNER = 'manual-video-export-20261017'
REFERENCE = ROOT / 'artifacts/reference/proxy-b-d13-detached-20261016-1-reference.json'
INDEX = ROOT / 'artifacts/reference/proxy-b-d13-detached-20261016-1-frames.jsonl'
NATIVE_BUILD = ROOT / '.tools/capture/B-compat/3fdbcd12eb6cd75c3c7a6932398b1522b0a065e71ae083b93d970e4fa5e023f2'
RUST_BUILD = DATA / 'verification/rust/live-d26-full01'
RUST_HASH = '48e356fed928d1712ffb35b660d2865d915d9c7ea90cd6e0df2bd891d6ba91aa'
NATIVE_HASH = '376b476c358a969da7d5d45c091355520453086ee8cd22625fdbb4fa3a9fd6be'
PCM_HASH = '9b1aa5f18aea89e27415ce82bd142b2e66bab3adaa7db4eab64f119fd33e631d'
FRAME_BYTES = 1920 * 1080 * 4
PCM_BYTES = 159716352
FRAMES = 27000


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def owned_lock():
    return LOCK.exists() and json.loads(LOCK.read_text()).get('owner') == OWNER


def release_lock():
    if owned_lock():
        LOCK.unlink()


def encoder_command(pcm, target, label, count):
    return ['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-nostdin',
            '-f', 'rawvideo', '-pixel_format', 'rgba', '-video_size', '1920x1080',
            '-framerate', '60', '-i', 'pipe:0', '-f', 'f32le', '-ar', '44100',
            '-ac', '2', '-i', str(pcm), '-map', '0:v:0', '-map', '1:a:0',
            '-vf', 'vflip,scale=in_range=full:out_range=tv:out_color_matrix=bt709,format=yuv420p',
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-maxrate', '12M',
            '-bufsize', '24M', '-threads', '4', '-color_range', 'tv', '-colorspace', 'bt709',
            '-color_primaries', 'bt709', '-color_trc', 'bt709', '-c:a', 'pcm_f32le',
            '-metadata', 'title=Eidolon - ' + label, '-metadata',
            'comment=Viewing copy: H.264 video is lossy; source frames verified against D9-restored-native; float32 PCM unchanged',
            '-n', str(target)]


class Backpressure(threading.Thread):
    """Bound the disk spool; pause only this job's actual PE process."""
    def __init__(self, output, prefix, executable):
        super().__init__(daemon=True)
        self.output, self.prefix, self.executable = output, prefix, executable
        self.done = threading.Event()
        self.pid = None
        self.paused = False
        self.error = None

    def belongs(self, proc):
        try:
            return ('WINEPREFIX=' + str(self.prefix)).encode() in (proc / 'environ').read_bytes().split(b'\0')
        except (OSError, ProcessLookupError):
            return False

    def target_signal(self, value):
        proc = Path('/proc') / str(self.pid)
        if self.pid and self.belongs(proc):
            os.kill(self.pid, value)
            return True
        return False

    def run(self):
        last_search = 0
        try:
            while not self.done.wait(0.1):
                if self.pid is None and time.monotonic() - last_search >= 1:
                    last_search = time.monotonic()
                    for proc in Path('/proc').glob('[0-9]*'):
                        if self.belongs(proc):
                            try:
                                if str(self.executable).encode() in (proc / 'maps').read_bytes():
                                    self.pid = int(proc.name)
                                    break
                            except OSError:
                                pass
                files = list(self.output.glob('frame-*'))
                if len(files) >= 8 and not self.paused:
                    if not self.pid and len(files) >= 32:
                        raise RuntimeError('Cannot identify PE process to bound raw spool')
                    self.paused = self.target_signal(signal.SIGSTOP)
                elif len(files) <= 2 and self.paused:
                    self.target_signal(signal.SIGCONT)
                    self.paused = False
                if shutil.disk_usage(DATA).free < 40_000_000_000:
                    raise RuntimeError('Free space below required 40GB reserve')
        except BaseException as error:
            self.error = repr(error)
        finally:
            if self.paused:
                self.target_signal(signal.SIGCONT)
                self.paused = False

    def close(self):
        self.done.set()
        self.join(timeout=5)


def validate_video(path, count, pcm_digest):
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-count_frames', '-show_streams', '-show_format',
        '-of', 'json', str(path)], text=True))
    video, = [s for s in probe['streams'] if s['codec_type'] == 'video']
    audio, = [s for s in probe['streams'] if s['codec_type'] == 'audio']
    assert (video['codec_name'], video['width'], video['height'], video['r_frame_rate'],
            int(video['nb_read_frames'])) == ('h264', 1920, 1080, '60/1', count), video
    assert (audio['codec_name'], audio['sample_rate'], audio['channels']) == ('pcm_f32le', '44100', 2), audio
    with subprocess.Popen(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path),
                           '-map', '0:a:0', '-c:a', 'pcm_f32le', '-f', 'f32le', 'pipe:1'],
                          stdout=subprocess.PIPE) as decoder:
        digest = hashlib.file_digest(decoder.stdout, 'sha256').hexdigest()
        assert decoder.wait() == 0 and digest == pcm_digest, 'Decoded PCM differs'
    return {'video': video, 'audio': audio, 'format': probe['format'], 'decoded_pcm_sha256': digest}


def prepare():
    assert not LOCK.exists(), 'GPU solo lock is already held'
    assert shutil.disk_usage(DATA).free >= 40_000_000_000
    for name in ('ffmpeg', 'ffprobe', 'wine', 'wineserver', 'gamescope', 'pactl'):
        assert shutil.which(name), name
    reference = json.loads(REFERENCE.read_text())
    assert sha(INDEX) == reference['video']['index_sha256']
    assert reference['audio']['sha256'] == PCM_HASH
    record = json.loads((NATIVE_BUILD / 'build.json').read_text())
    for name in ('opengl32.dll', 'winmm.dll'):
        assert sha(NATIVE_BUILD / name) == record['outputs'][name]
    previous = json.loads((RUST_BUILD / 'state.json').read_text())
    assert sha(RUST_BUILD / 'live.dll') == previous['helper_sha256']
    assert sha(RUST_BUILD / 'launch.exe') == previous['launcher_sha256']
    exe = DATA / f'builds/T22/candidates/{RUST_HASH}/eidolon-runtime.exe'
    assert sha(exe) == RUST_HASH
    assert not DEST.exists(), 'Do not overwrite a previous export directory'
    DEST.mkdir()
    (DEST / '.work').mkdir()
    config = {'owner': OWNER, 'destination': str(DEST), 'created': time.time(),
              'reference_sha256': sha(REFERENCE), 'frame_index_sha256': sha(INDEX),
              'script_sha256': sha(__file__), 'video': 'H.264 CRF18, 12Mbps VBV ceiling, 1080p60',
              'audio': 'bit-exact PCM f32le stereo 44100Hz',
              'jobs': ['original', 'rust'], 'reason': 'User requested convenient viewing copies; not acceptance runs'}
    write_json(DEST / 'request.json', config)
    with LOCK.open('x') as stream:
        json.dump(config, stream, indent=2)
    print(json.dumps(config), flush=True)


def wait_original(state):
    previous = DEST / '.work/original/state.json'
    state['phase'] = 'waiting-original'
    started = time.monotonic()
    while time.monotonic() - started < 24 * 3600:
        if previous.exists():
            value = json.loads(previous.read_text())
            if value['phase'] == 'complete':
                return
            if value['phase'] == 'failed':
                raise RuntimeError('Original export failed: ' + value.get('error', 'unknown'))
        if not owned_lock():
            raise RuntimeError('Video export GPU reservation is absent')
        time.sleep(5)
    raise RuntimeError('Timed out waiting for original export')


def export(label):
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    job = DEST / '.work' / label
    job.mkdir(exist_ok=False)
    state = {'label': label, 'pid': os.getpid(), 'sid': os.getsid(0), 'phase': 'preparing',
             'frames_written': 0, 'requested_frames': FRAMES, 'started': time.time()}
    state_path = job / 'state.json'
    write_json(state_path, state)
    process = encoder = limiter = None
    module = None
    env = None
    partial = DEST / (label + '.partial.mkv')
    try:
        if label == 'rust':
            state['phase'] = 'waiting-original'
            write_json(state_path, state)
            wait_original(state)
        assert owned_lock(), 'GPU reservation lost'
        assert shutil.disk_usage(DATA).free >= 40_000_000_000
        agent = 'VIDEO_' + label.upper()
        scratch = Path('/tmp/opencode/eidolon') / agent
        scratch.mkdir(exist_ok=False)
        prefix = scratch / 'prefix'
        subprocess.run(['cp', '-a', '--reflink=auto', str(ROOT / '.tools/capture/T11-prefix-baseline'), str(prefix)], check=True)
        output = job / 'output'
        output.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith(('EIDOLON_B_', 'EIDOLON_RUST_'))}
        env.update(AGENT=agent, WINEPREFIX=str(prefix), WINE_TIMEOUT='14400', WINEDEBUG='-all',
                   WINEARCH='win64', WINE_W='1920', WINE_H='1080', LC_ALL='C', TZ='UTC',
                   WINEDLLOVERRIDES='winemenubuilder.exe,mscoree,mshtml=d')
        env.pop('DISPLAY', None)
        env.pop('WAYLAND_DISPLAY', None)
        def win(path):
            return 'Z:' + str(path).replace('/', '\\')
        if label == 'original':
            stage = scratch / 'stage'
            stage.mkdir()
            name = 'Eidolon - Poo-Brain (native).exe'
            with zipfile.ZipFile(ROOT / 'eidolon_-_poo-brain_-_revision2017_64k_-_rc4.zip') as archive:
                (stage / name).write_bytes(archive.read(name))
            executable = stage / name
            assert sha(executable) == NATIVE_HASH
            for name in ('opengl32.dll', 'winmm.dll'):
                shutil.copyfile(NATIVE_BUILD / name, stage / name)
            (job / 'retention.txt').write_text(''.join(f'{n}\n' for n in range(FRAMES)))
            env.update(WINEDLLOVERRIDES='opengl32,winmm=n,b;winemenubuilder.exe,mscoree,mshtml=d',
                       EIDOLON_B_LOG=win(output / 'backend.jsonl'), EIDOLON_B_BOOTSTRAP='capture-probe',
                       EIDOLON_B_OUTPUT=win(output), EIDOLON_B_FRAMES='3',
                       EIDOLON_B_COMPAT='450-compatibility', EIDOLON_B_FULL='27000',
                       EIDOLON_B_RETENTION=win(job / 'retention.txt'), XDG_CACHE_HOME=str(stage / 'cache'),
                       __GL_SHADER_DISK_CACHE_PATH=str(stage / 'cache/nvidia'))
            arguments = [str(executable)]
            extension = 'rgba'
        else:
            executable = DATA / f'builds/T22/candidates/{RUST_HASH}/eidolon-runtime.exe'
            # Existing adapter's planned-stop mode retains every requested frame;
            # use 27000 without FULL (which intentionally allows only 510 anchors).
            # EXE is unchanged; this viewing run stops just after its last present.
            env['EIDOLON_RUST_FRAMES'] = str(FRAMES)
            arguments = [str(RUST_BUILD / 'launch.exe'), win(executable),
                         win(RUST_BUILD / 'live.dll'), win(output)]
            extension = 'raw'
        sink = 'eidolon_video_' + label
        module = subprocess.check_output(['pactl', 'load-module', 'module-null-sink',
                                          'sink_name=' + sink, 'rate=44100', 'channels=2'], text=True).strip()
        env['PULSE_SINK'] = sink
        command = ['bash', 'tools/run', 'tools/wine-headless', *arguments]
        expected = [json.loads(line)['sha256'] for line in INDEX.read_text().splitlines()]
        assert len(expected) == FRAMES
        state.update(phase='capturing-startup', command=command, executable=str(executable),
                     executable_sha256=sha(executable), scratch=str(scratch), prefix=str(prefix),
                     source_frame_index_sha256=sha(INDEX), adapter_policy='D9-restored-native full run' if label == 'original' else 'unchanged baseline EXE; controlled cursor; planned stop after present26999')
        with (job / 'runner.log').open('wb') as runner_log, (job / 'encoder.log').open('wb') as encoder_log, (job / 'captured-frames.jsonl').open('w') as ledger:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=runner_log,
                                       stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
            state['runner_pid'] = process.pid
            write_json(state_path, state)
            limiter = Backpressure(output, prefix, executable)
            limiter.start()
            deadline = time.monotonic() + 14400
            for n in range(FRAMES):
                path = output / f'frame-{n:05d}.{extension}'
                while not path.exists() or path.stat().st_size < FRAME_BYTES:
                    if limiter.error:
                        raise RuntimeError(limiter.error)
                    if process.poll() is not None:
                        raise RuntimeError(f'Capture exited {process.returncode} before frame{n}; see runner.log')
                    if time.monotonic() > deadline:
                        raise RuntimeError('Capture exceeded four-hour deadline')
                    time.sleep(0.05)
                assert path.stat().st_size == FRAME_BYTES
                pixels = path.read_bytes()
                digest = hashlib.sha256(pixels).hexdigest()
                assert digest == expected[n], f'Source frame{n} differs from accepted reference'
                if encoder is None:
                    pcm = output / 'pcm.f32le'
                    assert pcm.stat().st_size == PCM_BYTES and sha(pcm) == PCM_HASH, 'Source PCM differs'
                    codec = encoder_command(pcm, partial, label, FRAMES)
                    encoder = subprocess.Popen(codec, stdin=subprocess.PIPE, stdout=encoder_log, stderr=subprocess.STDOUT)
                    state.update(phase='encoding', encoder_pid=encoder.pid, encoder_command=codec, source_pcm_sha256=PCM_HASH)
                encoder.stdin.write(pixels)
                ledger.write(json.dumps({'n': n, 'sha256': digest}) + '\n')
                path.unlink()
                state['frames_written'] = n + 1
                if n % 60 == 0:
                    ledger.flush()
                    state.update(producer_pid=limiter.pid, updated=time.time())
                    write_json(state_path, state)
            encoder.stdin.close()
            assert encoder.wait(timeout=300) == 0, 'Encoder failed; see encoder.log'
            assert process.wait(timeout=180) == 0, 'Capture runner failed; see runner.log'
            limiter.close()
            assert not limiter.error, limiter.error
        state['phase'] = 'validating'
        write_json(state_path, state)
        validation = validate_video(partial, FRAMES, PCM_HASH)
        assert sha(executable) == state['executable_sha256'], 'EXE changed'
        final = DEST / (label + '.mkv')
        assert not final.exists()
        partial.rename(final)
        state.update(phase='complete', finished=time.time(), video=str(final), video_bytes=final.stat().st_size,
                     video_sha256=sha(final), validation=validation, source_frames_verified=FRAMES,
                     captured_frame_index_sha256=sha(job / 'captured-frames.jsonl'),
                     video_is_lossy=True, audio_is_bit_exact=True)
        write_json(state_path, state)
        if label == 'rust':
            (DEST / 'compare.m3u').write_text('#EXTM3U\n#EXTINF:-1,Eidolon - Original\noriginal.mkv\n#EXTINF:-1,Eidolon - Rust uncompressed build\nrust.mkv\n')
            subprocess.run(['notify-send', 'Eidolon: videos ready', str(DEST / 'compare.m3u')], check=False)
        print(json.dumps({'status': 'complete', 'video': str(final), 'bytes': final.stat().st_size}), flush=True)
        return 0
    except BaseException as error:
        state.update(phase='failed', error=repr(error), finished=time.time())
        write_json(state_path, state)
        print(json.dumps(state), flush=True)
        return 1
    finally:
        if limiter:
            limiter.close()
        if encoder and encoder.poll() is None:
            encoder.terminate()
            encoder.wait(timeout=20)
        if process and process.poll() is None:
            subprocess.run(['wineserver', '-k'], env=env, check=False, timeout=10)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
        if module:
            subprocess.run(['pactl', 'unload-module', module], check=False, timeout=10)
        if label == 'rust' or state['phase'] == 'failed':
            release_lock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'original', 'rust'])
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
    else:
        raise SystemExit(export(args.action))
