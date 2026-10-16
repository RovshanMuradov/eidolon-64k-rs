# Draft reference contract

- [V] Owner: Verification/T13; assignment: [briefs/T13.md](../briefs/T13.md).
- [H] Schema `eidolon-reference-draft-3` remains provisional pending producer agreement and live capture validation; D9 experiment provenance is specified separately below.
- [V] Acceptance target: [approved step 1](../GOAL.md#approved-step-1--reproducible-reference-of-the-original).
- [V] Executable checker: [tools/verify/reference.py](../tools/verify/reference.py); synthetic fixture: [reference_factory.py](reference_factory.py).
- [H] A `PASS` under this draft reports only the requested integrity/comparison operation; synthetic captures establish neither an original reference nor original repeatability.

## Files and types

- [H] Each run has a UTF-8 JSON manifest and a UTF-8 JSONL frame index; manifests/indexes are small Git artifacts, while PCM and `.raw.zst` files live under `$EIDOLON_DATA/reference/<run>/`.
- [H] Index and PCM-completion evidence paths resolve relative to the manifest; PCM/raw paths resolve relative to the CLI data root, defaulting to the manifest directory.
- [H] Payload paths use relative POSIX components; absolute paths, `.`/`..`, backslashes, missing files, and symlink escapes fail.
- [H] Objects accept exactly the fields below; duplicate keys, non-finite numbers, missing fields, and unknown fields fail.
- [H] Counts/ticks are JSON integers, never booleans or floats; hashes are lowercase 64-character SHA-256; descriptive strings are nonempty.
- [H] Capture publishes the final manifest only after all payloads and the index are closed successfully; its completion counters are independently checked for consistency.

## Manifest

- [H] `schema`: exactly `eidolon-reference-draft-3`; earlier drafts fail validation and require an explicit producer update with observed PCM-completion evidence, never fabricated defaults.
- [H] `run_id`: a unique identifier for a separate invocation; comparing the same ID or manifest is a failure.
- [H] `source`: `{kind, exe_sha256, inputs}`; `kind` is `original` or `synthetic`; `inputs` maps every other input's stable name to its hash, including the source archive and hook/shim build inputs.
- [H] `source.exe_sha256` for `original` must equal the approved native EXE hash in `GOAL.md`; synthetic inputs must be labeled `synthetic`.
- [H] `capture`: `{kind, tool_sha256, command}`; `kind` is `controlled-reference` for originals or `synthetic-reference` for synthetic fixtures; `compatibility-smoke` is rejected.
- [H] `capture.tool_sha256` hashes the complete capture implementation bundle, including `tools/wine-headless` and hooks/shims; `command` is the exact nonempty argument array used to reproduce the capture.
- [H] `conditions`: `{environment, settings, clock, rng, initial_state_sha256}`; `settings` records every capture/demo setting as a JSON object.
- [H] `conditions.environment`: `{os, arch, wine, gpu, driver, graphics_api, gamescope, display}`; all fields except `display` are nonempty pinned version/identity strings, including the gamescope version.
- [H] `conditions.environment.display`: exactly `{kind:"gamescope-headless", width:1920, height:1080, launcher:"tools/wine-headless", wine_virtual_desktop:false}`; dimensions are integer pixels and the flag is a JSON boolean.
- [V] Display semantics require an invisible gamescope headless display with no Wine virtual desktop or user-screen window; dimensions describe that display, not the captured final buffer ([approved display](../GOAL.md#approved-step-1--reproducible-reference-of-the-original)).
- [H] `conditions.clock`: `{numerator:1, denominator:60, method}`; `method` identifies how the clock and audio position fed to the demo are controlled.
- [H] `conditions.rng`: `{method, initial_state_sha256}`; identify RNG initialization/control and hash its initial-state serialization.
- [H] `conditions.initial_state_sha256`: hash the stable initial-state specification, including Wine-prefix baseline, initial resources and process/FP settings affecting output; record the prefix initialization recipe and hook/build identifiers in `conditions.settings`.
- [H] `video`: `{width, height, row_stride, pixel_format, row_order, color_space, frame_count, index, index_sha256, storage}`.
- [H] `video.width`/`height` are positive final-buffer dimensions, independently recorded from `conditions.environment.display`; `row_stride = width * 4` bytes.
- [H] `video.pixel_format` is `rgba8` or `bgra8`; `row_order` is `top-down` or `bottom-up`; `color_space` names the actual interpretation without applying a conversion.
- [H] `video.frame_count = N > 0`; `index_sha256` hashes the exact index file bytes, including newlines; `storage` is `reference` or `hashes`.
- [H] `audio`: `{path, sha256, sample_format, sample_rate, channels, layout, sample_frames, start_sample}`.
- [H] Synthetic `audio.sample_format` is `s16le`, `s24le`, `s32le`, `f32le`, or `f64le`; `sample_rate > 0` is in Hz; `channels` is a nonempty ordered array of unique channel labels; `layout` is `interleaved`.
- [H] `audio.start_sample = 0`; `sample_frames = A > 0` counts multichannel instants, not scalar samples; file length is exactly `A * len(channels) * bytes_per_sample`.
- [H] `audio.sha256` hashes the entire headerless, complete submitted PCM file, including the tail beyond the final visual cursor; trimming, resampling, normalizing or adding silence fails.
- [H] `scenes`: ordered nonempty array of `{id, first, last}` with unique IDs and inclusive frame bounds partitioning `0..N-1` exactly; boundaries come from T1's timeline.
- [H] `termination`: `{reason, end_tick, audio_position, audio_position_num, audio_position_den, exit_code, timeline_end_tick, evidence}` with visual `end_tick=N` and `audio_position=floor(N*sample_rate/60) <= A`; this cursor does not define complete audio length.
- [H] The terminal ideal sample position is the exact rational `audio_position_num=N*sample_rate`, `audio_position_den=60`; retain the fractional phase even when the native integer cursor is rounded down.
- [H] Natural termination requires `reason=natural_exit`, `exit_code=0`, `timeline_end_tick=null`, and evidence identifying the observed process-exit event.
- [H] Timeline termination requires `reason=timeline_end`, `timeline_end_tick=N`, `exit_code=null`, and evidence identifying T1's established exclusive timeline endpoint.
- [H] `termination.evidence` is a stable semantic event label shared by equal runs; retain PID/TID, wall times and observation-file locations in separate runtime evidence; exact termination-object comparison remains required.
- [H] `completion`: `{finalized:true, frames_observed:N, frames_hashed:N, audio_sample_frames:A, dropped_frames:0, dropped_audio_sample_frames:0, errors:[], pcm}`; `pcm` follows the final-data requirements below.
- [H] Timeout, crash, manual abort, capture errors, partial manifests, loss counters, zero-length runs, or inconsistent end/count fields fail even when both inputs share the defect.

## Native extent and final-data evidence

- [V] Source: `$EIDOLON_ROOT/handoff/reverse-to-capture-hooks.md`, sections PCM extent and completion / Clock and termination; T1's saved-code/trace reconciliation distinguishes observed values from predicted live cursor state.
- [V] Original PCM layout is `f32le`, 44100 Hz, channels `["L","R"]`, interleaved; WAVEHDR submits exactly 19964544 sample frames / 159716352 bytes / 452.7107482993 seconds.
- [V] The synthesis tick starts at 1 and ends at 19964545; the delta, not the final raw tick, equals the submitted sample-frame count.
- [V] The visual timeline ends at beat 600 / 450 seconds / sample position 19845000; submitted PCM retains a tail of 119544 sample frames / 956352 bytes.
- [H] Full original manifests must independently satisfy those native PCM constants and `video.frame_count=termination.end_tick=27000`, derived from the verified visual endpoint and approved 60 Hz clock; controlled frames `0..26999` and end check `27000` still require live confirmation.
- [H] A short real capture is an integration diagnostic, not a passing full reference; differing live results require investigation, not adapting these criteria to the capture.
- [H] `completion.pcm`: exactly `{submitted_bytes, initial_tick, final_tick, final_cursor_offset, events, stable_sha256, evidence, evidence_sha256}`.
- [H] `submitted_bytes` equals the complete PCM byte length; `final_tick-initial_tick=A`; original `initial_tick=1`; each field is a nonnegative integer.
- [H] `final_cursor_offset` is the observed synthesis write cursor minus the submitted buffer base, in bytes, and must equal `submitted_bytes`; record the original's `[EBP+8]` at completion, not epilogue EDI or thread-return EAX.
- [H] `events`: exactly `{synth_complete, readback_begin, readback_end, stability_check}`, with strictly increasing positive integer sequence numbers in one per-run, cross-thread ordered observation stream; event IDs are not visual ticks or wall-clock timings.
- [H] `synth_complete` identifies execution after the final stores, deferred frees and FP restoration, established at original VA `0x401765`; successful submission, WAVEHDR playback completion and thread-return status do not substitute for this event.
- [H] `readback_begin`/`readback_end` bracket acquisition of the entire submitted range after synthesis completion; `stability_check` marks a later, separate full-range memory hash while the source buffer remains valid.
- [H] `stable_sha256` equals `audio.sha256`; neither a second hash of the saved file nor a copy of its declared hash establishes source-buffer stability.
- [H] `evidence` names a nonempty observation artifact; `evidence_sha256` hashes its exact bytes; the verifier checks presence/hash independently for each run.
- [H] The evidence artifact must identify its run, source/dependency identity, synthesis thread and completion location, submitted pointer/length, initial/final ticks, observed final cursor, event ordering and both full-range acquisition/stability hashes; include capture loss/error observations and retain the producer's observation format/tool identity.
- [H] Runtime evidence review must establish actual final cursor, full-range coverage, cross-thread ordering and later immutability; metadata consistency and a hash-bound artifact alone cannot authenticate producer claims.
- [V] Immutable B provides observed final-cursor/acquisition/stability diagnostics; independent assessment and remaining acceptance limitations: [B diagnostic assessment](#b-diagnostic-assessment).

## Frames and time

- [H] The index has exactly one object per line for every `n=0..N-1`, in order, with `{n, tick, clock_tick, audio_position, audio_position_num, audio_position_den, sha256}` and optional `raw_zst`.
- [H] `tick=n` means frame presentation at exactly `n/60` seconds; `clock_tick=n` records the controlled clock supplied for that render; `audio_position=floor(n*sample_rate/60)` is the supplied PCM cursor in sample frames.
- [H] Record the ideal cursor as unreduced `audio_position_num=n*sample_rate`, `audio_position_den=60`; this preserves fractional-sample timing independently of the native integer cursor.
- [H] Frame `n` is the final buffer immediately before its present, after rendering with clock `n/60` and the corresponding controlled audio position; readback must complete before the buffer is reused.
- [H] The exclusive visual endpoint is `N/60` seconds; complete PCM duration is `A/sample_rate` seconds; use integer arithmetic for audio positions, including sample rates not divisible by 60.
- [H] `sha256` covers exactly `row_stride * height` final pixel-buffer bytes, including alpha; preserve channel order, row order and numeric values without gamma correction, flipping, quantization or perceptual metrics.
- [H] `raw_zst` names one complete Zstandard frame containing those same bytes; decompression must reach end-of-frame with no trailing/concatenated data, match the exact byte length, and reproduce the frame hash.
- [H] The `reference` run must store frame `0`, every frame divisible by `60`, and the first/last frame of every scene; extra explicitly listed recapture frames are checked identically.
- [H] A `hashes` run stores every frame hash and the full PCM but no `raw_zst` pointers; one run supplies the sparse reference pixels.

## Exact comparisons

- [H] Validate each run independently before comparing; matching malformed inputs cannot pass.
- [H] Compare `source`, `conditions`, `scenes`, `termination`, capture-tool hash, video layout/count, and PCM layout/count exactly.
- [H] Compare every frame record exactly except its storage pointer; missing, reordered, duplicated, extra or shifted records fail.
- [H] Compare the full PCM files byte-for-byte after each file independently passes its declared hash and size; report the first differing byte offset.
- [H] Frame comparison uses SHA-256 for all final buffers and rehashes every stored raw frame; unsaved pixel buffers require re-capture from the original to inspect a mismatch.
- [H] Run IDs, capture-command arguments, file locations, storage mode and index-file hashes need not agree across runs; commands may differ in output paths, while behavioral settings must agree in `conditions`.
- [H] PCM evidence paths/hashes and event sequence numbers are run-specific and need not agree; each run independently passes all final-data invariants and matches its entire PCM to its stability hash.
- [H] No tolerance, time alignment, dropped prefix/suffix, frame deduplication, image conversion or audio normalization is permitted.
- [H] Source/tool/state hashes, display metadata, end-event evidence and PCM observation artifacts do not by themselves prove runtime behavior; headless execution, capture-point correctness and a full natural end require independent runtime validation.
- [V] Native PCM extent/layout and the derived visual endpoint are checked independently of pair equality; identically trimmed native pairs with rewritten hashes/counts/termination cannot pass ([test_reference.py](test_reference.py)).
- [H] Consistently forged full-length bytes, event histories or synthetic endpoints cannot be disproved from self-declarations alone; independent runtime evidence remains necessary.

## Capture feedback reconciliation

- [V] Proposal: `$EIDOLON_ROOT/handoff/capture-to-verification-format.md`; response: `$EIDOLON_ROOT/handoff/verification-to-capture-format.md`.
- [V] T4's completion-gated full submitted extent, one-based synthesis tick, exact integer/rational cursors, pre-present ordering and retained tail agree with this contract; draft-3 adds mandatory machine-checked final-data proof beyond draft-2's counters.
- [H] Native pixel/PCM layout is constant per run and lives once in `video`/`audio`; `pixel_format` specifies byte channel order and unsigned 8-bit components, while `sample_format` specifies scalar type and byte order.
- [H] Sparse compression is defined by `raw_zst`; raw length and hash are derived from video layout and the frame record, while mandatory selection reasons follow frame numbers and scene bounds without duplicate fields.
- [H] PCM byte length, rational cursor phase, completion proof and pre-present ordering follow the definitions above; native constants come from T1 evidence, independently of either compared payload.
- [H] G5 small-capture review uses a clearly labeled partial diagnostic bundle: observed native layout, sequential frame records including frame zero and scene-boundary samples, lossless raw buffers, complete PCM and completion evidence, and the actual stop event; preserve failure/partial state.
- [H] Review G5 pixels with `verify_raw` and PCM declarations/artifact with `verify_pcm_completion` in the independent checker, then verify whole PCM size/hash and clock observations; this is acquisition validation, not the full-run CLI `PASS` criterion.
- [H] `validate`/`compare` require full original extents and valid completion; diagnostic fragments must not rewrite source kind, scene/count/end fields or `finalized` to manufacture a pass.

## B diagnostic assessment

- [V] Immutable input: [canonical merged B manifest](../artifacts/reference/proxy-b-g1-20261016.json); [diagnostic_pcm.py](../tools/verify/diagnostic_pcm.py) pins its SHA-256, rehashes its three evidence files and six capture sources, and checks the original observation stream independently; the removed T2 worktree is not an input.
- [V] `completion_from_events` projects only observed PCM fields into `verify_pcm_completion`; it creates no reference manifest, frame records, successful termination or accepted-reference identity.
- [V] The source-pinned `core.c` reads `[EBP+8]` at `0x401765`, serializes event IDs under a critical section, waits for completion, writes the entire submitted range and separately hashes source memory twice; independent saved-file hashing agrees.
- [V] `hook_context` logs the same digest twice after a context comparison; this limited observation does not establish complete ABI/FP/state-preservation gates.
- [V] The manifest supplies run/source/dependency identity; `backend.jsonl` alone does not contain that envelope. New captures must publish self-identifying, hash-bound completion evidence under the existing draft-3 requirements.
- [V] Real PCM content statistics are descriptive; finite/nonzero values and peaks outside ±1 neither establish musical correctness nor authorize clipping, normalization or tolerance.
- [V] Diagnostic assessment returns `DIAGNOSTIC_ONLY`, `reference_accepted:false`, exit 0 for successfully checked diagnostics; changed/missing evidence returns `FAIL`, exit 1. Full-run `validate` rejects B.
- [V] `--corruptions` modifies disposable PCM copies, checks first/tail bytes, missing/short/extra data, the complete visual-tail trim and a one-sample-frame shift; refreshed hashes cannot defeat direct byte comparison. Completion-field faults also fail.
- [?] B contains zero real pre-present buffers and one frame-zero sample-cursor observation; final layout, raw pixels, scene anchors, advancing controlled clocks, visual completion, exact repeatability and outstanding G1–G4 evidence remain absent.

## D9 compatibility experiment eligibility

- [V] Authority: D9 in [STATE.md](../STATE.md); semantic basis: `$EIDOLON_ROOT/handoff/reverse-to-capture-glsl-compatibility.md`; independent file-only checker: [compatibility.py](../tools/verify/compatibility.py).
- [H] D9 authorizes a proxy-only experiment, not acceptance of a restored original; preserve native EXE/source memory, original failure artifacts and all exact PCM/frame/timing criteria.
- [V] D11 in [STATE.md](../STATE.md) permits D9's independently reviewed source-bound directive-only layer as a candidate reference environment, conditional on all remaining gates; it grants neither reference acceptance nor changed tolerances.
- [H] Contradictory semantic evidence rejects candidate eligibility and returns D9 fallback evaluation to the coordinator under its existing prerequisites before new comparisons; the authorized edits remain unchanged.
- [H] Keep candidates labeled `compatibility-modified-diagnostic`, `reference_eligible:false`; draft-3's `original` kind cannot describe runtime shader modifications, and the full-reference checker rejects modified kinds/diagnostic sidecars.
- [H] Successful provenance/edit checking returns `PROVENANCE_ONLY`, `runtime_semantics_verified:false`, `reference_accepted:false`; it establishes neither capture G5/G6 nor scene identity, even if a producer reports successful compilation.

### Provenance sidecar: `eidolon-d9-eligibility-1`

- [H] Exact top-level fields: `schema`, `kind`, `decision`, `run_id`, `reference_eligible`, `run_manifest`, `inputs`, `build`, `transformation`, `calls`, `fallback`; duplicate/unknown/missing fields fail.
- [H] `schema` is `eidolon-d9-eligibility-1`, `kind` is `compatibility-modified-diagnostic`, `decision` is `D9`, `reference_eligible` is false, and `run_id` is nonempty.
- [H] Each artifact binding is exactly `{root,path,sha256}`: `root` selects `checkout`, `shared` (`$EIDOLON_ROOT`) or `data` (`$EIDOLON_DATA`); `path` is root-relative POSIX with the existing traversal/symlink rules; exact bytes must rehash successfully.
- [H] `run_manifest` binds the unmodified producer manifest, whose `run_id` must agree and `reference_eligible` must be false; retain its actual stop/failure and environment observations, not synthesized draft-3 completion fields.
- [H] `inputs` is exactly `{exe,archive,bank,launcher}` of artifact bindings; native EXE/archive/bank identities are pinned independently in the checker to merged B's inputs; launcher bytes are bound and require independent review against `tools/wine-headless`.
- [H] `build` is exactly `{inputs,outputs,compiler,commands}`; `inputs`/`outputs` are nonempty name→artifact-binding maps; outputs require at least `opengl32.dll` and `winmm.dll`; compiler is a pinned identity/version string and commands are nonempty exact argv arrays.
- [H] Build coverage must include every source/build script, generated wrapper/export file, header, linker/compiler flag and backend dependency; bind immutable snapshots and actual loaded shim bytes. File hashing alone cannot establish that the build inventory is exhaustive or that the process loaded it.
- [H] The producer manifest must preserve GPU/driver/Wine/GL/GLSL/gamescope identities, approved display, full invocation/settings, dependency hashes, fresh prefix/RNG/resource/FP initial state and hash-bound raw observations; provenance checker does not certify these opaque runtime claims.
- [H] `transformation` is `450-compatibility` or `450-explicit-output-0`; primary `fallback` is null; explicit-output `fallback` is exactly `{failed_primary,routing}` of nonempty artifact bindings requiring semantic review, not automatically approved by their hashes.
- [H] `calls` is a nonempty complete ledger of `glCreateShaderProgramv` calls; each record is exactly `{sequence,stage,count,caller,return,source_addresses,input,forwarded,forward_calls,program}`.
- [H] `sequence` enumerates creations from 1 without gaps/duplicates/reordering; `stage`, `count`, `forward_calls` and returned `program` are integers, never booleans; `forward_calls` must be 1 and the actual returned handle is retained, not assumed to equal 2.
- [H] `caller`/`return` and every `source_addresses` entry use lowercase `0x` plus eight hex digits; source-address/input/forwarded arrays have exactly `count>0` entries; input/forwarded entries bind full source-string bytes excluding NUL in their original order.
- [V] Original creation PC `0x00406dcc` belongs to a 30-record loop over `0x4357e0..0x4358cf`; it is not a unique invocation. T12 checks original instruction/table bytes and all 235 raw strings against the unchanged unpacked image.
- [H] Select the target by creation PC `0x00406dcc` plus source address `0x00409918` anywhere in its array; require return `0x00406dce`, fragment stage `0x8b30`, count 1, exactly that source address, and the D7-pinned 1310-byte source. Zero/duplicate targets or fingerprint mismatches fail; every sibling array remains byte-identical even at the shared PC.
- [H] Primary replaces only `#version 450\n` with `#version 450 compatibility\n`, retaining all 1297 body bytes; fallback inserts `layout(location=0) out vec4 eidolon_FragColor;\n` after the original version line and replaces the sole `gl_FragColor` identifier; all unrelated arrays must remain byte-identical.
- [V] Candidate byte lengths/hashes independently agree with T1's [static review](../tools/reverse/review_glsl.py): 1324 bytes for primary, 1362 for fallback; test pins and malformed/edit/provenance faults are in [test_compatibility.py](test_compatibility.py).
- [H] Runtime review must establish ledger completeness, exact one-time forwarding and byte lifetime; a complete-looking declared ledger can omit runtime calls, and a refreshed hash cannot authorize an otherwise forbidden edit.

### Semantic prerequisites for later review

- [H] Fresh unchanged-source control on the pinned backend must reproduce D7 source/context, C7616, false link status and original-use `0x0502`; preserve original failure records.
- [H] Remedy evidence must establish every startup/later program's complete link log/status, returned handle, successful original use/expected current program, HDC/HGLRC/TID and clean error boundaries through initialization/acquisition; nonzero handles or successful swaps do not establish linking.
- [H] Verify stdcall/stack/register/MXCSR/x87 preservation, unchanged source memory, separately allocated NUL-terminated replacement lifetime and normal acquisition with diagnostic callbacks/breakpoints removed; copied context hashes are insufficient.
- [H] Observe first-pass FBO completeness, texture dimensions/internal format, draw-buffer map, viewport, masks, blend/clamp/sRGB and fixed-function vertex path; save the native-float 16384×128 atlas before upload into the 128³ RGBA32F volume with observed pack layout and complete extent.
- [H] Meaningful atlas variation, expected alpha=0 and downstream scene use are required diagnostics, not proof of historical scene identity; no normalization, clipping or visual-similarity tolerance is authorized.
- [H] Fallback requires a distinct failed-primary compile/link/use experiment and only output location 0 enabled at every actual use; static single-attachment tables or one sampled draw cannot establish all-use routing equivalence. A pixel mismatch is not permission to switch remedies.
- [H] Two fresh identical-state candidate runs must compare atlas, controlled pre-present pixels including alpha and complete PCM byte-for-byte; if both remedies execute, their atlas/final pixels must also agree exactly or the difference must be resolved before reference selection.
- [H] Real G5 acquisition review still requires actual final-buffer layout/read/draw bindings/components/samples/sRGB, sequential frame zero/advancing clocks, scene anchors, lossless raw buffers, run-specific PCM completion/stability evidence and actual stop state.
- [H] T13 performs staged G5 and full G6 acceptance after T11 supplies the remaining evidence; D11's conditional candidate permission does not admit a modified-source full-reference schema. Missing observations remain missing and cannot be inferred from static tables or a shader fix.
- [?] Historical driver/compiler output and author bank identity remain unknown; exact candidate agreement proves pinned compatibility-run agreement only.

## T12 saved short-capture assessment

- [V] Recheck: [review_short.py](../tools/verify/review_short.py) pins T11's control3/primary/repeat/boundary manifests and sidecars, rehashes evidence/build snapshots/shims/backends, reconstructs all ordered source arrays from original MOV initialization and the creation-loop table, and compares each raw string with the pinned unpacked image.
- [V] Startup creation 1 returns at `0x406442` with source `0x426c58`; creations 2–31 return at `0x406dce`. Creation 2 alone uses `0x409918`; creation 3 also has count 1 but source `0x409e38`. The checker correction removes only the disproven unique-callsite assumption.
- [V] Both real eligibility sidecars return `PROVENANCE_ONLY`: exactly one authorized directive replacement, 234 other source-array entries unchanged; source bytes, stage/count/address, actual returned handles and all 31 creation records reconcile with original roles and the saved stream.
- [V] Unchanged-source control3 preserves C7616, false link status and original-use `0x0502`; primary/repeat have 31 linked programs and clean recorded uses in the owning context. These observations cover only the captured execution prefix.
- [V] Primary/repeat match byte-for-byte for the 33554432-byte atlas, complete 159716352-byte PCM and all three 8294400-byte RGBA buffers; six Zstandard files independently reproduce their exact raw hashes. Atlas RGB has 2097152 distinct finite triples, range 0…0.9385188817977905, alpha zero.
- [V] Frame 0 is all-zero RGBA; frames 1/2 have 8/19 distinct RGBA tuples and constant alpha 1/2. These are acquisition/content observations, not scene-fidelity acceptance.
- [V] Each run's self-identifying PCM envelope reconciles with the hash-bound original stream: completion on the synthesis thread at `0x401765`, cursor delta 159716352, ticks 1→19964545, ordered whole-range acquisition and later source-memory hashing; primary/repeat retain the nonzero 119544-frame tail.
- [V] Pinned `proxy-b/core.c` guards default read/draw FBOs, 8-bit normalized RGBA components, zero samples, owning context, `GL_BACK` readback and state restoration before present. Events observe bottom-up 1920×1080, linear encoding, sRGB disabled and cursors 0/735/1470; they retain state digests rather than raw queried arrays.
- [V] Pinned compatibility wrapper forwards once with a separate NUL-terminated replacement alive until return and rehashes original target memory afterward. Primary/repeat sidecar `forward_calls=1` is source-derived; copied context/state digests do not establish independent complete ABI/FP canaries.
- [V] Boundary recovery preserves 67 successful presents, 67 hashes, raw frames 0/1/2/60, its own complete PCM and the actual supervisor timeout/native-exit-unknown state. Frame 60 has 16956 distinct RGBA tuples; the build differs from primary/repeat. This failed attempt establishes no scene boundary or endpoint.
- [V] T12's bounded diagnostic review/checker-correction task is complete under [briefs/T12.md](../briefs/T12.md), with verdict `DIAGNOSTIC_ONLY` and partial G5 acquisition findings; G1/G4, downstream volume/scene identity, full G5 and G6 remain open for T11/T13. Precise runtime prerequisites and producer metadata corrections are in `$EIDOLON_ROOT/handoff/verification-to-capture-format.md`.
- [V] [test_review_short.py](test_review_short.py) exercises the real shared-site ledger, missing/reordered/shifted frame records, changed alpha, invalid Zstandard extents, and first/tail/shifted PCM bytes including refreshed hashes; originals remain untouched.
- [H] The pinned review adapter understands both saved diagnostic envelope shapes; it does not ratify their inconsistent `eidolon-small-real-capture-diagnostic-1` fields as a new reference schema. Both partial and failed packages remain rejected by the full-reference checker.

## T13 independent staged assessment

- [V] [review_stage.py](../tools/verify/review_stage.py) pins T11's D11 boundary3/boundary-repeat manifests, version-2 diagnostic packages, eligibility sidecars and negative-control manifest; it imports only Verification primitives, never producer checks/packages. Verdict: `STAGED_G5_PARTIAL`, `full_duration_ready:false`, `reference_accepted:false`, G6 open.
- [V] Both saved streams independently reconcile all 1443 sequential pre-present/present records and exact integer/rational cursors; every frame hash agrees. All 62 retained Zstandard buffers rehash correctly, and direct comparison of 31 RGBA buffers plus the complete PCM and atlas establishes 33 byte-identical file pairs, including alpha and the 119544-sample-frame PCM tail.
- [V] Each run independently establishes its own completion location/thread/cursor, ordered full-range PCM acquisition and later memory-stability observations through the existing draft-3 proof checker. A planned partial exit 0 after frame 1442 remains partial; both packages are rejected by full-reference validation.
- [V] All 1443 independent pre-read/post-restore arrays establish default read/draw FBOs, `GL_BACK`, no PBO, eight pack parameters, four 8-bit normalized channels, zero samples and sRGB disabled; recomputed array hashes match the pre-present evidence. All recorded program uses retain the owning HDC/HGLRC/TID and clean errors.
- [V] Startup ticks 0…1000 and two repeated queries per timeline frame independently match epoch 1001 ms, `floor(1000*n/60)` milliseconds, QPC `60060000+1000000*n`, QPF 60000000 and PCM cursor `735*n`; no frame advancement occurs during repeated queries.
- [V] All 235 original source strings and all 31 creation roles reconcile with the unchanged image; exactly one authorized directive replacement occurs, every program links and both eligibility checks return `PROVENANCE_ONLY`. The unchanged-source control retains C7616/link=false/original-use `0x0502`.
- [V] Both atlases contain 2097152 distinct finite RGB triples, range 0…0.9385188817977905, alpha zero; the complete 33554432-byte source is observed at the 128³ RGBA32F texture-16 upload. None of 27417 scene-pass observations per run has an active `uClouds` location; upload/binding does not establish sampling.
- [V] Pinned build/source/generated-wrapper/backend/staged-shim bytes, in-process loaded-module file hashes, host runner and all 1875 baseline inventory entries rehash. The runner independently checks the copied fresh prefix before invocation; bootstrap x87 control word `0x027f` and MXCSR `0x1f80` agree across runs.
- [V] Raw PUSHAD/PUSHFD/FXSAVE pairs independently validate 16 first returned-wrapper invocations: preserved GPR/EFLAGS, actual RET argument cleanup, EAX and all 512 FP/SIMD bytes. Source-enforced per-wrapper counters total 626647 returns per run; only the first successful return per invoked wrapper has retained raw snapshots, not 626647 independent raw pairs.
- [V] Static inspection of pinned `compat.S`, `stage.c:54–97` and `objdump -d <build>/opengl32.dll` confirms the first snapshot precedes the core and the second follows the wrapper's executed `ret imm16`, through `_stage_return`. This validates the tested wrapper boundary, not native semantics or exception resumption.
- [V] The saved 716-byte bootstrap and completion CONTEXT pairs match exactly; completion's permitted EIP rewind is explicit. These snapshots are taken inside exception handling, before physical resumed execution; they do not observe completion's displaced epilogue/native return. Resolver wrapper ID 10 has zero calls; ID 17 is unused counter capacity, not a missing implemented hook.
- [V] All 12 hash-bound live rejection controls independently reconcile injection/failure ordering, native exit 125 and zero accepted frames; the wrong-thread control uses a distinct actual thread. Fingerprint rejection is forced by an environment guard; the backend controls exercise canary executables. Coverage is these recorded faults/routes, not arbitrary exceptions or live GPR/FP corruption.
- [V] [test_review_stage.py](test_review_stage.py) independently corrupts boundary frame order/time, QPC, restoration, GPR/EFLAGS/stack/EAX/x87/MXCSR/XMM, exception CONTEXT, alpha/Zstandard, atlas and full PCM including its tail; refreshed payload hashes cannot defeat direct pair comparison. These offline faults validate the verifier, not unperformed live canary injections.
- [V] T14's `$EIDOLON_ROOT/handoff/reverse-to-capture-gate-confirmation.md` and file-only `tools/reverse/confirm_capture_gate.py` independently reconcile all 1443 native seconds/local-beat/token triples in each run. T13 re-ran that checker: `TECHNICAL_CONFIRMATION_ONLY`. Frame 1440 selects row 1 at 24 seconds/beat 32 with local beat zero; rows 0/1 legitimately share token 0 and final program 20. This closes the first-boundary interpretation, not endpoint observation.
- [V] T14 establishes seed `[1,0,31337,0]`, global RNG `0x0b16b810`, node-local state `ESI+0x190`, native zero-initialized allocations, internal synth MXCSR `0xffc0`, persistent physics and successive audio-derived dt. T11's initial resource digest excludes mutable RNG/node/physics allocations and RNG constants `0x4090b8..0x4090c7`; matching PCM and completion FP do not independently attest those initial/interior states.
- [?] G1 still needs independently observed exception resumption/displaced epilogue/return preservation and coverage or a justified unreachable-route disposition for GetProcAddress ID 10, including name/ordinal routing. ID 17 requires no probe because no wrapper implements it.
- [H] Close explicit state evidence with unchanged pre-CreateThread bytes `0x0b16b800..0x0b16bd1f`, separate tick/main-thread FP, synth FP at `0x40166a` after native `ldmxcsr`, and the four physics records at native entry/first timeline query; exclude allocation-pointer slots beyond the tick. T14's handoff specifies optional node-stream attribution. Compare fresh runs, preserving native initialization and every intervening frame.
- [H] T14 locates the first actual cloud-capable consumer at frame 5760/beat 128/row 6, program index 20 (linked handle 22). Next bounded semantic probe is two sequential 5763-frame runs, raws 5758…5762 plus periodic/row-edge retention, observed active sampler/texture/filter/wrap/level/FBO/uniform state, full 3D texture readback matched to atlas bytes, and exact pass/final pixels. The program's bound unit at presentation alone is insufficient.
- [?] The modified-source full-reference schema and full-duration runner remain unimplemented; coordinator authorization/candidate selection is separate from these technical gaps. Preserve D9/D11 labels and zero tolerance until an explicit accepted contract exists.
- [H] Full G6 requires two fresh identical-state executions of frames 0…26999, evidenced exclusive endpoint 27000, all frame hashes, sparse raws every 60th plus every scene's first/last frame, complete PCM/tail, run-specific completion proof, exact comparison and deliberate-fault rejection. Later-scene timing/logging/storage must be budgeted under 30 GB; a partial exit is never the endpoint.

## Commands

- [H] Single-run integrity: `bash tools/run python tools/verify/reference.py validate <manifest> --data-root <run-data>`.
- [H] Independent run comparison: `bash tools/run python tools/verify/reference.py compare <reference-manifest> <repeat-manifest> --reference-data <reference-data> --candidate-data <repeat-data>`.
- [H] JSON output contains `status: PASS|FAIL`, `draft:true`, `source_kinds`, operation and failure reasons; exit status is `0` for PASS, `1` for FAIL, `2` for CLI usage errors.
- [V] Tool versions: Python 3.14.7, pytest 9.1.1, NumPy 2.5.4, Zstandard 0.25.0; check with `bash tools/run python -c 'import sys,pytest,numpy,zstandard; print(sys.version,pytest.__version__,numpy.__version__,zstandard.__version__)'`.
- [V] Temporary-parent prerequisite: `bash tools/run python -c "from pathlib import Path; Path('/tmp/opencode/eidolon/T10').mkdir(parents=True, exist_ok=True)"`; pytest requires the parent before `--basetemp` initialization.
- [V] Regression command: `bash tools/run python -m pytest tests/test_reference.py tests/test_diagnostic_pcm.py tests/test_compatibility.py --basetemp /tmp/opencode/eidolon/T10/pytest -q`; real-input tests require merged manifests and immutable shared assets and fail if these are absent; result: [reports/03-tests.md](../reports/03-tests.md).
- [V] B acquisition/corruption command: `bash tools/run python tools/verify/diagnostic_pcm.py artifacts/reference/proxy-b-g1-20261016.json --corruptions`; data root defaults to `$EIDOLON_DATA`, source root to the manifest's checkout.
- [V] D7 saved-evidence recheck: `bash tools/run python tools/reverse/review_glsl.py` → four manifests, four compressed evidence files, producer sources and source/dump equality; no target/GPU execution.
- [H] D9 sidecar check: `bash tools/run python tools/verify/compatibility.py <sidecar.json>`; roots default to the checker's checkout and shared environment, with explicit `--checkout-root`, `--shared-root`, `--data-root` overrides; exit 0 means `PROVENANCE_ONLY`, exit 1 means `FAIL`, never reference acceptance.
- [V] T12 file-only review from its worktree: `bash tools/run python tools/verify/review_short.py --capture-root ../T11` → `DIAGNOSTIC_ONLY`, partial G5, G6 open; omit `--capture-root` once T11's artifacts/tools are merged into the invoking checkout.
- [V] T12 regressions: `bash tools/run env EIDOLON_CAPTURE_ROOT=../T11 python -m pytest tests/test_reference.py tests/test_diagnostic_pcm.py tests/test_compatibility.py tests/test_review_short.py --basetemp /tmp/opencode/eidolon/T12/pytest -q` → 215 passed, zero skips; omit the environment override when T11 inputs are merged locally.
- [V] T13 stage review: `bash tools/run python tools/verify/review_stage.py --capture-root ../T11` → `STAGED_G5_PARTIAL`; immutable saved-data checks only, no GPU/target execution.
- [V] T13 regressions: `bash tools/run env EIDOLON_CAPTURE_ROOT=../T11 python -m pytest tests/test_reference.py tests/test_diagnostic_pcm.py tests/test_compatibility.py tests/test_review_short.py tests/test_review_stage.py --basetemp /tmp/opencode/eidolon/T13/pytest -q` → 244 passed, zero skips; 29 new tests include 28 independent fault cases.
- [V] T14 counter-review recheck from T13: `bash tools/run python ../T14/tools/reverse/confirm_capture_gate.py ../T11/artifacts/reference/proxy-b-d11-boundary3-20261016.json ../T11/artifacts/reference/proxy-b-d11-boundary-repeat-20261016.json`; after merge use `tools/reverse/confirm_capture_gate.py` and local artifacts. Native review input hashes: [t13-native-review.json](../artifacts/verification/t13-native-review.json).

## Agreement required

- [V] T11 acknowledged draft-3 acquisition and D9 provenance through the named handoff; T12 independently assessed its new per-run evidence in the section above.
- [V] Explicit final read/draw/pack state observations are established for the D11 pair in [T13 staged assessment](#t13-independent-staged-assessment); this does not establish a full-duration endpoint.
- [?] Each new run needs its own observed PCM final-cursor/full-range stability evidence and exact-repeat controlled captures; native clock integer mapping is `735*n` at 44100 Hz, preserving the original float conversion path.
- [?] A small real capture must establish acquisition semantics before full-reference comparison; unsupported native pixel formats require a contract revision rather than a lossy conversion.
