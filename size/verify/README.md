# Packed-image verification

`verify.py` checks the delivered EXE under Wine/Gamescope, including both depacker
stages and the application entry point. It uses hash-pinned reference parsers and
a C observer. The external reference archive is required.

A passing full capture reports `FULL_MEDIA_EXACT_PARTIAL`. Build reproduction,
playback measurements and native Windows testing have separate results. The
current results are in [reports/](reports/README.md).

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
`reference_shared` resolves the reference manifest's `shared` bindings. References
are read-only; each capture gets its own prefix, audio sink and cache directory.

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
  --job .build/verify/full --full

python3 size/verify/verify.py review \
  --config .build/verify/reference-paths.json \
  --job .build/verify/full --output .build/verify/full-review.json
```

Omit `--full` for a three-frame smoke run with full PCM. Use a fresh job directory
for each run. The timeout is one hour for smoke and four hours for full capture;
synthesis alone can take over 15 minutes. A file lock serializes this checkout's
captures. Other GPU jobs must also be stopped while capturing.

## What is checked

| Check | Required result |
|---|---|
| Identity | Candidate, PE inputs, observer, references, captured files and mapped image match their hashes |
| PE preparation | Only the export directory and unused `.eh_fram`/`.edata` contents cleared |
| Unpacking | Three register/FP restoration checks; entry/marker fingerprints and decoded sections exact |
| Frames | 27 000 RGBA hashes, clocks and scene records exact; 510 independently captured raw anchors byte-compared |
| Audio | All 159 716 352 PCM bytes exact; completion and terminal memory stable |
| State | 151 physics samples, 27 000 GL restoration records, marker/position register and FP state exact |
| Endpoint | Terminal query 27 000 at sample 19 845 000; one clean child/Wine/Gamescope exit and complete cleanup |

Decoded-section comparison masks the seven-byte marker hook. Import and relocation
sections are transformed by the loader. Review exits nonzero on failure and records
the first differing frame, sample/channel or physics word. Large captures stay in `.build/`.

## Corruption tests

Run against a hash-pinned, closed full capture:

```sh
python3 -B size/verify/check_contracts.py \
  --config .build/verify/reference-paths.json \
  --reference-job /path/to/existing/full-capture \
  --reference-state-sha256 FULL_STATE_JSON_SHA256 \
  --output .build/verify/contract-checks.json
```

The tests reject changed pixels, timing, PCM, physics/FP state, terminal cursors
and exit records. Mutations use memory or temporary files. Add
`--manifest .build/verify/candidate/candidate.json` to check candidate inputs and
reject a rehashed but invalid PE preparation transform.

## Playback measurements

`playback.py` runs the unmodified EXE with `--play` and the real audio clock. It
uses a private null sink, a fresh prefix and a separate shader-cache path. Run the
baseline first, then the candidate, using copies of the same prefix. Example:

```sh
python3 -B size/verify/playback.py run \
  --config .build/verify/reference-paths.json \
  --exe .build/verify/candidate/eidolon-runtime.exe \
  --sha256 FULL_64_CHARACTER_SHA256 --job .build/verify/playback-final
python3 -B size/verify/playback.py review \
  --job .build/verify/playback-final --output .build/verify/playback-final-review.json
```

Each run allows 1 020 seconds plus cleanup. Review checks the natural endpoint,
Wine/Gamescope exits, a 44 100 Hz stereo float stream attributed to the candidate,
file identities and process cleanup.

Measurements cover wall time, launch to first uncorked audio, and sampled process
RSS/high-water marks. Startup includes Wine, shader setup, synthesis and audio
submission. One-second sampling can miss peaks; process sums can double-count
shared pages and exclude GPU VRAM. Cache paths do not establish a cold-cache
state. A single pair supports descriptive observations only.

Compare both closed reviews with `playback.py compare --baseline BASELINE_REVIEW
--candidate FINAL_REVIEW --media FULL_MEDIA_REVIEW --output PAIRED_REPORT`.
This checks matching prefix, driver and tool conditions, final media identity
and serialized runs. `--console` includes observer diagnostics. `check_playback.py`
takes the same three review paths and `--output` to test rejection of mismatched
inputs, failed exits and incomplete cleanup.
