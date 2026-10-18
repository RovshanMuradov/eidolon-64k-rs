# Exact packed-image verification

`verify.py` observes the **delivered kkrunchy executable**, including both
depacker stages and the original entry point. It reuses the hash-pinned native
oracle parsers and C observer through explicit external paths. The reference
archive is required; it is not distributed in this repository.

This is a Linux/Wine/Gamescope verification harness. A successful full result is
`FULL_MEDIA_EXACT_PARTIAL`, with `production_accepted: false`. It does not certify
native Windows behavior, clean-build reproducibility, or performance.

## Requirements

- Python 3.11+ with `zstandard`.
- Wine, Gamescope, PulseAudio-compatible `pactl`, and `i686-w64-mingw32-gcc`.
- The pinned T30 verification toolkit (`toolkit-pins.json`).
- Native reference `proxy-b-d13-detached-20261016-1`, its artifact manifests, and
  the `native-d28-vectors01` physics oracle.
- A reusable Wine prefix containing the standard `gm.dls` bank.
- About 6 GB free on the checkout filesystem for one full acquisition.

Create `.build/verify/reference-paths.json` with **absolute paths**:

```json
{
  "toolkit": "/path/to/T30/vt",
  "reference_checkout": "/path/to/T30/vt",
  "reference_data": "/path/to/reference-data",
  "reference_shared": "/path/to/reference-shared-root",
  "prefix_template": "/path/to/read-only-prefix-template"
}
```

`reference_checkout` contains `artifacts/reference/`;
`reference_data` contains `reference/` and `verification/rust/`.
`reference_shared` resolves the reference manifest's `shared` bindings. These
inputs are opened read-only. The external `tools/run`, capture entrypoints, and
private time-vector cache writer are never invoked. Bytecode writes are disabled.
Every acquisition gets its own prefix, audio sink, and graphics-cache directory.

## Capture and review

```sh
python3 size/verify/verify.py oracle \
  --config .build/verify/reference-paths.json

python3 size/verify/verify.py bundle \
  --candidate /path/to/trimmed.exe --sha256 FULL_64_CHARACTER_SHA256 \
  --unprepared /path/to/unprepared.exe --prepared /path/to/input.exe \
  --output .build/verify/candidate

python3 size/verify/verify.py capture \
  --config .build/verify/reference-paths.json \
  --manifest .build/verify/candidate/candidate.json \
  --job .build/verify/smoke

python3 size/verify/verify.py review \
  --config .build/verify/reference-paths.json \
  --job .build/verify/smoke --output .build/verify/smoke-review.json
```

After the three-frame/full-PCM smoke passes, capture a **new job** with `--full`,
then review that job. Run long acquisitions without an outer timeout shorter
than the capture's own timeout (one hour for smoke, four hours for full).
Synthesis alone can take over 15 minutes. Jobs are never overwritten. A local
file lock refuses concurrent captures from this checkout; coordinate exclusive
GPU access across other checkouts too. Do not use timings collected alongside
other CPU/GPU workloads as solo performance benchmarks.

## Checks retained from the reference verifier

- Candidate, manifest, prepared/unprepared PE, observer source/binaries, output
  files, reference provenance, and live mapped-image identities are hashed.
- The complete preparation transform is independently checked: clearing the
  export directory and unused `.eh_fram`/`.edata` bytes only.
- Three physical depacker/OEP GPR/FP restoration witnesses, original entry and
  marker fingerprints, and decoded `.text`/`.rdata`/`.eh_fram` bytes are checked.
  The adapter additionally checks `.data` and `.edata` when present. Only the
  verified seven-byte marker hook is masked. Import and relocation sections
  are loader-transformed and are not claimed as byte-identical.
- All 27,000 final RGBA hashes (including alpha), observed clock/scene words,
  ordered query/pre/post records, and GL layout/restoration witnesses must pass.
- All 510 retained frames are independently captured, rehashed against their
  event records, then byte-compared with decompressed native anchors.
- All 159,716,352 PCM bytes must match, including completion and terminal-memory
  stability observations. All 151 native sampled physics states are compared.
- Natural terminal query 27,000 at sample cursor 19,845,000, clean process exits,
  marker/position GPR and FP restoration, and prefix/sink/session cleanup pass.

Mismatch reports retain the first differing frame/time and sample cursor, raw
anchor failures, differing PCM sample/channel, and differing physics-word indices. Review exits nonzero on
failure. Compact reports can be committed; `.build/` contains the large evidence.

## Offline corruption controls

Before trusting an adapted installation, run `check_contracts.py` on a pinned,
already-closed full capture:

```sh
python3 -B size/verify/check_contracts.py \
  --config .build/verify/reference-paths.json \
  --reference-job /path/to/existing/full-capture \
  --reference-state-sha256 FULL_STATE_JSON_SHA256 \
  --output .build/verify/contract-checks.json
```

It first checks the real 27,000-frame ledger and 151 physics samples, then rejects
record corruption, fabricated late-frame timing, changed pixels/alpha, PCM
stability faults, terminal-cursor changes, and an MXCSR restoration fault. The
mutations are in memory or disposable local files. No GPU capture is started.
