#!/usr/bin/env bash
# Full real-time native execution with diagnostic breakpoints; not a reference capture.
set -euo pipefail
: "${EIDOLON_DATA:?invoke through bash tools/run}"
scratch=/tmp/opencode/eidolon/T2
python tools/capture/prepare-native.py
i686-w64-mingw32-gcc -O2 -Wall -Wextra -Werror tools/capture/diagnose-playback.c -o "$scratch/diagnose-playback.exe" -lm
export AGENT=T2 WINE_W=1920 WINE_H=1080 WINE_TIMEOUT=600
export WINEDLLOVERRIDES='winemenubuilder.exe,mscoree,mshtml=d'
export WINEDEBUG="${PLAYBACK_WINEDEBUG:--all,+timestamp,+pid,+tid,+wgl,+wave}"
unset DISPLAY WAYLAND_DISPLAY
exec bash tools/run tools/wine-headless "$scratch/diagnose-playback.exe" "Z:$scratch/input/Eidolon - Poo-Brain (native).exe"
