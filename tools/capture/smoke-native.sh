#!/usr/bin/env bash
# Real-time compatibility smoke run; this does not produce a reference capture.
set -euo pipefail

if [[ -z "${EIDOLON_ROOT:-}" ]]; then
    printf 'Run from the worktree root: bash tools/run bash tools/capture/smoke-native.sh\n' >&2
    exit 64
fi

readonly archive='eidolon_-_poo-brain_-_revision2017_64k_-_rc4.zip'
readonly exe='Eidolon - Poo-Brain (native).exe'
readonly archive_sha256='11104969a59ef85d1f7ed416abfb01a377834504369902a735eb1a2fd1e40008'
readonly exe_sha256='376b476c358a969da7d5d45c091355520453086ee8cd22625fdbb4fa3a9fd6be'
readonly scratch='/tmp/opencode/eidolon/T2'
export WINEPREFIX="$scratch/prefix"
export WINEARCH=win64
export WINEDLLOVERRIDES='winemenubuilder.exe,mscoree,mshtml=d'
export LC_ALL=C
export TZ=UTC

for tool in wine wineboot wineserver unzip sha256sum timeout; do
    command -v "$tool" >/dev/null
done
if [[ "$(wine --version)" != 'wine-11.17' ]]; then
    printf 'Expected wine-11.17; review environment before changing the pin.\n' >&2
    exit 65
fi
printf '%s  %s\n' "$archive_sha256" "$archive" | sha256sum --check --status
mkdir -p "$scratch/input"
unzip -p "$archive" "$exe" > "$scratch/input/$exe"
printf '%s  %s\n' "$exe_sha256" "$scratch/input/$exe" | sha256sum --check --status

if [[ ! -e "$WINEPREFIX/system.reg" ]]; then
    WINEDEBUG=-all timeout --signal=TERM --kill-after=10s 120s wineboot --init
    timeout 120s wineserver --wait
fi

# Use Wine's X11 driver on the recorded Xwayland display. Native Wayland does
# not provide Wine's virtual-desktop semantics in the same way.
WINEDEBUG=-all wine reg add 'HKCU\Software\Wine\Drivers' /v Graphics /t REG_SZ /d x11 /f
WINEDEBUG=-all wine reg add 'HKCU\Software\Wine\Drivers' /v Audio /t REG_SZ /d pulse /f
WINEDEBUG=-all wine reg add 'HKCU\Software\Wine' /v Version /t REG_SZ /d win10 /f
WINEDEBUG=-all wine reg add 'HKCU\Software\Wine\Explorer' /v Desktop /t REG_SZ /d EidolonT2 /f
WINEDEBUG=-all wine reg add 'HKCU\Software\Wine\Explorer\Desktops' /v EidolonT2 /t REG_SZ /d 1920x1080 /f
timeout 120s wineserver --wait

export WINEDEBUG="${SMOKE_WINEDEBUG:--all,+timestamp,+pid,+tid,+seh,+wgl,+wave,+winmm,+process,+explorer}"
printf 'Smoke run: prefix=%s desktop=EidolonT2,1920x1080 timeout=%ss\n' "$WINEPREFIX" "${SMOKE_TIMEOUT_SECONDS:-900}" >&2
# 124/137 means failure to finish, never successful timeline termination.
exec timeout --signal=TERM --kill-after=10s "${SMOKE_TIMEOUT_SECONDS:-900}s" \
    wine "$scratch/input/$exe"
