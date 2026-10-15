# Draft reference contract

- [H] Owner: T3; schema `eidolon-reference-draft-1`; pending T2 agreement and T1-confirmed capture points.
- [V] Acceptance target: [approved step 1](../GOAL.md#approved-step-1--reproducible-reference-of-the-original).
- [V] Executable checker: [tools/verify/reference.py](../tools/verify/reference.py); synthetic fixture: [reference_factory.py](reference_factory.py).
- [H] A `PASS` under this draft reports only the requested integrity/comparison operation; synthetic captures establish neither an original reference nor original repeatability.

## Files and types

- [H] Each run has a UTF-8 JSON manifest and a UTF-8 JSONL frame index; manifests/indexes are small Git artifacts, while PCM and `.raw.zst` files live under `$EIDOLON_DATA/reference/<run>/`.
- [H] Index paths resolve relative to the manifest; PCM/raw paths resolve relative to the CLI data root, defaulting to the manifest directory.
- [H] Payload paths use relative POSIX components; absolute paths, `.`/`..`, backslashes, missing files, and symlink escapes fail.
- [H] Objects accept exactly the fields below; duplicate keys, non-finite numbers, missing fields, and unknown fields fail.
- [H] Counts/ticks are JSON integers, never booleans or floats; hashes are lowercase 64-character SHA-256; descriptive strings are nonempty.
- [H] Capture publishes the final manifest only after all payloads and the index are closed successfully; its completion counters are independently checked for consistency.

## Manifest

- [H] `schema`: exactly `eidolon-reference-draft-1`.
- [H] `run_id`: a unique identifier for a separate invocation; comparing the same ID or manifest is a failure.
- [H] `source`: `{kind, exe_sha256, inputs}`; `kind` is `original` or `synthetic`; `inputs` maps every other input's stable name to its hash.
- [H] `source.exe_sha256` for `original` must equal the approved native EXE hash in `GOAL.md`; synthetic inputs must be labeled `synthetic`.
- [H] `capture`: `{kind, tool_sha256, command}`; `kind` is `controlled-reference` for originals or `synthetic-reference` for synthetic fixtures; `compatibility-smoke` is rejected.
- [H] `capture.tool_sha256` hashes the complete capture implementation bundle; `command` is the exact nonempty argument array used to reproduce the capture.
- [H] `conditions`: `{environment, settings, clock, rng, initial_state_sha256}`; `settings` records every capture/demo setting as a JSON object.
- [H] `conditions.environment`: `{os, arch, wine, gpu, driver, graphics_api, desktop}`; version/identity strings must be pinned; `desktop` is exactly `[1920,1080]`.
- [H] `conditions.clock`: `{numerator:1, denominator:60, method}`; `method` identifies how the clock and audio position fed to the demo are controlled.
- [H] `conditions.rng`: `{method, initial_state_sha256}`; identify RNG initialization/control and hash its initial-state serialization.
- [H] `conditions.initial_state_sha256`: hash the stable initial-state specification, including Wine-prefix baseline, initial resources and process/FP settings affecting output.
- [H] `video`: `{width, height, row_stride, pixel_format, row_order, color_space, frame_count, index, index_sha256, storage}`.
- [H] `video.width`/`height` are positive final-buffer dimensions, independently recorded from the virtual-desktop dimensions; `row_stride = width * 4` bytes.
- [H] `video.pixel_format` is `rgba8` or `bgra8`; `row_order` is `top-down` or `bottom-up`; `color_space` names the actual interpretation without applying a conversion.
- [H] `video.frame_count = N > 0`; `index_sha256` hashes the exact index file bytes, including newlines; `storage` is `reference` or `hashes`.
- [H] `audio`: `{path, sha256, sample_format, sample_rate, channels, layout, sample_frames, start_sample}`.
- [H] `audio.sample_format` is `s16le`, `s24le`, `s32le`, `f32le`, or `f64le`; `sample_rate > 0` is in Hz; `channels` is a nonempty ordered array of unique channel labels; `layout` is `interleaved`.
- [H] `audio.start_sample = 0`; `sample_frames = A > 0` counts multichannel instants, not scalar samples; file length is exactly `A * len(channels) * bytes_per_sample`.
- [H] `audio.sha256` hashes the entire headerless PCM file; retain any generated tail beyond the final playback cursor, rather than trimming, resampling, normalizing, or adding silence.
- [H] `scenes`: ordered nonempty array of `{id, first, last}` with unique IDs and inclusive frame bounds partitioning `0..N-1` exactly; boundaries come from T1's timeline.
- [H] `termination`: `{reason, end_tick, audio_position, audio_position_num, audio_position_den, exit_code, timeline_end_tick, evidence}` with `end_tick=N` and `audio_position=floor(N*sample_rate/60) <= A`.
- [H] The terminal ideal sample position is the exact rational `audio_position_num=N*sample_rate`, `audio_position_den=60`; retain the fractional phase even when the native integer cursor is rounded down.
- [H] Natural termination requires `reason=natural_exit`, `exit_code=0`, `timeline_end_tick=null`, and evidence identifying the observed process-exit event.
- [H] Timeline termination requires `reason=timeline_end`, `timeline_end_tick=N`, `exit_code=null`, and evidence identifying T1's established exclusive timeline endpoint.
- [H] `completion`: `{finalized:true, frames_observed:N, frames_hashed:N, audio_sample_frames:A, dropped_frames:0, dropped_audio_sample_frames:0, errors:[]}`.
- [H] Timeout, crash, manual abort, capture errors, partial manifests, loss counters, zero-length runs, or inconsistent end/count fields fail even when both inputs share the defect.

## Frames and time

- [H] The index has exactly one object per line for every `n=0..N-1`, in order, with `{n, tick, clock_tick, audio_position, audio_position_num, audio_position_den, sha256}` and optional `raw_zst`.
- [H] `tick=n` means frame presentation at exactly `n/60` seconds; `clock_tick=n` records the controlled clock supplied for that render; `audio_position=floor(n*sample_rate/60)` is the supplied PCM cursor in sample frames.
- [H] Record the ideal cursor as unreduced `audio_position_num=n*sample_rate`, `audio_position_den=60`; this preserves fractional-sample timing independently of the native integer cursor.
- [H] Frame `n` is the final buffer immediately before its present, after rendering with clock `n/60` and the corresponding controlled audio position; readback must complete before the buffer is reused.
- [H] The exclusive playback endpoint is `N/60` seconds; use integer arithmetic for audio positions, including sample rates not divisible by 60.
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
- [H] No tolerance, time alignment, dropped prefix/suffix, frame deduplication, image conversion or audio normalization is permitted.
- [H] Source/tool/state hashes and end-event evidence are declarations checked for shape/equality, not proof of runtime behavior; capture-point correctness and a full natural end require T1/T2 evidence.
- [H] A consistently forged/truncated pair with rewritten termination declarations cannot be disproved from these payloads alone; a T1-established endpoint or independently verified exit event is necessary.

## Commands

- [H] Single-run integrity: `bash tools/run python tools/verify/reference.py validate <manifest> --data-root <run-data>`.
- [H] Independent run comparison: `bash tools/run python tools/verify/reference.py compare <reference-manifest> <repeat-manifest> --reference-data <reference-data> --candidate-data <repeat-data>`.
- [H] JSON output contains `status: PASS|FAIL`, `draft:true`, `source_kinds`, operation and failure reasons; exit status is `0` for PASS, `1` for FAIL, `2` for CLI usage errors.
- [V] Pytest 9.1.1 fails setup if the temporary parent is absent; prerequisite: `bash tools/run python -c "from pathlib import Path; Path('/tmp/opencode/eidolon/T3').mkdir(parents=True, exist_ok=True)"`.
- [V] Synthetic regression command: `bash tools/run python -m pytest tests/test_reference.py --basetemp /tmp/opencode/eidolon/T3/pytest -q` → 87 passed with Python 3.14.7 and zstandard 0.25.0.

## Agreement required

- [?] T2 must confirm the native final-buffer format, row layout, actual API/capture point and clock/audio-cursor semantics before this schema becomes agreed.
- [?] T1/T2 must identify scene boundaries, the exclusive endpoint and whether complete generated PCM includes a tail; this draft preserves that tail and requires coverage through the endpoint.
- [V] T2's proposal is `$EIDOLON_ROOT/handoff/capture-to-verification-format.md`; T3's response is `$EIDOLON_ROOT/handoff/verification-to-capture-format.md`.
- [?] T2 must agree integer-cursor rounding and supply a small real capture; unsupported native pixel/PCM formats require a new draft revision rather than a lossy conversion.
