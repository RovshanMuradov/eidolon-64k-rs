# Size-optimized build

The same intro in **48 128 bytes**: 12 800 bytes (21 %) smaller than the 60 928-byte original. It renders the same 27 000 frames and the same PCM byte for byte.

| Build | Bytes |
|---|---:|
| Original (kkrunchy-packed) | 60 928 |
| Rust port, `make build` | ~730 000 |
| **Rust, size-optimized, `make size`** | **48 128** |
| Target that was not reached | 32 768 |

## Build

```sh
make size        # Linux; builds .build/eidolon-size.exe and compares it with the verified build
make run-size    # plays it under Wine; installs gm.dls into the private prefix first
```

`make size` prints `PASS size: identical to the verified build` when the result has SHA-256 `ce67aee0…` (`size/expected.sha256`). That exact file passed the full comparison with the original: all 27 000 frames and the whole PCM identical, 510 raw frames byte-compared. Performance measurements and formal acceptance of this build were not completed.

Byte identity was reproduced from a clean checkout at a different path with Rust 1.97.1 (pinned in `rust-toolchain.toml`), MinGW-w64 GCC 16.2.0, Clang 22.1 and NASM 2.10.09 (built from source by the script). Other compiler versions may produce a different, untested file; the script then prints `FAIL`.

Like the original, this build reads `gm.dls` from the Windows system directory and checks it is the standard 3 440 660-byte bank; the bank is not counted in the size.

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

Techniques in the final build:

- **No standard library.** `no_std` with its own entry point, allocator and import loader; custom i686 target and a linker wrapper without CRT; `opt-level = "z"`, `panic = immediate-abort`, fail-fast errors.
- **Audio.** Instrument samples read from the system `gm.dls` instead of embedded; score and patch stored as transposed byte streams and compact records; note-off events derived from note-on durations.
- **Graphics.** Timeline, curves and pass tables packed as byte columns; curve tangents predicted from neighbouring keys, only residuals stored; unreachable curve keys removed; shader fragments pooled, renamed and ordered for the packer.
- **Packer.** kkrunchy_k7 whose x86 filter also understands SSE and three-byte opcodes, so the compiler's SSE code compresses better.

## Layout

| Path | Contents |
|---|---|
| `crate/` | The size-optimized Rust source; `make size` stages it with the shared `shaders/`, `src/data/` and `Cargo.lock` |
| `crate/src/data/graphics.cg29` | Compressed graphics tables and shader pool |
| `crate/tools/rust/` | Custom i686 target spec and a linker wrapper without CRT |
| `packer/` | kkrunchy_k7 by Fabian "ryg" Giesen, public domain ([farbrausch/fr_public](https://github.com/farbrausch/fr_public) @ `8c8f82c`), with the x86 filter extension and two build fixes |
| `build.py` | The build and pack script behind `make size` |
| `expected.sha256` | SHA-256 of the verified 48 128-byte EXE |
