# Draft reference contract

- [V] Owner: Verification/T12; assignment: [briefs/T12.md](../briefs/T12.md).
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
- [H] T12 independently reviews G5/G6 when real capture exists; the coordinator resolves restoration acceptance before any modified-source full-reference schema is admitted. Missing observations remain missing and cannot be inferred from static tables or a shader fix.
- [?] Historical driver/compiler output and author bank identity remain unknown; exact candidate agreement proves pinned compatibility-run agreement only.

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

## Agreement required

- [?] T11 must acknowledge draft-3 acquisition fields and D9 provenance through the named handoff and satisfy runtime gates independently of old B diagnostics.
- [?] T11 must confirm native final-buffer layout, actual read-buffer/samples/sRGB, pre-present ordering, scene boundaries and controlled frame zero/endpoint; packed four-byte pixels remain provisional.
- [?] Each new run needs its own observed PCM final-cursor/full-range stability evidence and exact-repeat controlled captures; native clock integer mapping is `735*n` at 44100 Hz, preserving the original float conversion path.
- [?] A small real capture must establish acquisition semantics before full-reference comparison; unsupported native pixel formats require a contract revision rather than a lossy conversion.
