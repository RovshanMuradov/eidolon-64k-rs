# Exact packed-image verification

`verify.py` observes the **delivered kkrunchy executable**, including both
depacker stages and the original entry point. It reuses the hash-pinned native
oracle parsers and C observer through explicit external paths. The reference
archive is required; it is not distributed in this repository.

This is a Linux/Wine/Gamescope verification harness. A successful full result is
`FULL_MEDIA_EXACT_PARTIAL`, with `production_accepted: false`. It does not certify
native Windows behavior, clean-build reproducibility, or performance.
`not_assessed_by_media_review` describes this review's scope; companion playback
reports and candidate-keyed rebuild attestations can provide that evidence without
leaving a stale claim that those tasks are unperformed.

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
  marker/position GPR and FP restoration, and prefix/sink/session/supervisor
  cleanup pass. Exactly one clean child and wrapper exit record is required;
  Wine exit zero cannot mask a Gamescope teardown failure.

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
It also rejects failing or duplicate process-closure records. Add
`--manifest .build/verify/candidate/candidate.json` to test the preserved candidate
inputs and rejection of a rehashed but invalid preparation transform.

## Bounded, uninjected playback observations

`playback.py` adapts the pinned reference playback observer. It launches the
unmodified EXE directly with `--play`, using the real audio clock, a private null
sink, fresh prefix, and separate requested shader-cache paths. It shares the capture
lock. Run at most one baseline and one final playback, sequentially:

```sh
python3 -B size/verify/playback.py run \
  --config .build/verify/reference-paths.json \
  --exe .build/verify/candidate/eidolon-runtime.exe \
  --sha256 FULL_64_CHARACTER_SHA256 --job .build/verify/playback-final
python3 -B size/verify/playback.py review \
  --job .build/verify/playback-final --output .build/verify/playback-final-review.json
```

Each run is bounded to 1,020 seconds plus cleanup. Review requires the real-clock
natural endpoint, exactly one clean Wine/Gamescope closure, an actual uncorked
44100 Hz stereo float stream attributed to the mapped candidate and private sink,
unchanged executable/source/telemetry identities, and complete process cleanup.

The measurements are total launcher wall time, startup to first uncorked audio,
target-process sampled RSS/high-water mark, and sampled sum of owned process RSS.
The latter includes the runner session and prefix services and can double-count
shared pages. GPU VRAM and shared system services are outside that measurement.
One-second external samples can miss a peak. Startup includes Wine/bootstrap,
shader setup, synthesis, and device submission; it does not isolate synthesis or
unpacking. No injected capture frames, frame-file I/O timings, or native FPS are
reported as playback performance. A single matched pair is descriptive evidence,
not a statistical benchmark or a formal acceptance threshold.
The review records whether the requested NVIDIA cache directory/files exist;
their presence or absence does not establish an effective cold-cache state.

Join the closed reviews with `playback.py compare --baseline BASELINE_REVIEW
--candidate FINAL_REVIEW --media FULL_MEDIA_REVIEW --output PAIRED_REPORT`.
It requires matching prefix seed/driver context/tool versions, successful strict
reviews, candidate identity, and serialized acquisition timestamps. The optional
`--console` argument pins external observer diagnostics. `check_playback.py` takes
the same three review paths and `--output`; it tests rejection of mismatched
prefixes/media identities, failed playback closure, and surviving supervisors
without starting another playback.
