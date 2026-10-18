# Verification

Equality is checked byte for byte, with no tolerances: the SHA-256 of every presented frame and of the whole soundtrack must match the original.

## What is compared

| Output | How it is produced | Compared with |
|---|---|---|
| Audio | `eidolon-engine --pcm-sha256`: full synthesis on the CPU, 159 716 352 bytes of float32 PCM | SHA-256 of the original's PCM |
| Frames | `eidolon-runtime.exe --capture`: frame `n` rendered at sample cursor `735·n`, back buffer read before `SwapBuffers` as RGBA8, bottom-up, unpadded rows | SHA-256 of the original's 27 000 frames captured the same way |

The controlled clock removes timing from the comparison: in a normal run, frames are sampled whenever the GPU finishes, so they differ between any two runs, of the original as well.

## Where the expected hashes come from

| File | Source |
|---|---|
| `verify/pcm.sha256`, `verify/frames.sha256` | The accepted reference capture of the original: NVIDIA GeForce RTX 3070 Ti, driver 610.57.04, Wine 11.17, gamescope 3.16 headless 1920×1080 |
| `verify/local/*.sha256` | Written by `make reference` on your machine; `make verify` uses them when present |

Audio is computed on the CPU and matches on any x86 machine. Frames are computed by the GPU, so the shipped frame hashes only match on the same GPU and driver; on other hardware, capture your own reference first.

## Commands

| Command | Platform | Time |
|---|---|---|
| `make verify-audio` | any x86 / x86_64 | 2–5 min |
| `make reference` | Linux | about 1–1.5 h |
| `make verify` | Linux (Wine + gamescope), Windows (native) | about 20–30 min |

`make reference` downloads the original from scene.org and `gm.dls` from the Microsoft DirectX redistributable on web.archive.org, both checked against pinned SHA-256. It then builds `opengl32.dll` and `winmm.dll` proxies against your Wine (`tools/capture/proxy-b*`, driven by `tools/reference/capture_original.py`). The proxies control the clock, read back each frame and record its hash; the original EXE is not modified. Shader program 0 gets the same `#version 450 compatibility` header as in the Rust build.

## Research verification

The research harness that accepted the port is kept in the repository.

| Path | Contents |
|---|---|
| `tools/verify/rust/` | Comparison of Rust captures with the reference: frames, PCM, shader sources, curves, physics state, GL resources |
| `tests/rust/` | Fault suite: corrupted pixels, shifted frames, changed PCM bytes and forged manifests must be rejected |
| `tools/capture/` | Capture tooling for the original and for the Rust build |
| `artifacts/reference/`, `artifacts/verification/rust/` | Hashes and results of the accepted runs |

Accepted result: all 27 000 frames and the full PCM identical, 510 retained raw frames byte-compared, physics and uniform state compared at sampled frames. Most of `tests/rust/` needs the raw reference data (5.8 GB), which is not published; 57 of its tests run without it.

## Size-build verification

The compact executable is built from `size/crate/`, postprocessed and packed.
Its verification observes the **delivered EXE** through both decoder stages
and the original entry point. The regular runtime checks above cover `src/`.

| Check | Command or evidence |
|---|---|
| Frozen audio, shader, model and layout inputs | `make check-size-inputs` |
| PE-merger, layout/model and shader regressions | `make test-size`: 34 tests; requires `glslangValidator` and GNU `objdump` |
| Complete source-level PCM | `python3 size/tools/verify_audio.py --bank /path/to/gm.dls --reference /path/to/pcm.f32le` |
| Production assembly decoder roundtrip and damaged-stream rejection | `python3 size/packer/check.py --input .build/size/input.exe --packer .build/size/packer/kkrunchy.exe` |
| Build identity | `size/build.py` writes `build.json` with input, tool and output identities; normal mode also checks `size/expected.sha256` |
| Full packed-image capture | [`size/verify/verify.py`](../../size/verify/README.md), with explicitly configured hash-pinned external references |

The full packed-image review checks 27 000 frame hashes, 510 captured raw
anchors, all 159 716 352 PCM bytes, 151 physics samples, decoded sections,
FP/GL restoration, endpoint behavior and process closure. A build-hash match
or host PCM match alone does not establish all of these properties.

The old shader checker erased identifier bindings and could accept differing
expressions or equal compile failures. Its replacement preserves bindings and
rejects count mismatches and compile failures. Program 21 is explicitly
unsupported by the offline glslang comparison; it is never counted as a pass.

Reports are keyed by the delivered file's full SHA-256. The exploratory
44 101-byte file passed `FULL_MEDIA_EXACT_PARTIAL`; the corrected 44 139-byte
candidate has a clean byte-identical rebuild and is undergoing final capture.
Native Windows testing and formal acceptance remain open. See
[integrated results](../../size/RESULTS.md) and
[runtime reports](../../size/verify/reports/README.md) for the exact scope of
each result.
