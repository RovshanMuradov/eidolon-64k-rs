# Size-build tools

Run these commands from the repository root. Build prerequisites are in
[size/README.md](../README.md); generated output goes to `.build/`.

## Generated inputs

```sh
make check-size-inputs
make test-size
```

The first command checks audio streams, shader reconstruction, packer configuration
and linker layout. The second adds the PE, layout and shader regressions; it needs
`glslangValidator` and GNU `objdump`.

| Input | Generator | Check |
|---|---|---|
| Patch, score and formant tables | `generate_audio.py` | `--check` |
| `graphics.cg29` | `reconstruct_shaders.py` | `--check` |
| `model_config.inc` | `size/packer/generate_model.py` | `--check` |
| `sizecoded.ld` | `size/crate/tools/rust/layout.py` | `--check` |

The shader source, recipes, rename map and hashes are in `size/shaders/`.
`checkpoint-tx.cg29` supplies the 12 table records and the comparison checkpoint.
Reconstruction checks all 91 fragments, 31 assembled programs and the final blob.
The encoder and decoder share `model_config.inc`, generated from `model.json`.

## Shader comparison

```sh
python3 size/tools/astcheck.py \
  size/shaders/checkpoint-tx.cg29 size/crate/src/data/graphics.cg29 \
  --rename-map size/shaders/fo2-renames.json \
  --reorder-functions --uniforms-by-name --unsupported 21 -v
```

The checker compiles each unmodified program, expands macros through glslang and
compares declaration bindings, expressions, types, scopes, fields and interfaces.
Function-definition order may change; executable global-initializer and output
declaration order may not. `--uniforms-by-name` matches the runtime's
`glGetUniformLocation` contract. Ambiguous builtin overloads and unsupported syntax fail.

With glslang 16.4.0, 30 programs pass. Program 21 fails baseline and candidate
compilation because a global `const` initializer depends on a uniform. It is
explicitly `UNSUPPORTED`, so the full command exits **2**, not 0. Without that
exception it exits 1. The checkpoint and candidate already use `texture`; the
checker does not inject a `texture2D` compatibility macro. Pixel equality is
checked by the [packed-image verifier][capture-tools].

## Audio and decoder checks

```sh
python3 size/tools/verify_audio.py \
  --bank /path/to/gm.dls --reference /path/to/pcm.f32le
python3 size/packer/check.py --input .build/size/input.exe \
  --packer .build/size/packer/kkrunchy.exe
```

The audio check compares the full host-rendered PCM. The decoder check runs the
production assembly in a native Linux i386 harness and rejects damaged streams.
It requires i386 execution support, GCC, Wine and NASM 2.10.09. Both checks write
their results under `.build/`.

## Changing link order

The linker validates section membership and anonymous-constant digests against
`lay2.json`. Capture a changed object for explicit layout regeneration:

```sh
EIDOLON_SAVE_LINK="$PWD/.build/link-capture" python3 size/build.py --candidate
```

The `unrenamed/` subdirectory contains the COFF objects, libraries, `runtime.def`,
link arguments and any validation error. A successful link also saves the renamed
objects. Replays preserve rustc's output basename because the linker embeds it in `.edata`.

Migrate an existing order to the captured runtime object:

```sh
python3 size/crate/tools/rust/layout.py --migrate-order OLD-ORDER.json \
  --object RUNTIME.o --output-dir .build/new-layout
python3 size/build.py --candidate \
  --link-order .build/new-layout/sizecoded.ld \
  --layout-manifest .build/new-layout/lay2.json
```

Migration reports added/removed members, rejects ambiguous matches and appends
new members in object order. Mark a section discarded only with link-map evidence.
The script and manifest must agree. Cargo watches the linker directory and
`EIDOLON_SAVE_LINK`, so changes force a relink.

Search tools and acquisition reports are available on
[`size/finish-integration`](https://github.com/RovshanMuradov/eidolon-64k-rs/tree/size/finish-integration/size).

[capture-tools]: https://github.com/RovshanMuradov/eidolon-64k-rs/blob/d4c7756fa94beb6d7db230e254d12c682a119ed2/size/verify/README.md
