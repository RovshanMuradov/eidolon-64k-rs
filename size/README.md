# Size-optimized build

The verified build is **44 139 bytes**: 3 422 bytes (7.2 %) smaller than
the previous 47 561-byte build and 16 789 bytes (27.6 %) smaller than the
60 928-byte original. A clean checkout reproduces the exact file, and its full
packed-image capture matches all frames and PCM byte for byte.

| Build | Bytes |
|---|---:|
| Original (kkrunchy-packed) | 60 928 |
| Rust port, `make build` | ~730 000 |
| Previous fully media-verified Rust baseline | 47 561 |
| **Rust, size-optimized, `make size`** | **44 139** |
| Target that was not reached | 32 768 |

## Build

```sh
make size       # Linux; builds .build/eidolon-size.exe and checks its SHA-256
make run-size   # installs gm.dls in the private prefix and plays under Wine
```

The verified SHA-256 is
`d59888ef0ef7bb1f737e755d96892f0537037118d172073806a5ce26e47cf458`.
`make size` checks generated inputs and enforces this value through
`size/expected.sha256`. `PASS size` means identity with the file that passed the
full comparison; it does not run a new media capture.

The clean rebuild used Rust 1.97.1 (pinned in `rust-toolchain.toml`), MinGW-w64
GCC 16.2.0, Clang 22.1.8 and NASM 2.10.09, with fresh Rust and NASM build
directories. Other tool versions may produce different bytes. Build identities
and the packer comparison are in [build.json](../artifacts/verification/size/build.json).

Like the original, this build reads `gm.dls` from the Windows system directory and checks it is the standard 3 440 660-byte bank; the bank is not counted in the size.

### Candidate builds

Use a separate workspace and output when measuring an optimization:

```sh
python3 size/build.py --candidate --work-dir .build/candidate --output .build/candidate.exe
```

This prints `CANDIDATE`, not `PASS`, and leaves the accepted hash unchanged. The workspace contains
`unprepared.exe`, `input.exe`, `packed.exe`, and `build.json`: hashes of the staged inputs, tool versions,
packer identity, and delivered EXE identity. A successful build does not perform a media comparison.
`--link-order path/to/order.ld --layout-manifest path/to/lay2.json` overrides the staged layout
as a validated pair and requires `--candidate`.

Regeneration, layout experiments, shader comparison and decoder checks are
documented in [tools/README.md](tools/README.md).

## Verification

| Check | Result |
|---|---|
| Clean build | Byte-identical 44 139-byte EXE |
| Generated inputs and transformation tests | `make test-size`: all input checks and 34 tests pass |
| Regular Rust tests | Five pass |
| Host audio | All 19 964 544 stereo frames / 159 716 352 PCM bytes exact |
| Assembly decoder | 208 770-byte roundtrip, damaged-stream rejection and observer signatures pass |
| Offline shader comparison | 30 programs pass; program 21 explicitly unsupported by glslang; overall exit 2 |
| Final packed-image capture | All 27 000 frames, 510 raw anchors, full PCM and 151 physics samples exact; restoration, endpoint and cleanup pass |

The [packed-image verifier](verify/README.md) checks the delivered EXE against
external pinned references: all 27 000 frames, 510 raw anchors, the full PCM,
151 physics samples, decoder restoration, endpoint and process closure.
`make verify` instead checks the regular `src/` runtime. Native Windows testing
and formal acceptance remain open.

The earlier 44 101-byte experiment passed full media checks; its
[capture reports](verify/reports/README.md) include a separate failed smoke run.
The corrected build retains all constant data and restores public audio extent
checks, adding 38 bytes. Its independent full capture also passed. The
[completion record](../artifacts/verification/size/completion.json) binds the
clean rebuild and final capture to the same executable hash.

### Runtime observations

One uninjected playback per executable, on the same Wine/GPU setup:

| Observation | Previous 47 561-byte build | Final 44 139-byte build |
|---|---:|---:|
| Launch → first uncorked audio | 217.02 s | 237.02 s |
| Target sampled peak RSS | 954.95 MiB | 994.73 MiB |

These are single-run observations. About 32 seconds at the end of the final run
overlapped review-branch validation; both startup observations preceded it.
Cold-cache state and workload isolation are unverified. The pair establishes
neither a slowdown cause nor a statistical performance result. Full conditions
and sampling limits are in the [runtime reports](verify/reports/README.md).

## How the bytes were saved

Milestones; from 59 392 bytes on, each passed a full capture before it replaced the previous one:

| Bytes | Change |
|---:|---|
| 320 512 | Rust port packed with UPX (LZMA); baseline |
| 60 416 | `no_std` core, compact audio and graphics, packed with kkrunchy |
| 59 392 | Timeline codec: tracks plus unique curves with predicted tangents |
| 50 688 | Custom target without frame pointers; curve keys no scene can reach removed; uniforms and struct members renamed; score planes transposed and patch records relaid; GL entry points loaded from one name string; FNV-1a bank check instead of system crypto; dead shader locals removed; shader fragments reordered for the packer |
| 49 152 | Pointer-style decoders, fixed-capacity lists, static physics records, fail-fast errors, lower inlining threshold |
| 48 640 | Tuned kkrunchy context model (not used in the final build) |
| 48 128 | Note-off times derived from note durations; kkrunchy x86 filter extended to SSE and three-byte opcodes |
| 47 616 | One section per function and static, linked in an order found by hill-climbing the packed size (`crate/tools/rust/sizecoded.ld`) |
| 47 561 | Trailing zero padding after the packed data dropped; `SizeOfRawData` shrunk to match |
| 46 083 | Stronger kkrunchy context model (14 hashed models with position and word terms, 7 mixer weight sets), reworked smaller stage-1 depacker, compact stage-0 import table |
| 44 139 | Compact audio, fo2 shader pool, safe FP-load redirection, t15t model and a retuned combined layout |

The current build combines compact audio, fo2 shaders, safe FP-load
redirection and t15t. Four starting layouts and 64 proposals produced the frozen
order. On the same final PE, t14m7 packs to 44 288 bytes and t15t to **44 139**.

Techniques in the final build:

- **No standard library.** `no_std` with its own entry point, allocator and import loader; custom i686 target and a linker wrapper without CRT; `opt-level = "z"`, `panic = immediate-abort`, fail-fast errors.
- **Audio.** Instrument samples read from the system `gm.dls` instead of embedded; score and patch stored as transposed byte streams and compact records; note-off events derived from note-on durations. Static graph analysis removes unused controller streams and canonicalizes unused velocities. Controller values use deltas; unused formant rows are zeroed. Repository-owned generators check the frozen data.
- **Graphics.** Timeline, curves and pass tables packed as byte columns; curve tangents predicted from neighbouring keys, only residuals stored; unreachable curve keys removed. The fo2 shader pool has deterministic reconstruction, explicit rename mappings and binding-aware validation.
- **Code.** Selected DSP routines remain out of line, and backend options are chosen by packed size. The PE postprocessor redirects equal read-only FP loads using an allowlisted instruction decoder; all constant data is retained. Successful natural completion exits the process directly.
- **Packer.** kkrunchy_k7 whose x86 filter also understands SSE and three-byte opcodes. The t15t model has 14 hashed contexts and 8 mixers, including a 4 KiB region context. `model.json` generates configuration shared by encoder and decoder. The smaller decoder computes its squash table with the FPU and uses an `ebp`-relative work area; the compact stage-0 import table overlaps hints.
- **Link order.** `minimal-linker` renames anonymous `.rdata` constants to content-derived `.rd$xxxx` sections before linking; the FP pass runs after linking. The frozen manifest checks full anonymous digests, unique names and exact section membership. A changed source layout requires explicit regeneration. Trailing packed zero padding is trimmed.

Low-level changes are mapped to their source files in
[docs/rust/asm-map.md](../docs/rust/asm-map.md#compact-build-and-modified-assembly).

## Layout

| Path | Contents |
|---|---|
| `crate/` | The size-optimized Rust source; `make size` stages it with the shared `shaders/`, `src/data/` and `Cargo.lock` |
| `crate/src/data/graphics.cg29` | Compressed graphics tables and shader pool |
| `shaders/` | Frozen fo2 reconstruction sources, recipes, rename mappings and provenance |
| `crate/tools/rust/` | Custom i686 target spec, a linker wrapper without CRT and the link-order script `sizecoded.ld` |
| `packer/` | Public-domain kkrunchy_k7 by Fabian "ryg" Giesen ([farbrausch/fr_public](https://github.com/farbrausch/fr_public) @ `8c8f82c`), extended filter, shared t15t model configuration and decoder checks |
| `tools/`, `tests/` | Reproducible data generators, bounded experiments and transformation checks |
| `verify/` | Packed-image capture/review adapter, external-oracle pins and independent reports |
| `build.py` | The build and pack script behind `make size` |
| `expected.sha256` | SHA-256 of the verified 44 139-byte EXE |
