# Integrated size result

The frozen candidate is **44,139 bytes** (43.10 KiB): **3,422 bytes / 7.2%**
smaller than the previous 47,561-byte build, and **16,789 bytes / 27.6%**
smaller than the 60,928-byte original. Its complete SHA-256 is:

```
d59888ef0ef7bb1f737e755d96892f0537037118d172073806a5ce26e47cf458
```

This is the smallest retained corrected build from the bounded search, not a
claim of a globally optimal executable. Final packed-image capture is pending.

## Completed integration

| Work | Result |
|---|---|
| Packer | Recovered t15t encoder/decoder, shared generated model configuration, checked stream-size limit and decoder roundtrip |
| Layout | Content-derived anonymous sections before linking, exact membership/digest checks, four seeds and 64 measured proposals |
| Rust/audio | Reproducible patch/score/formant generation, DSP/backend tuning, restored public bounds checks and conservative post-link FP-load redirection |
| Graphics | Frozen fo2 pool with committed fragments/recipes, deterministic reconstruction, binding-aware fail-closed checker |
| Verification | Packed-image observer with pinned external references and strict media, restoration, endpoint and process-closure checks |
| Build | Isolated candidate mode, input/tool identities, paired layout overrides and watched linker inputs |

Recovery and reconstruction use repository-owned inputs. Historical scratch
directories are unnecessary for the normal build. The external reference
archive is required only for independent full-media verification.

The earlier 44,101-byte exploratory EXE passed a full media capture, but used
the old constant-erasure heuristic. Its generic safety flaw was reproduced
with a live indexed table. The retained pass redirects proven immutable reads
without erasing any constant copies; the final build also restores public
audio extent checks. Those correctness changes take precedence over the
38-byte difference from that exploratory result.

## Reproduction and source checks

An independent, clean checkout of `dbefed39ce3083be25f7699fec46d400c4755991`
at a different path rebuilt the EXE byte for byte. Both the Rust target cache
and NASM build directory started empty; only the pinned toolchain/dependency
cache and hash-verified NASM source archive were reused.

- Rust 1.97.1, Clang 22.1.8, MinGW-w64 GCC 16.2.0, NASM 2.10.09, Wine 11.17.
- All generated-input checks and **34 transformation tests** passed in that
  checkout: six PE-merger, eight layout/model, and 20 shader-validation tests.
- The regular Rust suite's **five tests** also passed after source integration.
- Full host PCM matched all **19,964,544 stereo frames / 159,716,352 bytes**;
  SHA-256 `9b1aa5f18aea89e27415ce82bd142b2e66bab3adaa7db4eab64f119fd33e631d`.
- The final decoder roundtrip reproduced **208,770 bytes**; damaged-stream
  rejection and observer-signature checks passed.
- Shader reconstruction preserved all 12 tables. Unmodified glslang compilation
  and binding-aware comparison passed 30 programs. Program 21 fails baseline
  compilation too and remains explicitly `UNSUPPORTED` (overall exit 2), not
  a successful shader check. Runtime media verification is a separate check.

The clean-rebuild attestation is
[`reports/d59888ef…-rebuild.json`](reports/d59888ef0ef7bb1f737e755d96892f0537037118d172073806a5ce26e47cf458-rebuild.json).
The linked, postprocessed PE is 172,544 bytes, SHA-256
`f448f284e1400dc10b145e0b3893b96954ac7e4b8b5b781a534cb8ce41020dd2`.

## Complete-executable comparison

Both packers received the same corrected linked input and final layout:

| Model | Delivered bytes | SHA-256 |
|---|---:|---|
| t14m7 | 44,288 | `50ca1a3569dfa2b4f18a8e9b6effeb0b24a2855a4a8e811d30c744a06133a441` |
| **t15t** | **44,139** | `d59888ef0ef7bb1f737e755d96892f0537037118d172073806a5ce26e47cf458` |

t15t saves **149 bytes**. These are complete trimmed files, not shader-pool or
compressed-stream estimates. See the
[matrix identities](reports/final-model-comparison.json) and
[bounded layout search](INTEGRATED-LAYOUT.md).

## Final runtime evidence

Independent full capture and controlled runtime/resource measurements of the
44,139-byte file are pending. Native Windows execution is untested.
The 44,101-byte exploratory capture is documented separately under
[`verify/reports/`](verify/reports/README.md).
