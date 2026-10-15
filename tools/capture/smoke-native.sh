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
export AGENT=T2
export WINE_W=1920 WINE_H=1080
export WINE_TIMEOUT="${SMOKE_TIMEOUT_SECONDS:-600}"
export WINEDLLOVERRIDES='winemenubuilder.exe,mscoree,mshtml=d'
export LC_ALL=C
export TZ=UTC
unset DISPLAY WAYLAND_DISPLAY

for tool in wine wineboot wineserver gamescope unzip sha256sum timeout; do
    command -v "$tool" >/dev/null
done
if [[ ! "$WINE_TIMEOUT" =~ ^[1-9][0-9]{0,2}$ ]]; then
    printf 'SMOKE_TIMEOUT_SECONDS must be an integer between 1 and 999 seconds.\n' >&2
    exit 64
fi
if [[ "$(wine --version)" != 'wine-11.17' ]]; then
    printf 'Expected wine-11.17; review environment before changing the pin.\n' >&2
    exit 65
fi
printf '%s  %s\n' "$archive_sha256" "$archive" | sha256sum --check --status
mkdir -p "$scratch/input"
unzip -p "$archive" "$exe" > "$scratch/input/$exe"
printf '%s  %s\n' "$exe_sha256" "$scratch/input/$exe" | sha256sum --check --status

export WINEDEBUG="${SMOKE_WINEDEBUG:--all,+timestamp,+pid,+tid,+seh,+wgl,+wave,+winmm,+dsound,+process}"
printf 'Smoke run: prefix=%s display=gamescope-headless,1920x1080 timeout=%ss\n' "$scratch/prefix" "$WINE_TIMEOUT" >&2
# 124/137 means failure to finish, never successful timeline termination.
exec bash tools/run tools/wine-headless "$scratch/input/$exe"
