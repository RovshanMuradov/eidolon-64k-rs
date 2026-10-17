# Eidolon in Rust

A Rust port of **Eidolon** by Poo-Brain, the 64k intro that won the PC 64k competition at Revision 2017. It reproduces the original exactly: under controlled capture all 27 000 frames and the whole soundtrack match the original executable byte for byte.

- Original: [pouët](https://www.pouet.net/prod.php?which=69669) · [demozoo](https://demozoo.org/productions/170753/) · [scene.org](https://files.scene.org/view/parties/2017/revision17/pc_64k_intro/eidolon_-_poo-brain_-_revision2017_64k_-_rc4.zip) · [YouTube](https://youtu.be/rsZHBJdaz-Y)
- How the original works: [docs/en](docs/en/README.md)

## Quick start

```sh
make run
```

`make run` builds the executable and starts the intro. The window shows a loading screen for a few minutes while the full soundtrack is synthesized, then plays for 7.5 minutes and exits. Escape quits.

| Command | What it does |
|---|---|
| `make build` | Builds `target/i686-pc-windows-gnu/release/eidolon-runtime.exe` |
| `make run` | Builds and runs it; `RES=1280x720 make run` changes the Wine window size |
| `make test` | Runs the Rust tests on the host |
| `make clean` | Removes build output and the private Wine prefix `.wine/` |

## Requirements

The intro is a 32-bit Windows program using OpenGL 4.5 and WinMM. Other systems run it through Wine.

| System | Status | Needs |
|---|---|---|
| Windows | native | [rustup](https://rustup.rs), [MSYS2](https://www.msys2.org) with `pacman -S make mingw-w64-i686-gcc` |
| Linux | through Wine; tested with Wine 11.17 and an NVIDIA driver | rustup, `make`, MinGW-w64 for i686, Wine with 32-bit support |
| macOS | not supported | macOS OpenGL stops at 4.1 |

MinGW-w64 packages: Arch `mingw-w64-gcc`, Debian/Ubuntu `gcc-mingw-w64-i686`, Fedora `mingw32-gcc`.

`rustup` installs the pinned toolchain and the `i686-pc-windows-gnu` target from `rust-toolchain.toml` on first build. A distribution-packaged Rust without `rustup` cannot build for this target. Mesa drivers should work if they expose an OpenGL 4.5 compatibility profile, but they are untested.

## Layout

| Path | Contents |
|---|---|
| `src/` | Engine, timeline, physics, OpenGL runtime, Win32 window and audio output |
| `src/audio/` | Port of the 64klang2 synthesizer and the score |
| `src/data/` | Timeline, curve, uniform and render-graph tables of the original |
| `shaders/` | GLSL fragments of the original |
| `docs/` | How the original binary works, in English and Russian |
| `tools/`, `tests/`, `artifacts/` | Reverse-engineering, capture and verification tooling and its recorded results |

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
