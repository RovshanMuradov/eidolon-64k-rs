# t15t / lay2 recovery

This is a source recovery of the completed research candidate, based on
`a29719c`, rather than a new layout search. `recovery.json` records its exact
input/output fingerprints. The reference artifacts are generated files and
are not required to build the checked-in source.

## Model and decoder

`model.json` transcribes research `c15.json`: 14 contexts, 60 MMX inputs,
8 mixers and 6,656 weight rows. `generate_model.py` generates the shared
`model_config.inc` used by both complete assembly implementations. Context
mask bit 7 selects the word hash; bit 6 selects the region hash. The fifth
extra mixer selects a 4 KiB region. Its byte-sized selector limits this
model to prefilter streams below 1 MiB; the packer checks that limit.

The depacker includes the recovered t15t work-area ordering, squash/table
initialization size changes, and region hashing. Assembled with NASM 2.10.09,
its RDF is byte-for-byte identical to the recovered t15t RDF (2,225 bytes).
The `W_src = 0` invariant and the observer's entry/import-tail instruction
patterns are preserved and checked. Encoder model state is explicitly reset
between calls, including calls to the existing C++ reverse coder. The scratch
interactive serving protocol is not needed by the production build.

Regenerate and check:

```sh
python3 size/packer/generate_model.py
python3 size/packer/generate_model.py --check
```

## Layout and linker integration

`size/crate/tools/rust/lay2.json` contains the completed order: 55 retained
function sections, 91 read-only sections (86 anonymous), and the one known
GC-discarded `rust_eh_personality` section. The generated blocks in
`sizecoded.ld` reproduce the exact-name research link. Rust v0 crate hashes
and base62 back-references, including uppercase `BM_` and `B1U_`, are
wildcarded. Every pattern must match exactly one object section, and every
section must have exactly one slot.

Anonymous names preserve the recovered `.rd$` plus four SHA-1 hex digits
of `contents || little_endian_u32(relocation_count)`. Names are independent
of section enumeration order. Collisions are errors rather than order-based
renumbering; the manifest checks full digests as well. Added, removed,
ambiguous or changed anonymous members stop the link with an explanation.
New integrated code/data requires an explicit layout regeneration/retune.

The overlap with another linker pass is **`size/crate/tools/rust/minimal-linker`**:
keep `prepare_object()` and its replacement object **before** invoking the
linker; run PE constant merging **after** that invocation. A post-link pass
must replace the final `os.execvp` with a checked subprocess call.
`EIDOLON_SAVE_LINK` still saves the renamed object. `size/build.py` checks
generated model/layout inputs and invalidates the Cargo target cache when
linker/layout sources change, because Cargo does not track `-T` contents.

```sh
python3 size/crate/tools/rust/layout.py --check
python3 -m unittest discover -s tests -p test_size_layout.py -v
```

For an explicitly supplied new order and unrenamed COFF object:

```sh
python3 size/crate/tools/rust/layout.py --import-order ORDER.json --object RUNTIME.o
```

`ORDER.json` has `text` and `rdata` arrays of exact section names (anonymous
sections use their renamed identities). Unlisted sections are recorded as
discarded; use the link map to establish that they really are GC-discarded.
This import command is an explicit recovery/tuning action, never a build step.

## Reproduction and checks

With the repository's pinned Cargo/Rust environment and tools on `PATH`:

```sh
python3 size/build.py
python3 size/packer/check.py --input .build/size/input.exe \
  --packer .build/size/packer/kkrunchy.exe
```

The first command writes `.build/eidolon-size.exe` and then **reports the
expected hash mismatch** against the older accepted `size/expected.sha256`.
That acceptance file is intentionally left to final verification/integration.
The second command uses its own Wine prefix, captures `KK_DUMP` immediately
before range coding, and decodes with the production assembly in a native
freestanding Linux i386 harness. It verifies all 207,205 prefilter bytes,
output guards, the observer signatures, and rejection of a corrupted stream.
On the known prepared input it also enforces the recovered packed and trimmed
hashes. Products and `report.json` are under `.build/packer-check`.

Recovered size matrix (same baseline Rust program):

| Model | Layout | Trimmed bytes |
| --- | --- | ---: |
| committed t14m7 | old | 46,083 |
| committed t14m7 | lay2 | 45,989 |
| t15t | old | 45,900 |
| t15t | lay2 | **45,782** |

Final SHA-256: `35f2eeda640ad18ad3d60fc0fa60854b7b4eb23d415f0c3d52a35a4daf204f31`.
The clean Rust rebuild also reproduces the unprepared 175,104-byte PE and
prepared input exactly; no saved objects are needed. Tested tools: Rust 1.97.1,
NASM 2.10.09, Clang 22.1.8, MinGW GCC 16.2.0, Binutils 2.47.20260726,
host GCC 16.2.1, Wine 11.17.

Scope: these checks establish packer reproduction and prefilter decoding.
They do not execute stage2/import restoration or verify graphics/audio.
Native image-loader and exact media acceptance belong to the integration
verifier. No additional tuning was performed during this recovery.
