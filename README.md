# Eidolon in Rust

A Rust port of **Eidolon** by Poo-Brain, the 64k intro that won the PC 64k competition at Revision 2017. It reproduces the original exactly: under a controlled clock all 27 000 frames and the whole soundtrack match the original executable byte for byte.

- Original: [pouët](https://www.pouet.net/prod.php?which=69669) · [demozoo](https://demozoo.org/productions/170753/) · [scene.org](https://files.scene.org/view/parties/2017/revision17/pc_64k_intro/eidolon_-_poo-brain_-_revision2017_64k_-_rc4.zip) · [YouTube](https://youtu.be/rsZHBJdaz-Y)
- How the original works: [docs/en](docs/en/README.md) · How the port works: [docs/rust](docs/rust/README.md)

**Size.** A size-optimized build of the port takes **48 128 bytes**, 21 % less than the 60 928-byte original, with the same frames and sound byte for byte: [size/](size/README.md).

**Research note.** This is a research project that tests what frontier AI models can do on a complete reverse-engineering task: understand a packed 64k binary, build an exact reference of its output, port it to another language with byte-identical results and verify that independently. The work was done by AI agents on 15–17 October 2026 (about 40 hours wall-clock, 270 commits); the human set the goals and made the override decisions. Agents, models and token use are listed in [How this project was made](#how-this-project-was-made).

## What works where

| | Windows | Linux | macOS |
|---|---|---|---|
| Watch: `make run` | native, untested | Wine | ❌ OpenGL 4.1 only |
| Check audio: `make verify-audio` | ✅ | ✅ | ✅ Intel Macs |
| Check frames: `make verify` | native, untested | Wine + gamescope, tested | ❌ |
| Capture your own reference: `make reference` | ❌ | Wine + gamescope, tested | ❌ |
| Build the 48 128-byte version: `make size` | ❌ | tested | ❌ |

Tested on Arch Linux with an NVIDIA GPU. The install commands for other systems follow their standard package names but were not run.

## 1. Install

**Arch Linux**

```sh
sudo pacman -S --needed rustup base-devel clang python wine mingw-w64-gcc gamescope libpulse libarchive openssl
rustup default stable
```

**Debian, Ubuntu**

```sh
sudo dpkg --add-architecture i386 && sudo apt update
sudo apt install build-essential clang python3 wine wine32:i386 gcc-mingw-w64-i686 gamescope pulseaudio-utils libarchive-tools openssl curl
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

**Fedora**

```sh
sudo dnf install make gcc clang python3 wine mingw32-gcc gamescope pulseaudio-utils bsdtar openssl
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

**Windows**

1. Install Rust with the GNU host: run [rustup-init.exe](https://rustup.rs) and choose `x86_64-pc-windows-gnu` as the default host.
2. Install [MSYS2](https://www.msys2.org), open the **MSYS2 MINGW32** shell and run:

```sh
pacman -S make diffutils mingw-w64-i686-gcc
export PATH="$PATH:$(cygpath "$USERPROFILE")/.cargo/bin"
```

Run all following commands in that shell. The first build downloads the pinned Rust toolchain from `rust-toolchain.toml`.

## 2. Get the code

```sh
git clone <repository-url> eidolon
cd eidolon
```

## 3. Watch

```sh
make run
```

A loading screen stays for a few minutes while the soundtrack is synthesized; then the intro plays for 7.5 minutes and exits. Escape quits. On Linux it runs in a 1920×1080 Wine window; `make run RES=1280x720` makes it smaller.

## 4. Verify

Each check prints one line: `PASS …` or `FAIL …` with the first differing frames.

**Audio**: any machine, about 3 minutes.

```sh
make verify-audio
```

```text
PASS audio: 9b1aa5f18aea89e27415ce82bd142b2e66bab3adaa7db4eab64f119fd33e631d
```

**Frames**: pick the line for your machine. Frames are drawn by the GPU, and different GPUs or drivers round shader math differently, so the shipped frame hashes only fit the hardware they were captured on.

| Your machine | Commands | Time |
|---|---|---|
| NVIDIA RTX 3070 Ti, driver 610.57.04, Linux | `make verify` | 1–1.5 h |
| Any other GPU, Linux | `make reference`, then `make verify` | 2–3 h |
| Windows | `make verify`; expect `FAIL` unless the GPU and driver match the row above | 1–1.5 h |

```text
PASS frames: 27000/27000 identical to verify/local/frames.sha256
```

`make reference` captures the original on your GPU into `verify/local/`; `make verify` then compares against it instead of the shipped hashes. It needs the original archive [eidolon_-_poo-brain_-_revision2017_64k_-_rc4.zip](https://files.scene.org/view/parties/2017/revision17/pc_64k_intro/eidolon_-_poo-brain_-_revision2017_64k_-_rc4.zip): put it in the repository root, pass it as `make reference ARCHIVE=~/Downloads/eidolon_-_poo-brain_-_revision2017_64k_-_rc4.zip`, or let the command download it. It also downloads `gm.dls` from the Microsoft DirectX redistributable on web.archive.org. Both files are checked against pinned SHA-256.

During frame checks the GPU renders in an invisible window; leave the machine otherwise idle. On Windows the capture window is 1920×1080 and needs a monitor at least that large. Details: [docs/rust/verification.md](docs/rust/verification.md).

**Unit tests**: `make test`, a few seconds.

## 5. Size-optimized build (optional, Linux)

```sh
make size        # about 1 minute
make run-size    # plays the 48 128-byte EXE under Wine
```

```text
.build/eidolon-size.exe: 48128 bytes (original: 60928 bytes)
PASS size: identical to the verified build, SHA-256 ce67aee06109441cf8d1694b197b9a8bee9cea0b443575aa1234fd20a0d7f74e
```

`PASS` means the build is byte-identical to the 48 128-byte EXE that passed the full frame and audio comparison. NASM 2.10.09 is downloaded and built by the script. Details and the techniques used: [size/README.md](size/README.md).

## All commands

| Command | What it does |
|---|---|
| `make build` | Builds `target/i686-pc-windows-gnu/release/eidolon-runtime.exe` |
| `make run` | Builds and plays |
| `make verify-audio` | Synthesizes the soundtrack and compares its SHA-256 |
| `make verify` | Renders all frames with a controlled clock and compares their SHA-256 |
| `make reference` | Captures the original on this machine into `verify/local/` |
| `make size` | Builds the 48 128-byte version and compares it with the verified one |
| `make run-size` | Plays the 48 128-byte version |
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
| `size/` | Size-optimized source, patched kkrunchy packer and build script |
| `tools/`, `tests/`, `artifacts/` | Reverse-engineering, capture and verification tooling and recorded results |

## How this project was made

**Goal:** reverse-engineer the 60 928-byte intro, build an exact reference of its frames and sound, rewrite it in Rust with identical output, then shrink the Rust build toward 32 KiB without losing exactness.

| Step | Task | Result |
|---|---|---|
| 1 | Reproducible reference of the original: run it under Wine, control its clock, capture every frame and the PCM, prove repeated runs are identical and that corruption is detected | 27 000 frames + full PCM; repeated full runs byte-identical |
| 2 | Understand the original: unpack, recover algorithms, data and the synthesizer; explain the 64k size | [docs/en](docs/en/README.md), 64klang2 source match, size breakdown |
| 3 | Rust port with byte-exact output, independently verified against the reference | This repository |
| 4 | Size optimization (sizecoding, packers), target 32 KiB | 48 128 bytes with all frames and PCM exact ([size/](size/README.md)); 32 KiB not reached; performance acceptance open |
| 5 | Final reproducible build and verification | Not started |

**Agents.** The work was done by AI agents with a coordinator and workers:

- The coordinator only planned: split each step into tasks (T1–T33), wrote a brief of at most 15 lines per task, accepted 4-line replies and recorded every decision as one line in a state file. By protocol it never read code or logs itself.
- Workers had fixed roles per step: reverse engineering, capture, independent verification; graphics & engine and audio & compactness; Rust engine, Rust audio and independent verification; optimization and candidate verification.
- Each task ran in its own git worktree and branch with a fixed write zone; the coordinator merged finished branches. Agents agreed shared formats through handoff files with one owner, never through the coordinator.
- Verification was always a separate agent from the one producing the result, and compared against the original's reference, never against values computed by the port.
- GPU runs were serialized; runs longer than 45 minutes were detached and polled.
- Harnesses: OpenCode 2 for steps 1–3 and the start of step 4, then Claude Code as coordinator.

| Harness | Model | Effort | Sessions | Input | Output | Cache |
|---|---|---|---:|---:|---:|---:|
| OpenCode 2 | GPT-6 Astra | xhigh | 55 | 10.0 M | 2.5 M | 448.1 M |
| OpenCode 2 | GPT-6.1 Sol | high | 7 | 0.7 M | 0.1 M | 31.3 M |
| Claude Code | Claude Opus 5.5 | high | — | < 0.1 M | 0.2 M | 266.7 M |
| **Total** | | | | **10.7 M** | **2.8 M** | **746.0 M** |

Tokens from the harnesses' local session logs, 15–17 October 2026; output includes reasoning, cache counts cache reads and writes. The later documentation session is not included.

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
