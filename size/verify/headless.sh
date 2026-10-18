#!/usr/bin/env bash
# Parameterized equivalent of the pinned T30 tools/wine-headless.
set -uo pipefail
: "${WINEPREFIX:?capture must supply its private prefix}"
: "${EIDOLON_SCRATCH:?capture must supply its local output directory}"
export WINEARCH=win64 LC_ALL=C TZ=UTC
export WINEDLLOVERRIDES="${WINEDLLOVERRIDES:-winemenubuilder.exe,mscoree,mshtml=d}"
unset WAYLAND_DISPLAY
killprefix() {
  wineserver -k 2>/dev/null
  sleep 1
  for d in /proc/[0-9]*; do
    [[ $(readlink "$d/exe" 2>/dev/null) == */wine* ]] || continue
    grep -qzx "WINEPREFIX=$WINEPREFIX" "$d/environ" 2>/dev/null && kill -9 "${d#/proc/}" 2>/dev/null
  done
}
export -f killprefix
trap killprefix EXIT INT TERM
[[ -e $WINEPREFIX/system.reg ]] || WINEDEBUG=-all timeout 120 wineboot --init
reg() { WINEDEBUG=-all wine reg add "$@" /f >/dev/null; }
reg 'HKCU\Software\Wine\Drivers' /v Graphics /t REG_SZ /d x11
reg 'HKCU\Software\Wine' /v Version /t REG_SZ /d win10
reg 'HKCU\Software\Wine\WineDbg' /v ShowCrashDialog /t REG_DWORD /d 0
reg 'HKLM\Software\Microsoft\Windows NT\CurrentVersion\AeDebug' /v Debugger /t REG_SZ /d ''
reg 'HKLM\Software\Wow6432Node\Microsoft\Windows NT\CurrentVersion\AeDebug' /v Debugger /t REG_SZ /d ''
timeout 60 wineserver --wait
export RC_FILE="$EIDOLON_SCRATCH/wine.rc" WINEDEBUG="${WINEDEBUG:--all}"
start=$(date +%s)
timeout --signal=TERM --kill-after=10s "${WINE_TIMEOUT:-3600}s" \
  gamescope --backend headless -W 1920 -H 1080 -w 1920 -h 1080 -r 60 -- \
  bash -c 'wine "$@"; echo $? > "$RC_FILE"; killprefix' _ "$@"
gs=$?
rc=$(cat "$RC_FILE" 2>/dev/null || echo none)
echo "WINE_EXIT=$rc GAMESCOPE_EXIT=$gs SECONDS=$(( $(date +%s) - start ))"
[[ $rc == none && ( $gs == 124 || $gs == 137 ) ]] && { echo "TIMEOUT after ${WINE_TIMEOUT:-3600}s" >&2; exit 124; }
[[ $rc == none ]] && exit 125
[[ $rc == 0 && $gs != 0 ]] && exit "$gs"
exit "$rc"
