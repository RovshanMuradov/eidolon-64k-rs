# Size-optimized build

The integrated candidate is **44 139 bytes**: 3 422 bytes (7.2 %) smaller than
the previous 47 561-byte build and 16 789 bytes (27.6 %) smaller than the
60 928-byte original. A clean checkout reproduces the exact file. Its final
packed-image verification is in progress; see [RESULTS.md](RESULTS.md).

| Build | Bytes |
|---|---:|
| Original (kkrunchy-packed) | 60 928 |
| Rust port, `make build` | ~730 000 |
| Previous fully media-verified Rust baseline | 47 561 |
| **Integrated Rust candidate, `size/build.py --candidate`** | **44 139** |
| Target that was not reached | 32 768 |

## Build

```sh
make check-size-inputs
python3 size/build.py --candidate   # Linux; builds .build/eidolon-size.exe and records build.json
```

The candidate SHA-256 is
`d59888ef0ef7bb1f737e755d96892f0537037118d172073806a5ce26e47cf458`.
`make size` also enforces `size/expected.sha256`, which still pins the previous
47 561-byte file (`a46ecc05…`) until final verification completes. It currently
reports a hash mismatch for the new candidate. `make run-size` passes that same
gate before installing `gm.dls` in the private prefix and playing under Wine.

The old pinned file passed all 27 000 frame hashes and the full PCM, including
510 raw frame comparisons. The exploratory 44 101-byte file also passed a full
capture; its report belongs to that exact hash. The final corrected 44 139-byte
file is undergoing its own capture. Native Windows and formal acceptance remain open.

Byte identity was reproduced from a clean checkout at a different path with Rust 1.97.1 (pinned in `rust-toolchain.toml`), MinGW-w64 GCC 16.2.0, Clang 22.1 and NASM 2.10.09 (built from source by the script). Other compiler versions may produce a different, untested file; the script then prints `FAIL`.

The current clean-rebuild attestation is linked from [RESULTS.md](RESULTS.md).
Candidate mode records the actual hash instead of comparing it with the accepted pin.

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
as a validated pair and requires `--candidate`; see [INTEGRATED-LAYOUT.md](INTEGRATED-LAYOUT.md).

To compare packers against the same already-built PE:

```sh
python3 size/tools/pack_matrix.py \
  --input combined=.build/candidate/unprepared.exe \
  --packer tuned=.build/candidate/packer/kkrunchy.exe \
  --work-dir .build/matrix
```

Repeat `--input` or `--packer` for a finite matrix. The fresh output directory retains each candidate
and its manifest; measurements never replace the accepted hash.

For the delivered packed executable's independent frame/audio/depacker verification, use
[`verify/`](verify/README.md). Its reference archive and hash-pinned observer toolkit are external,
explicitly configured inputs. `make verify` checks the regular runtime, not the packed size build.

`make check-size-inputs` checks frozen audio, shaders, model configuration and linker layout without
rewriting them; `make size` also runs these checks. `make test-size` adds the CPU-only transformation
regressions and requires `glslangValidator`. Full source-level PCM can be checked with
`python3 size/tools/verify_audio.py --bank /path/to/gm.dls --reference /path/to/pcm.f32le`.

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

The current **44 139-byte candidate** combines t15t, compact audio, the fo2
shader pool, safe FP-load redirection and a retuned layout. Its source and
decoder checks and clean rebuild passed; final runtime evidence is tracked in
[RESULTS.md](RESULTS.md).

Techniques in the final build:

- **No standard library.** `no_std` with its own entry point, allocator and import loader; custom i686 target and a linker wrapper without CRT; `opt-level = "z"`, `panic = immediate-abort`, fail-fast errors.
- **Audio.** Instrument samples read from the system `gm.dls` instead of embedded; score and patch stored as transposed byte streams and compact records; note-off events derived from note-on durations. Static graph analysis removes unused controller streams and canonicalizes unused velocities. Controller values use deltas; unused formant rows are zeroed. Repository-owned generators check the frozen data.
- **Graphics.** Timeline, curves and pass tables packed as byte columns; curve tangents predicted from neighbouring keys, only residuals stored; unreachable curve keys removed. The frozen fo2 shader pool has deterministic reconstruction, explicit rename mappings and binding-aware validation; see [shaders/fo2-notes.md](shaders/fo2-notes.md).
- **Code.** Selected DSP routines remain out of line, and backend options are chosen by packed size. The PE postprocessor redirects equal read-only FP loads using an allowlisted instruction decoder; all constant data is retained. Successful natural completion exits the process directly.
- **Packer.** kkrunchy_k7 whose x86 filter also understands SSE and three-byte opcodes. The t15t model has 14 hashed contexts and 8 mixers, including a 4 KiB region context. `model.json` generates configuration shared by encoder and decoder. The smaller decoder computes its squash table with the FPU and uses an `ebp`-relative work area; the compact stage-0 import table overlaps hints. [Recovery notes](packer/RECOVERY.md) distinguish the historical recovered checkpoint from integrated builds.
- **Link order.** `minimal-linker` renames anonymous `.rdata` constants to content-derived `.rd$xxxx` sections before linking; the FP pass runs after linking. The frozen manifest checks full anonymous digests, unique names and exact section membership. A changed source layout requires explicit regeneration. Trailing packed zero padding is trimmed.

## Documentation and evidence

| Read | Purpose |
|---|---|
| [RESULTS.md](RESULTS.md) | Overall result, sizes, correctness fixes, clean rebuild and current verification status |
| [INTEGRATED-LAYOUT.md](INTEGRATED-LAYOUT.md) | Frozen section order, bounded search, explicit layout regeneration and replay |
| [packer/RECOVERY.md](packer/RECOVERY.md) | Historical t15t/lay2 recovery, model synchronization and decoder reproduction |
| [shaders/fo2-notes.md](shaders/fo2-notes.md) | Shader reconstruction, rename mappings, checker behavior and unsupported program 21 |
| [verify/README.md](verify/README.md) | How to capture/review a packed EXE using the external pinned oracle |
| [verify/reports/README.md](verify/reports/README.md) | Results tied to each captured EXE's SHA-256, including failed runs |
| [reports/](reports/) | Machine-readable clean-rebuild and complete-packer comparison evidence |
| [../docs/rust/asm-map.md](../docs/rust/asm-map.md#compact-build-and-modified-assembly) | Engineering map from original routines to Rust and modified ASM sources |

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
| `expected.sha256` | Current verified-build pin; still the 47 561-byte baseline while final candidate verification runs |
