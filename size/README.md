# Size optimization: source review

This branch is a code excerpt for review. Generated score/shader payloads, JSON
inputs, generators and tests are omitted, so it cannot reproduce the executable.
The complete buildable version is preserved at [checkpoint `7eb8cc3`][buildable]
and locally on `size/review-buildable`.

## Before → after

| Read | Change |
|---|---|
| [`packer/model_asm.asm`](packer/model_asm.asm), [`model_config.inc`](packer/model_config.inc) | 11 contexts / 3 mixers → 14 / 8; added word, position and 4 KiB-region terms improve bit prediction |
| [`packer/depacker.asm`](packer/depacker.asm) | Work fields grouped near `EBP` for short displacements; squash table computed with x87; smaller initialization sequences |
| [`packer/exepacker.cpp`](packer/exepacker.cpp) | Duplicate import tables → one thunk array with shared terminator/hint bytes |
| [`crate/src/audio/`](crate/src/audio/) | Selected DSP functions kept out of line; exact constant products folded, e.g. `44100 × 2 → 88200`; controller deltas decoded by prefix sum; unused formant rows zeroed |
| [`crate/tools/rust/`](crate/tools/rust/) | Anonymous COFF constants given stable names before linking; function/data order retuned; equal immutable FP reads redirected to shared addresses after linking |
| [`build.py`](build.py) | Basic register allocation; machine LICM, machine CSE and early tail duplication disabled, chosen by packed size |
| [`crate/src/runtime.rs`](crate/src/runtime.rs) | Natural completion exits the process directly, avoiding teardown code |

The FP pass retains every constant byte and checks instruction encoding, read
width, alignment and relocations. The linker checks unique section membership
and full constant digests. These production transformations account for the
remaining Python code in this review.

## Measured result of the complete build

| Build | Bytes |
|---|---:|
| Previous Rust baseline | 47 561 |
| Corrected integrated candidate | **44 139** |
| Saving | **3 422 (7.2 %)** |

This includes the generated audio and fo2 shader data in the complete checkpoint.
The objective is the whole packed EXE; individual savings are not additive.
On the same final PE, t14m7 produces 44 288 bytes and t15t produces 44 139.

The complete checkpoint reproduced the exact file from a fresh build, passed
32 transformation tests and the 208 770-byte assembly decoder roundtrip.
Its EXE SHA-256 is:

```
d59888ef0ef7bb1f737e755d96892f0537037118d172073806a5ce26e47cf458
```

That final file also passed the full media comparison: 27 000 frames, 510 raw
anchors, the whole PCM and 151 physics samples exact, with clean process exit.
Native Windows is untested. Detailed acquisition tools and reports are on
[`size/finish-integration`][research].

[buildable]: https://github.com/RovshanMuradov/eidolon-64k-rs/tree/7eb8cc3d6d15974521d67ebc9b1df7e4139601d0
[research]: https://github.com/RovshanMuradov/eidolon-64k-rs/tree/size/finish-integration/size
