#!/usr/bin/env bash
# Invoke from this checkout: bash tools/run bash tools/analysis/graphics/decompile.sh
set -euo pipefail
: "${EIDOLON_DATA:?Run through tools/run}"
: "${GHIDRA_INSTALL_DIR:?Run through tools/run}"
OUT="$EIDOLON_DATA/analysis/graphics"
python tools/analysis/graphics/extract.py
python - <<'PY'
import hashlib, json, os
from pathlib import Path
data = Path(os.environ['EIDOLON_DATA'])
identity = json.loads(Path('reports/evidence/reverse/manifest.json').read_text())[
    'runtime_diagnostic']['files']['postfix']
raw = (data / identity['path']).read_bytes()
assert hashlib.sha256(raw).hexdigest() == identity['sha256']
copy = data / 'analysis/graphics/postfix-copy.bin'
if copy.exists():
    assert copy.read_bytes() == raw
else:
    copy.write_bytes(raw)
PY
if [[ -e "$OUT/T18-engine.gpr" ]]; then
    mode=(-process postfix-copy.bin -noanalysis)
else
    mode=(-import "$OUT/postfix-copy.bin" -loader BinaryLoader
          -loader-baseAddr 0x400000 -processor x86:LE:32:default -cspec windows)
fi
"$GHIDRA_INSTALL_DIR/support/analyzeHeadless" "$OUT" T18-engine "${mode[@]}" \
    -scriptPath "$PWD/tools/analysis/graphics" \
    -preScript ExtractEngine.java seed \
    -postScript ExtractEngine.java export "$OUT/engine.c" \
    -analysisTimeoutPerFile 300 -max-cpu 2 > "$OUT/ghidra.log" 2>&1
python - <<'PY'
import os
from pathlib import Path
text = (Path(os.environ['EIDOLON_DATA']) / 'analysis/graphics/engine.c').read_text()
assert text.count('// ENTRY ') == 8
assert '// FAILED' not in text and '// NO FUNCTION' not in text
print('STATIC_DECOMPILE_VERIFIED: 8 function entries; raw-loader ABI limitations apply')
PY
