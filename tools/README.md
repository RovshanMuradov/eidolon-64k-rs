# Running tools

From the project root: `bash tools/run <command> [args]`. It wires up the project Node.js, REA, Frida, Python, Rust, Ghidra and JDK.

```bash
bash tools/run rea doctor --provider ghidra --json
bash tools/run pytest
bash tools/run frida --version
bash tools/run cargo build --target i686-pc-windows-gnu
bash tools/run wine --version
```

- Node.js 24.22.0, REA 6.5.0, Frida 17.23.3: `.tools/rea/`. Ghidra 12.1.4: `.tools/ghidra_12.1.4_PUBLIC/`.
- Rust 1.97.1 + `i686-pc-windows-gnu`: `.tools/rustup/`; binaries in `.tools/cargo/bin/`. Building a Windows EXE also needs MinGW (the target alone has no linker).
- Python libs: `.venv/`, pinned in `tools/requirements.lock`. Rebuild: `uv venv .venv --python 3.14`, then `uv pip sync --python .venv/bin/python tools/requirements.lock`.
- Arch system packages: `sudo pacman -S --needed wine mingw-w64-gcc mesa-utils`.
- Per-agent Wine: `WINEPREFIX=/tmp/opencode/eidolon/<agent>/prefix bash tools/run wine ...`. Default prefix: `/tmp/opencode/eidolon/tools/prefix`.
- A tool being installed does not prove the demo works under Wine or that Frida hooks work on it.
