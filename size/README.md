# Size-optimized build

The same intro in **47 561 bytes**: 13 367 bytes (22 %) smaller than the 60 928-byte original. It renders the same 27 000 frames and the same PCM byte for byte.

| Build | Bytes |
|---|---:|
| Original (kkrunchy-packed) | 60 928 |
| Rust port, `make build` | ~730 000 |
| **Rust, size-optimized, `make size`** | **47 561** |
| Target that was not reached | 32 768 |

## Build

```sh
make size        # Linux; builds .build/eidolon-size.exe and compares it with the verified build
make run-size    # plays it under Wine; installs gm.dls into the private prefix first
```

`make size` prints `PASS size: identical to the verified build` when the result has SHA-256 `a46ecc05…` (`size/expected.sha256`). That exact file passed the full comparison with the original under Wine: all 27 000 frames and the whole PCM identical, 510 raw frames byte-compared. It has not been run on Windows; performance measurements and formal acceptance were not completed.

Byte identity was reproduced from a clean checkout at a different path with Rust 1.97.1 (pinned in `rust-toolchain.toml`), MinGW-w64 GCC 16.2.0, Clang 22.1 and NASM 2.10.09 (built from source by the script). Other compiler versions may produce a different, untested file; the script then prints `FAIL`.

Like the original, this build reads `gm.dls` from the Windows system directory and checks it is the standard 3 440 660-byte bank; the bank is not counted in the size.

### Candidate builds

Use a separate workspace and output when measuring an optimization:

```sh
python3 size/build.py --candidate --work-dir .build/candidate --output .build/candidate.exe
```

This prints `CANDIDATE`, not `PASS`, and leaves the accepted hash unchanged. The workspace contains
`unprepared.exe`, `input.exe`, `packed.exe`, and `build.json`: hashes of the staged inputs, tool versions,
packer identity, and delivered EXE identity. A successful build does not perform a media comparison.
`--link-order path/to/order.ld` overrides only the staged linker script and requires `--candidate`.

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

Techniques in the final build:

- **No standard library.** `no_std` with its own entry point, allocator and import loader; custom i686 target and a linker wrapper without CRT; `opt-level = "z"`, `panic = immediate-abort`, fail-fast errors.
- **Audio.** Instrument samples read from the system `gm.dls` instead of embedded; score and patch stored as transposed byte streams and compact records; note-off events derived from note-on durations.
- **Graphics.** Timeline, curves and pass tables packed as byte columns; curve tangents predicted from neighbouring keys, only residuals stored; unreachable curve keys removed; shader fragments pooled, renamed and ordered for the packer.
- **Packer.** kkrunchy_k7 whose x86 filter also understands SSE and three-byte opcodes, so the compiler's SSE code compresses better. Its context model (`model_asm.asm` for the packer, `depacker.asm` for the decoder; both must stay in step) has 14 hashed contexts whose byte masks, bit masks and position/word terms were tuned on this intro's data with a C mirror of the model, 7 mixer weight sets (previous byte, partial byte, confidence, position mod 4, high nibble, second and third previous byte), and tuned learning rates; the stage-1 decoder was reworked for size (squash table computed with the FPU, compact context init, `ebp`-relative layout). The stage-0 import table uses only a FirstThunk array with overlapped hints.
- **Link order.** `minimal-linker` renames rustc's anonymous `.rdata` constants to `.rd$xxxx` (hash of the contents) so `sizecoded.ld` can order them individually.

## Layout

| Path | Contents |
|---|---|
| `crate/` | The size-optimized Rust source; `make size` stages it with the shared `shaders/`, `src/data/` and `Cargo.lock` |
| `crate/src/data/graphics.cg29` | Compressed graphics tables and shader pool |
| `crate/tools/rust/` | Custom i686 target spec, a linker wrapper without CRT and the link-order script `sizecoded.ld` |
| `packer/` | kkrunchy_k7 by Fabian "ryg" Giesen, public domain ([farbrausch/fr_public](https://github.com/farbrausch/fr_public) @ `8c8f82c`), with the x86 filter extension and two build fixes |
| `build.py` | The build and pack script behind `make size` |
| `expected.sha256` | SHA-256 of the verified 47 561-byte EXE |
