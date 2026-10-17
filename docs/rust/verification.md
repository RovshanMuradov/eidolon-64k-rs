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
