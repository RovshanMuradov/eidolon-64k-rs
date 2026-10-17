#!/usr/bin/env python3
"""Run a Windows program under Wine in an invisible 1920x1080 gamescope display (Linux)."""
import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

WIDTH, HEIGHT = 1920, 1080
OVERRIDES = 'winemenubuilder.exe,mscoree,mshtml=d'
REGISTRY = [  # unattended runs: X11 driver, no crash dialog, no auto-debugger
    ('HKCU\\Software\\Wine\\Drivers', 'Graphics', 'REG_SZ', 'x11'),
    ('HKCU\\Software\\Wine', 'Version', 'REG_SZ', 'win10'),
    ('HKCU\\Software\\Wine\\WineDbg', 'ShowCrashDialog', 'REG_DWORD', '0'),
    ('HKLM\\Software\\Microsoft\\Windows NT\\CurrentVersion\\AeDebug', 'Debugger', 'REG_SZ', ''),
    ('HKLM\\Software\\Wow6432Node\\Microsoft\\Windows NT\\CurrentVersion\\AeDebug', 'Debugger', 'REG_SZ', ''),
]


def windows_path(path):
    return 'Z:' + str(Path(path).resolve()).replace('/', '\\')


def require_tools(*names):
    missing = [name for name in names if not shutil.which(name)]
    if missing:
        sys.exit(f'missing tools: {", ".join(missing)}')


def wine_env(prefix, extra=None):
    env = dict(os.environ, WINEPREFIX=str(Path(prefix).resolve()), WINEARCH='win64', WINEDEBUG='-all',
               WINEDLLOVERRIDES=OVERRIDES, LC_ALL='C', TZ='UTC')
    env.pop('WAYLAND_DISPLAY', None)
    env.update(extra or {})
    return env


def prepare_prefix(prefix):
    env = wine_env(prefix)
    if not (Path(prefix) / 'system.reg').exists():
        Path(prefix).mkdir(parents=True, exist_ok=True)
        subprocess.run(['wineboot', '--init'], env=env, check=True, timeout=300,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for key, name, kind, value in REGISTRY:
        subprocess.run(['wine', 'reg', 'add', key, '/v', name, '/t', kind, '/d', value, '/f'], env=env,
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['wineserver', '--wait'], env=env, check=False, timeout=120)


def run(exe, arguments, prefix, extra_env=None, timeout=3 * 3600, log=None):
    """Return the program's exit code; 124 on timeout."""
    require_tools('wine', 'wineserver', 'gamescope')
    prepare_prefix(prefix)
    env = wine_env(prefix, extra_env)
    env.pop('DISPLAY', None)
    with tempfile.TemporaryDirectory() as scratch:
        code_file = Path(scratch) / 'exit'
        env['EIDOLON_EXIT_FILE'] = str(code_file)
        command = ['gamescope', '--backend', 'headless', '-W', str(WIDTH), '-H', str(HEIGHT),
                   '-w', str(WIDTH), '-h', str(HEIGHT), '-r', '60', '--',
                   'bash', '-c', 'wine "$@"; echo $? > "$EIDOLON_EXIT_FILE"', '_', str(exe), *arguments]
        output = open(log, 'wb') if log else None
        process = subprocess.Popen(command, env=env, stdout=output, stderr=subprocess.STDOUT if output else None,
                                   start_new_session=True)
        try:
            process.wait(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        finally:
            subprocess.run(['wineserver', '-k'], env=env, check=False)
            if output:
                output.close()
        if timed_out:
            return 124
        # gamescope may exit nonzero after its child; the program's own exit code is authoritative.
        return int(code_file.read_text()) if code_file.exists() else 125


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=3 * 3600)
    parser.add_argument('exe', type=Path)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    return run(args.exe, args.arguments, args.prefix, timeout=args.timeout)


if __name__ == '__main__':
    sys.exit(main())
