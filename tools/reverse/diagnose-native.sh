#!/usr/bin/env bash
# Run with an assigned GPU slot: bash tools/run bash tools/reverse/diagnose-native.sh [NEW_OUTPUT_DIR]
set -euo pipefail
: "${EIDOLON_ROOT:?invoke through bash tools/run}"
: "${EIDOLON_DATA:?invoke through bash tools/run}"
mkdir -p "$EIDOLON_DATA/reverse" /tmp/opencode/eidolon/T1
if (( $# )); then
    output=$1
    mkdir "$output"
else
    output=$(mktemp -d "$EIDOLON_DATA/reverse/diagnostic.XXXXXX")
fi
export output
python - <<'PY'
import hashlib
import os
from pathlib import Path
from zipfile import ZipFile

root = Path(os.environ["EIDOLON_ROOT"])
name = "Eidolon - Poo-Brain (native).exe"
with ZipFile(root / "eidolon_-_poo-brain_-_revision2017_64k_-_rc4.zip") as archive:
    data = archive.read(name)
assert hashlib.sha256(data).hexdigest() == "376b476c358a969da7d5d45c091355520453086ee8cd22625fdbb4fa3a9fd6be"
copy = Path("/tmp/opencode/eidolon/T1") / name
if copy.exists():
    assert copy.read_bytes() == data, f"Refusing to overwrite differing input: {copy}"
else:
    copy.write_bytes(data)
PY
i686-w64-mingw32-gcc -O2 -Wall -Wextra -Werror tools/reverse/debug-native.c -o "$output/debug-native.exe"
printf 'Diagnostic output: %s\n' "$output"
set +e
AGENT=T1 WINE_TIMEOUT=160 WINEDEBUG=-all bash tools/run tools/wine-headless \
    "$output/debug-native.exe" \
    'Z:\tmp\opencode\eidolon\T1\Eidolon - Poo-Brain (native).exe' \
    "Z:$(realpath "$output")" > "$output/run.log" 2>&1
rc=$?
set -e
grep -E '^(CREATEFILE|READFILE|SAMPLE_NODE|NODE|EXIT|WINE_EXIT|BREAKPOINT_ERROR)' "$output/run.log" || true
exit "$rc"
