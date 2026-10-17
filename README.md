# Eidolon in Rust

A Rust port of **Eidolon** by Poo-Brain, the 64k intro that won the PC 64k competition at Revision 2017. It reproduces the original exactly: under a controlled clock all 27 000 frames and the whole soundtrack match the original executable byte for byte.

- Original: [pouët](https://www.pouet.net/prod.php?which=69669) · [demozoo](https://demozoo.org/productions/170753/) · [scene.org](https://files.scene.org/view/parties/2017/revision17/pc_64k_intro/eidolon_-_poo-brain_-_revision2017_64k_-_rc4.zip) · [YouTube](https://youtu.be/rsZHBJdaz-Y)
- How the original works: [docs/en](docs/en/README.md) · How the port works: [docs/rust](docs/rust/README.md)

**Research note.** This is a research project that tests what frontier AI models can do on a complete reverse-engineering task: understand a packed 64k binary, build an exact reference of its output, port it to another language with byte-identical results and verify that independently. The work was done by AI agents on 15–17 October 2026 (about 40 hours wall-clock, 270 commits); the human set the goals and made the override decisions. Agents, models and token use are listed in [How this project was made](#how-this-project-was-made).

## Requirements

| | Windows | Linux | macOS |
|---|---|---|---|
| Watch (`make run`) | ✅ native, untested | ✅ Wine | ❌ OpenGL 4.1 only |
| Check audio (`make verify-audio`) | ✅ | ✅ | ✅ Intel Macs |
| Check frames (`make verify`) | ✅ native, untested | ✅ Wine + gamescope, tested | ❌ |
| Capture your own reference (`make reference`) | ❌ | ✅ Wine + gamescope | ❌ |

Install:

- **All:** [rustup](https://rustup.rs). It installs the pinned toolchain and the `i686-pc-windows-gnu` target on first build; a distribution Rust without rustup cannot build this target.
- **Windows:** install rustup with the GNU host (`rustup-init --default-host x86_64-pc-windows-gnu`; the MSVC host would need Visual Studio build tools) and [MSYS2](https://www.msys2.org) with `pacman -S make diffutils mingw-w64-i686-gcc`. Run the commands below in the **MSYS2 MINGW32** shell, with `~/.cargo/bin` on `PATH`. The Windows path is written for native use but has not been run on Windows.
- **Linux:** `make`, Python 3.11+, Wine with 32-bit support, MinGW-w64 for i686. For `make verify` and `make reference` also `gamescope`, `pactl` (PulseAudio or PipeWire), `bsdtar` and `openssl`.

| Distribution | MinGW-w64 package |
|---|---|
| Arch | `mingw-w64-gcc` |
| Debian, Ubuntu | `gcc-mingw-w64-i686` |
| Fedora | `mingw32-gcc` |

## Watch

```sh
make run
```

A loading screen stays for a few minutes while the whole soundtrack is synthesized; then the intro plays for 7.5 minutes and exits. Escape quits. On Linux it runs in a 1920×1080 Wine virtual desktop; `RES=1280x720 make run` changes the size.

## Verify

**1. Audio**, any machine, a few minutes:

```sh
make verify-audio
```

**2. Frames on the reference hardware** (NVIDIA RTX 3070 Ti, driver 610.57.04), about 1–1.5 hours:

```sh
make verify
```

**3. Frames on any other GPU**, Linux only, about 2–3 hours:

```sh
make reference    # captures the original on your GPU into verify/local/
make verify       # captures the Rust build and compares it with verify/local/
```

`make reference` needs the original archive `eidolon_-_poo-brain_-_revision2017_64k_-_rc4.zip` from [scene.org](https://files.scene.org/view/parties/2017/revision17/pc_64k_intro/eidolon_-_poo-brain_-_revision2017_64k_-_rc4.zip). Put it in the repository root, or pass its path: `make reference ARCHIVE=~/Downloads/eidolon_-_poo-brain_-_revision2017_64k_-_rc4.zip`. Without it, the archive is downloaded from scene.org mirrors. It also downloads `gm.dls` from the Microsoft DirectX redistributable on web.archive.org. Both are checked against pinned SHA-256.

Each command ends with `PASS` or `FAIL` and the first differing frames. Frames are rendered by the GPU, so shipped frame hashes match only on the same GPU and driver; audio matches everywhere. Details: [docs/rust/verification.md](docs/rust/verification.md).

| Command | What it does |
|---|---|
| `make build` | Builds `target/i686-pc-windows-gnu/release/eidolon-runtime.exe` |
| `make run` | Builds and plays |
| `make verify-audio` | Synthesizes the soundtrack and compares its SHA-256 |
| `make verify` | Renders all frames with a controlled clock and compares their SHA-256 |
| `make reference` | Captures the original on this machine into `verify/local/` |
| `make test` | Rust unit tests |
| `make clean` | Removes build output, `.build/` and the private Wine prefix `.wine/` |

## Layout

| Path | Contents |
|---|---|
| `src/` | Engine, timeline, physics, OpenGL runtime, Win32 window, audio output |
| `src/audio/` | Port of the 64klang2 synthesizer, score and samples |
| `src/data/`, `shaders/` | Tables and GLSL of the original, unchanged |
| `verify/` | Expected hashes of the original's frames and PCM |
| `docs/en`, `docs/ru` | How the original binary works |
| `docs/rust` | How the port works and how it is verified |
| `tools/`, `tests/`, `artifacts/` | Reverse-engineering, capture and verification tooling and recorded results |

## How this project was made

**Goal:** reverse-engineer the 60 928-byte intro, build an exact reference of its frames and sound, rewrite it in Rust with identical output, then shrink the Rust build toward 32 KiB without losing exactness.

| Step | Task | Result |
|---|---|---|
| 1 | Reproducible reference of the original: run it under Wine, control its clock, capture every frame and the PCM, prove repeated runs are identical and that corruption is detected | 27 000 frames + full PCM; repeated full runs byte-identical |
| 2 | Understand the original: unpack, recover algorithms, data and the synthesizer; explain the 64k size | [docs/en](docs/en/README.md), 64klang2 source match, size breakdown |
| 3 | Rust port with byte-exact output, independently verified against the reference | This repository |
| 4 | Size optimization (sizecoding, packers) | In progress, not in this repository: best candidate 48 128 bytes with all frames and PCM exact; final acceptance open |
| 5 | Final reproducible build and verification | Not started |

**Agents.** The work was done by AI agents with a coordinator and workers:

- The coordinator only planned: split each step into tasks (T1–T33), wrote a brief of at most 15 lines per task, accepted 4-line replies and recorded every decision as one line in a state file. By protocol it never read code or logs itself.
- Workers had fixed roles per step: reverse engineering, capture, independent verification; graphics & engine and audio & compactness; Rust engine, Rust audio and independent verification; optimization and candidate verification.
- Each task ran in its own git worktree and branch with a fixed write zone; the coordinator merged finished branches. Agents agreed shared formats through handoff files with one owner, never through the coordinator.
- Verification was always a separate agent from the one producing the result, and compared against the original's reference, never against values computed by the port.
- GPU runs were serialized; runs longer than 45 minutes were detached and polled.
- Harnesses: OpenCode 2 (development build 0.0.0-dev-20987, with a `/goal` coordinator plugin) for steps 1–3 and the start of step 4; Claude Code 2.1.299 as coordinator from the second half of step 4.

| Harness | Model | Reasoning effort | Sessions / calls | Use |
|---|---|---|---|---|
| OpenCode 2 | `gpt-6-astra` | xhigh (2 sessions low) | 55 sessions | Coordinator and most workers, steps 1–4 |
| OpenCode 2 | `gpt-6.1-sol` | high | 7 sessions | Audit of the size candidate, launch diagnosis, license check |
| Claude Code | `claude-opus-5-5` | high; xhigh for the size worker T30 | 834 API calls | Coordinator and the step 4 size worker |

| Tokens | OpenCode 2 | Claude Code | Total |
|---|---:|---:|---:|
| Input, uncached | 10 736 608 | 1 672 | 10 738 280 |
| Input, cache read | 479 365 248 | 259 642 176 | 739 007 424 |
| Input, cache write | — | 7 022 603 | 7 022 603 |
| Output | 1 624 418 | 197 313 | 1 821 731 |
| of it reasoning | 977 153 | not reported | — |

Counted from the harnesses' local session logs for this project, from the first session (15 October 2026, 15:27 UTC) to the end of step 4 work (17 October 2026, 07:40 UTC); the later documentation and publication session is not included.

**Tools.**

| Purpose | Tools |
|---|---|
| Static analysis | Ghidra 12.1.4 through the REA MCP server, objdump |
| Unpacking | Memory dumps after kkrunchy, compared with the public kkrunchy source |
| Running and capture | Wine 11.17, gamescope (headless), proxy `opengl32.dll`/`winmm.dll` built with MinGW-w64, Frida |
| Audio recovery | Public 64klang2 source, compiled and compared with the binary sample by sample |
| Port | Rust 1.97, no external crates |
| Verification | Python, SHA-256 per frame, Zstandard for stored raw frames |

## Credits

**Eidolon** by Poo-Brain:

| Who | Role |
|---|---|
| Andro | Direction, shaders |
| Tropical Trevor | Code, tools, shaders |
| Wurstgetrank | Shaders |
| Glow | 2D, font, shaders |
| Roeltje | Physics code |
| Punqtured | Music, sound design |
| Virgill | Music, sound design |
| Gopher | 64klang2, film grain, vignette |
| Beftex | Co-direction, Andro-nerve-controller |
| Maikel | Concept art |

Instrument samples in `src/audio/gmdls_samples.rs` come from the Roland GM/GS Sound Set (`gm.dls`), © 1996 Roland Corporation.

## License

The Rust code, tools and documentation are licensed under either of [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE), at your option. The shaders, music, animation data and instrument samples belong to their authors listed above and are not covered by these licenses.
