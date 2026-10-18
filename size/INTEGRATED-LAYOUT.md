# Frozen integrated layout

The current `size/crate/tools/rust/lay2.json` and `sizecoded.ld` freeze the
corrected CODE + FO2 + t15t input merged at `a44ba9b`. Membership is 60 retained
text sections, 70 read-only sections (65 anonymous), and one known discarded
`rust_eh_personality` section. The final map confirms that discard.

Four explicitly migrated seeds measured 44,186 / 44,179 / 44,145 / 44,208
bytes. A single-worker search with seed 20261018 evaluated exactly 64 insertion
proposals (48 text, 16 read-only), in 335.734 seconds. The best result is
**44,139 bytes**, SHA-256
`d59888ef0ef7bb1f737e755d96892f0537037118d172073806a5ce26e47cf458`.
It is 38 bytes above the suggested 44,101 target; the safe constant pass and
restored audio checks are retained. No constant copies are erased.

`layout-provenance.json` records the seed results, accepted moves, and final
EXE/input/layout fingerprints. The unprepared PE means the linked image after
safe constant redirection, before clearing exports and unused PE contents.
Its SHA-256 is
`f448f284e1400dc10b145e0b3893b96954ac7e4b8b5b781a534cb8ce41020dd2`
(172,544 bytes). These are candidate fingerprints, not media acceptance.

## Rebuild

With the pinned Rust/tool environment on `PATH`, from the repository root:

```sh
python3 size/build.py --candidate
python3 size/packer/check.py --input .build/size/input.exe \
  --packer .build/size/packer/kkrunchy.exe
python3 -m unittest discover -s tests -p test_size_layout.py -v
python3 -m unittest discover -s size/tests -p test_merge_constants.py -v
```

The delivered EXE is `.build/eidolon-size.exe`; `.build/size/unprepared.exe`
and `.build/size/build.json` record the pre-packer image and actual staged
inputs. Omitting `--candidate` continues to enforce `size/expected.sha256`.
No saved objects, research packer, seed artifact, or tuning run is required
to reproduce the frozen result. GPU/media acceptance is a separate step.

## Explicit membership changes and candidate pairs

On new code/data, normal linking must fail rather than silently keeping a
stale order. Capture the rejected input without relaxing that guard:

```sh
EIDOLON_SAVE_LINK="$PWD/.build/link-capture" python3 size/build.py --candidate
```

The self-contained `.build/link-capture/unrenamed/` snapshot includes the
original runtime COFF, libraries, `runtime.def`, link arguments, and validation
error. Successful links also save a validated, renamed snapshot in the parent
capture directory. The original rustc output basename is preserved on replay,
because the GNU linker writes it into `.edata`.

Explicitly migrate a seed (JSON arrays of exact names, globs, or `*(...)` lines):

```sh
python3 size/crate/tools/rust/layout.py --migrate-order OLD-ORDER.json \
  --object RUNTIME.o --output-dir .build/new-layout
python3 size/build.py --candidate \
  --link-order .build/new-layout/sizecoded.ld \
  --layout-manifest .build/new-layout/lay2.json
```

Migration reports removed/added members, rejects ambiguous matches, and
appends new members in object order. Mark members discarded only with link-map
evidence. Both override files are mandatory and must agree; the normal
one-to-one membership and full anonymous digest checks still run. Cargo's
`build.rs` watches the entire `tools/rust` directory and `EIDOLON_SAVE_LINK`,
so changing these inputs forces relinking without deleting the target cache.

`size/tools/retune_layout.py` can replay an unrenamed snapshot using a
source-built packer. Its enforced limits are four seeds, 64 proposals, and
540 seconds between measurements, with one worker and actual trimmed-size
scoring. It writes a best manifest/script pair without changing repository
inputs. This phase's products and full search trace were kept in
`.build/phase2/search`.
