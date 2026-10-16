# Rust conformance contract — T24

- [V] Owner: T24; implementation: [conformance.py](../tools/verify/rust/conformance.py); fault suite: [test_conformance.py](rust/test_conformance.py).
- [V] D22 permits the immutable native-reference1 harness before final G6; every successful CLI result is `OFFLINE_CONFORMANCE_ONLY`, `reference_accepted:false`, `production_accepted:false`.
- [V] Expected data comes from pinned T16 reference1, its hash-bound frame index, PCM, eligibility ledger, producer envelope, raw native state and ordered observation stream; no engine/audio implementation computes native expected words.
- [V] Native input pin, projected-vector hash and coverage: [native.json](../artifacts/verification/rust/native.json); retained-candidate pins/results: [partials.json](../artifacts/verification/rust/partials.json).
- [V] T22/T23 inputs are read with `git show` at fixed commits; mutable branch heads/worktree files are not an oracle.

## Commands

- [V] Native integrity: `bash tools/run python tools/verify/rust/conformance.py native` checks all27000 hashes,510 raw buffers, complete PCM, seven initial-state payloads and27000 observed time records.
- [V] Retained host diagnostics: `bash tools/run python tools/verify/rust/check_partials.py --result artifacts/verification/rust/partials.json`; only the hash-pinned Linux x86_64 ELF executes; PE inspection is file-only.
- [V] Fault suite: `bash tools/run python -m pytest tests/rust -q --basetemp /tmp/opencode/eidolon/T24-pytest`.
- [V] Individual checks: `conformance.py probe STREAM`, `shaders STREAM`, `identity EXE`, `pcm PCM --kind standalone-rust-diagnostic|hybrid-source-oracle-diagnostic`, `frames INDEX --payload-root DIRECTORY`, or `full-run MANIFEST`, each through `bash tools/run python tools/verify/rust/`.
- [V] Root overrides precede the operation: `--capture-root CHECKOUT --data-root DATA`; defaults select shared T16/reference1 only.
- [V] Exit0 means the requested offline operation passed within its declared coverage; exit1 means failed integrity/conformance; exit2 means CLI usage error.

## Native and derived vector coverage

- [V] `EIDRAW01` and `EIDSTA01` follow T22's shared handoff:27000 ordered records, eight little-endian u32 header words `(n,cursor,seconds_bits,beat_bits,row,local_beat_bits,dt_bits,uniform_count)`, then `(name_index,components,component_words...)`; state records append64 u32 words; no footer/padding.
- [V] Native observed checks compare every cursor, seconds bit-pattern and local-beat bit-pattern; row attribution comes from reference1's independently reviewed50-row scene partition, including adjacent rows sharing a token.
- [V] Native ordered-stream projection is27000 little-endian `<5I` tuples `(n,cursor,seconds_bits,local_beat_bits,scene_token)`; decoded and compressed stream hashes are checked before trusting it.
- [V] Native frame-zero physics is exactly256 bytes from `native-first-query-physics.bin`; all seven initial-state dumps are available for future candidate serialization in native layout.
- [V] Beat and dt checks are explicitly derived f32 models; `delta_f32_bits` in the native scene event is not treated as an authenticated dt oracle.
- [?] Reference1 does not supply independently authenticated post-update physics/curve-uniform vectors throughout the run; later state records and uniform values are structurally parsed but not certified.
- [V] Shader stream `EIDGLS01` compares31 programs/235 NUL-terminated source-array elements directly with hash-bound effective native shader files; loading program appears last in the probe ABI.
- [V] Host-probe agreement establishes neither Windows x86 numeric behavior nor graphics linking/pass output; hybrid PCM agreement establishes no standalone Rust synthesizer.

## Candidate file envelope

- [V] JSON rejects duplicate/unknown/missing fields and non-finite numbers; exact comparisons distinguish booleans, integers and floats; payload paths are relative POSIX paths with no traversal or symlink escape.
- [V] Every file binding is exactly `{path,sha256}`, relative to the candidate manifest directory; the verifier rehashes every binding, including executable, input inventory, capture tool and observation files.
- [V] Top-level fields are exactly `schema,kind,reference_sha256,executable,inputs,runtime,video,frames,audio,pcm,pcm_completion,state,completion,endpoint,observations`.
- [V] `schema="eidolon-rust-candidate-1"`; `kind="production-rust-capture"`; `reference_sha256` equals the independently pinned native-reference1 manifest; diagnostic/hybrid kinds cannot enter full-run checking.
- [V] `executable` binds the shipped PE32 i386 file; `inputs` is a nonempty stable-name→binding build/dependency inventory; the checker reports actual PE imports, size and hash.
- [V] `runtime` is exactly `{environment,exe_before_sha256,exe_after_sha256,command,capture_tool}`; environment equals native-reference1's environment object; both executable observations equal the bound shipped file; command is a nonempty argv array and capture_tool is a file binding.
- [V] `video` equals reference1.video excluding `index,index_sha256,storage`; `frames` binds a27000-line index with the exact reference-format fields/timing and every hash, including alpha; retained raw pointers must cover all510 native periodic/row-edge anchors.
- [V] `audio` equals reference1.audio excluding `path,sha256`; `pcm` binds all159716352 bytes, including the956352-byte tail; comparison reads both files and reports the first differing byte.
- [V] `pcm_completion` is exactly `{rendered_sample_frames:19964544,submitted_bytes:159716352,stable_sha256,events}`; stable hash equals native PCM; events has positive strictly increasing integer IDs `render_complete,readback_begin,readback_end,stability_check` in one observation order.
- [V] `state` maps exactly `entry/physics,entry/rng,entry/tick,prethread/rng,prethread/tick,first-query/physics,first-query/previous-seconds` to raw native-layout bindings; every byte must match the corresponding observed native initialization phase.
- [V] `completion` is exactly `{finalized:true,frames_observed:27000,frames_hashed:27000,audio_sample_frames:19964544,dropped_frames:0,dropped_audio_sample_frames:0,errors:[]}`.
- [V] `endpoint` is exactly `{reason:"natural_exit",exit_code:0,queries:27001,frames:27000,last_present:26999,terminal_cursor:19845000,wrapper_stop:false}`; timeout, truncated run, extra present and manual wrapper stop fail.
- [V] `observations` is exactly `{identity,clock,state,pcm_completion,endpoint}` of nonempty hash-bound files; these are mandatory runtime-review inputs, not self-authenticating assertions.

## Production acceptance gate

- [?] Full candidate envelope success remains file conformance until independently reviewed capture sources/ordered observations establish actual executable identity, fresh state, pre-present readback, complete synthesis/source-memory stability, advancing clocks and natural termination.
- [?] Production acceptance additionally requires final G6, the complete shipped audiovisual EXE, reproducible builds, Windows target execution, exact all-frame/PCM comparison, runtime fault controls and measured startup/runtime/memory/size baselines.
- [V] Missing native post-update vectors remain explicit; no tolerance, alignment, frame deletion, PCM trimming, normalization or model-as-native substitution is authorized.
