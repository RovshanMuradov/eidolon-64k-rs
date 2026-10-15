"""Black-box runner checks using inert stand-ins; no Wine, compositor or GPU."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRATCH = Path("/tmp/opencode/eidolon/T7")
STAND_IN = r"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['MOCK_LOG'], 'a') as log:
    log.write(json.dumps({'tool': name, 'args': args,
                          'prefix': os.environ.get('WINEPREFIX'),
                          'wayland': os.environ.get('WAYLAND_DISPLAY')}) + '\n')
if name == 'wineboot':
    sys.exit('unexpected prefix initialization')
if name == 'wineserver' or (name == 'wine' and args[0] == 'reg'):
    sys.exit(0)
if name == 'wine':
    time.sleep(float(os.environ['MOCK_WINE_DELAY']))
    sys.exit(int(os.environ['MOCK_WINE_EXIT']))
if name == 'gamescope':
    if os.environ['MOCK_LAUNCH'] == '1':
        subprocess.run(args[args.index('--') + 1:], check=False)
    # Simulate the reported status, without generating a real crash/core.
    sys.exit(int(os.environ['MOCK_GAMESCOPE_EXIT']))
sys.exit('unexpected stand-in name')
"""


@pytest.fixture
def runtime():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="process-test-", dir=SCRATCH) as directory:
        base = Path(directory)
        prefix = base / "prefix"
        prefix.mkdir()
        (prefix / "system.reg").touch()
        bindir = base / "bin"
        bindir.mkdir()
        for name in ("wine", "wineboot", "wineserver", "gamescope"):
            command = bindir / name
            command.write_text(f"#!{sys.executable}\n" + STAND_IN)
            command.chmod(0o700)
        env = os.environ | {
            "AGENT": f"T7/{base.name}",
            "PATH": f"{bindir}:/usr/bin:/bin",
            "MOCK_LOG": str(base / "calls.jsonl"),
            "MOCK_WINE_EXIT": "0",
            "MOCK_GAMESCOPE_EXIT": "0",
            "MOCK_WINE_DELAY": "0",
            "MOCK_LAUNCH": "1",
            "WINE_TIMEOUT": "15",
            "WINE_W": "1920",
            "WINE_H": "1080",
            "WAYLAND_DISPLAY": "host-display-must-not-leak",
        }
        # Do not inherit shell startup hooks into this isolated process test.
        env.pop("BASH_ENV", None)
        yield base, env


def run_runner(runtime, **overrides):
    base, env = runtime
    result = subprocess.run(
        ["bash", str(ROOT / "tools/wine-headless"), "program with spaces.exe", "a 'quoted' argument"],
        cwd=ROOT,
        env=env | overrides,
        capture_output=True,
        text=True,
        timeout=25,
    )
    calls = [json.loads(line) for line in (base / "calls.jsonl").read_text().splitlines()]
    return result, calls


@pytest.mark.parametrize("native,compositor", [(0, 0), (5, 139), (37, 0)])
def test_native_exit_survives_compositor_teardown(runtime, native, compositor):
    result, calls = run_runner(
        runtime, MOCK_WINE_EXIT=str(native), MOCK_GAMESCOPE_EXIT=str(compositor)
    )
    assert result.returncode == native, result.stderr
    assert result.stdout.splitlines()[-1].startswith(
        f"WINE_EXIT={native} GAMESCOPE_EXIT={compositor} SECONDS="
    )
    native_call = next(c for c in calls if c["tool"] == "wine" and c["args"][0] != "reg")
    assert native_call["args"] == ["program with spaces.exe", "a 'quoted' argument"]
    compositor_call = next(c for c in calls if c["tool"] == "gamescope")
    assert compositor_call["args"][:13] == [
        "--backend", "headless", "-W", "1920", "-H", "1080",
        "-w", "1920", "-h", "1080", "-r", "60", "--",
    ]
    assert all(c["wayland"] is None for c in calls)
    assert all(c["prefix"] == str(runtime[0] / "prefix") for c in calls)
    assert sum(c["tool"] == "wineserver" and c["args"] == ["-k"] for c in calls) == 2


def test_compositor_failure_without_native_status(runtime):
    result, calls = run_runner(runtime, MOCK_LAUNCH="0", MOCK_GAMESCOPE_EXIT="139")
    assert result.returncode == 125, result.stderr
    assert "WINE_EXIT=none GAMESCOPE_EXIT=139" in result.stdout
    assert any(c["tool"] == "wineserver" and c["args"] == ["-k"] for c in calls)


def test_timeout_before_native_exit(runtime):
    result, calls = run_runner(runtime, MOCK_WINE_DELAY="30", WINE_TIMEOUT="1")
    assert result.returncode == 124, result.stderr
    assert "WINE_EXIT=none GAMESCOPE_EXIT=124" in result.stdout
    assert "TIMEOUT after 1s" in result.stderr
    assert any(c["tool"] == "wineserver" and c["args"] == ["-k"] for c in calls)


def test_cleanup_kills_only_wine_executables_in_own_prefix(runtime):
    base, env = runtime
    # Real Linux sleeper processes exercise /proc executable + environment matching.
    processes = []
    try:
        for name, prefix in [
            ("wine-orphan", base / "prefix"),
            ("wine-other-prefix", base / "unrelated-prefix"),
            ("compositor-sentinel", base / "prefix"),
        ]:
            executable = base / name
            shutil.copy2("/usr/bin/sleep", executable)
            processes.append(subprocess.Popen(
                [str(executable), "60"], env=env | {"WINEPREFIX": str(prefix)}
            ))
        result, _ = run_runner(runtime)
        assert result.returncode == 0, result.stderr
        assert processes[0].poll() == -9
        assert processes[1].poll() is None
        assert processes[2].poll() is None
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
