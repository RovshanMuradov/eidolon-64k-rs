# Frozen fo2 shader candidate — pending GPU verification

This change ships the recovered **fo2** data in
`size/crate/src/data/graphics.cg29`. It was built against `bcab00d`'s runtime,
layout and packer. Independent full GPU capture of the integrated executable is
still required. `size/expected.sha256` is not an acceptance record for this candidate.

## Reproduction

The committed `fo2-source.json` holds all 91 fragments and the 31 recipes.
`checkpoint-tx.cg29` preserves the earlier tx/gfx1 checkpoint, including the 12
unchanged table records. `fo2-renames.json` records candidate-to-checkpoint
internal-name/field mappings. Local declarations are resolved by scope, not by
this map. `fo2-provenance.json` pins every fragment, assembled program, recipe,
table payload, source file and resulting executable with full SHA-256 hashes.

```sh
python3 size/tools/reconstruct_shaders.py --check
python3 size/tools/reconstruct_shaders.py --output .build/fo2-reconstructed.cg29
```

Reconstruction uses only committed inputs and Python's standard library. It
checks fragment/recipe mapping, program hashes, table identity and CG29 round trip.
It does not run a search, native pool compressor, or private-path helper.

The recovered chain is `tx -> pm1 -> pm2 -> rn2 -> io2 -> fo2`. Replaying the two
historical global-permutation logs reproduced both saved permutation outputs
exactly. The remaining saved fragments/recipes match the parent's frozen fo2
candidate byte for byte. Historical wall-clock runs did not log evaluation counts
or all seed arguments; these are not invented in the manifest. **Zero new search
evaluations** were used to recover this candidate.

## Checks

```sh
python3 -m unittest discover -s size/tools -p test_shader_validation.py -v
python3 size/tools/astcheck.py \
  size/shaders/checkpoint-tx.cg29 size/crate/src/data/graphics.cg29 \
  --rename-map size/shaders/fo2-renames.json \
  --reorder-functions --uniforms-by-name --unsupported 21 -v
```

Results with glslang **11:16.4.0**:

- 20 regression tests passed. Valid-shader negative cases include `a+b` versus
  `a+a`, variable capture/shadowing, macro capture, type/interface/location
  changes, output order, global initializers, overload selection, struct members,
  swizzles, entrypoint changes, builtin-overload collisions and GLSL
  initializer-before-declaration scope.
  Unequal counts, malformed CG29/recipes, missing
  compilation support and identical compilation failures are rejected.
- Programs **0–20 and 22–30** compile unmodified on both sides and pass the
  binding-aware preprocessed-token comparison.
- Program **21 is UNSUPPORTED**, on both tx and fo2: glslang rejects
  `const vec3 Sy=normalize(vec3(.25,uE-1.,-.5));`, because its global const
  initializer depends on a uniform. Its failure is not a successful comparison.
  The complete command above therefore exits **2**, with
  `30 passed; 0 failed; 1 unsupported; 31 total`. Without `--unsupported 21`, it
  exits 1. No input is modified to suppress this limitation.
- All 12 table records also match the original `bcab00d` blob exactly.

`astcheck.py` no longer erases identifiers or compares failed compiler return
codes for equality. It compiles original inputs, expands macros through glslang,
then compares a conservative source tree with distinct declaration bindings.
Expressions, literal spellings, types, scopes, overload signatures, fields,
swizzles, builtins, entrypoint and interface names are retained. Unsupported
grammar fails closed. This deliberately does not prove arbitrary GLSL algebraic
equivalence and is not pixel acceptance.

User-defined overloads of compiler builtins are explicitly unsupported: a
user overload `sin(int)` must not allow a builtin `sin(float)` call to be renamed
to `cos(float)`. The checker reads the actual compiler's builtin symbol inventory
and rejects these ambiguous overload sets, rather than treating every call with
the same spelling as a reference to the user function.

The unsafe old `--sort` option is removed. `--reorder-functions` permits only
function/type-definition order changes. Output declaration order and executable
global-initializer order remain significant. `--uniforms-by-name` is an explicit
host contract: this runtime calls `glGetUniformLocation` by name
(`size/crate/src/graphics.rs`), so uniform declaration order can differ; names,
types, layouts, arrays and initializer expressions still must match.

### texture2D compatibility

The original `bcab00d` pool contains eight `texture2D` spellings. The recovered
tx checkpoint and fo2 both contain zero: the shipped source already uses
`texture`, rather than depending on a checking-only macro. Some original core
`#version 450` shaders therefore fail unmodified glslang compilation even before
the program-21 const limitation. Earlier driver acceptance does not make the old
checker's injected `#define texture2D texture` a compilation test of those
original bytes. The new checker injects no compatibility code, and a regression
test verifies that core-profile `texture2D` failures stay failures. The tx-to-fo2
comparison retains the recovered checkpoint's actual spellings and profiles.

## Whole executable measurement

Using the pinned Rust 1.97.1 toolchain/offline dependencies and the documented
cross-linker/Wine prerequisites, the command used for the isolated measurement is:

```sh
CARGO_BUILD_JOBS=4 python3 size/tools/measure.py \
  size/crate/src/data/graphics.cg29 \
  --work .build/fo2-measure-build --keep .build/fo2-measured \
  --nasm .build/size/nasm-2.10.09/nasm
```

The two experiment directories must be new. The optional NASM argument reuses a
local 2.10.09 build; omit it to fetch/hash-check/build the pinned source in the
new work directory. The tracked packer is built in that same work directory.
The environment's `CARGO_HOME` and `RUSTUP_HOME` may point at an existing offline
cache; reconstruction and committed inputs contain no private absolute paths.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| tx checkpoint | 93,664 | `261e528dc6aca9b20a7db54b4687e435bb6ca488d484cb1aac0991b23a4c1e60` |
| fo2 CG29 | 92,848 | `00d105dc4a09c991271f9d5f9493fda9a6b18d589f01f52f130a44b05c86166e` |
| Unprepared PE | 173,568 | `52f0d4c9c57bf6b1f0d4632b8f03d657229a21b6befa61f1ebba6f01524ef0d3` |
| Trimmed whole EXE | **46,777** | `f4dcdac406c6362af352a6d14429bf60e563a5991138f635d59fe49f6e468711` |

The historical pool proxy was 14,167 bytes; the reported final metric is the
whole executable. The parent's tx/gfx1 measurement was 47,034 bytes, making this
candidate 257 bytes smaller with the same packer/layout. Integrated retuning can
change these executable hashes and requires its own measurement and capture.

## Research-tool corrections and remaining scope

- `poolcost.py` now requires an explicit `EIDOLON_POOL_PACKER`; no private native
  packer path is embedded. Frozen reconstruction and whole-EXE builds do not
  require this optional proxy tool.
- Search processes have a hard maximum of 200 evaluations including the baseline,
  with four workers. `round.py` divides a maximum 200-evaluation budget across all
  four stages, requires a seed and a new experiment directory, and records bounds.
  Each stage publishes a complete candidate atomically and refuses overwrites.
- Local renaming now honors `--seed`. Future item-order proposals move functions
  only, preserving all global/interface declaration order. Untyped struct-field
  to swizzle normalization is removed, the untyped swizzle rewrite is disabled,
  and numeric proposal filtering uses exact decimal values instead of Python
  binary-float rounding. Candidate-generating heuristics remain proposals, not
  equivalence proofs; no new search was needed here.
- Legacy `capture.py`, `captures.py` and `bundle.py` still reference the private
  T30 workflow. They were not invoked and are not dependencies of these commands.
  The independent verifier owns capture tooling and authoritative full GPU checks.
- Program-21 glslang support and actual integrated GPU behavior remain unverified
  by this agent. No GPU captures were performed.
