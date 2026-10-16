# Rust conformance contract — T24

- [V] Owner: T24; implementation: [conformance.py](../tools/verify/rust/conformance.py); fault suite: [test_conformance.py](rust/test_conformance.py).
- [V] T17 G6 accepts the D9-restored-native reference; offline checks report `reference_accepted:true`, `production_accepted:false`; [accepted scope](../reports/03-tests.md).
- [V] Expected data comes from main's pinned reference1, its hash-bound frame index, PCM, eligibility ledger, producer envelope, raw native state and ordered observation stream; no engine/audio implementation computes native expected words.
- [V] Native input pin, projected-vector hash and coverage: [native.json](../artifacts/verification/rust/native.json); retained-candidate pins/results: [partials.json](../artifacts/verification/rust/partials.json).
- [V] Retained CPU streams are independently hash-pinned; production capture preparation reads fixed Git objects and copies the hash-pinned EXE; merged standalone audio uses a hash-checked source snapshot.

## Commands

- [V] Native integrity: `bash tools/run python tools/verify/rust/conformance.py native` checks all27000 hashes,510 raw buffers, complete PCM, seven initial-state payloads and27000 observed time records.
- [V] Retained host-stream replay: `bash tools/run python tools/verify/rust/check_partials.py`; original `partials.json` remains an immutable input, and overwritten build directories/removed worktrees are unnecessary.
- [V] Independent standalone synthesis: `bash tools/run python tools/verify/rust/standalone.py`; builds the merged production entrypoint from a private source snapshot and compares every PCM byte with accepted reference1.
- [V] Fault suite: `bash tools/run python -m pytest tests/rust -q --basetemp /tmp/opencode/eidolon/T24-pytest`.
- [V] Individual checks: `conformance.py probe STREAM`, `shaders STREAM`, `identity EXE`, `pcm PCM --kind standalone-rust-diagnostic|hybrid-source-oracle-diagnostic`, `frames INDEX --payload-root DIRECTORY`, or `full-run MANIFEST`, each through `bash tools/run python tools/verify/rust/`.
- [V] Root overrides precede the operation: `--capture-root CHECKOUT --data-root DATA`; defaults select this merged checkout's reference1 and shared data.
- [V] Exit0 means the requested offline operation passed within its declared coverage; exit1 means failed integrity/conformance; exit2 means CLI usage error.

## Native and derived vector coverage

- [V] `EIDRAW01` and `EIDSTA01` follow T22's shared handoff:27000 ordered records, eight little-endian u32 header words `(n,cursor,seconds_bits,beat_bits,row,local_beat_bits,dt_bits,uniform_count)`, then `(name_index,components,component_words...)`; state records append64 u32 words; no footer/padding.
- [V] Native observed checks compare every cursor, seconds bit-pattern and local-beat bit-pattern; row attribution comes from reference1's independently reviewed50-row scene partition, including adjacent rows sharing a token.
- [V] Native ordered-stream projection is27000 little-endian `<5I` tuples `(n,cursor,seconds_bits,local_beat_bits,scene_token)`; decoded and compressed stream hashes are checked before trusting it.
- [V] Native frame-zero physics is exactly256 bytes from `native-first-query-physics.bin`; all seven initial-state dumps are available for future candidate serialization in native layout.
- [V] Beat and dt checks are explicitly derived f32 models; `delta_f32_bits` in the native scene event is not treated as an authenticated dt oracle.
- [?] Reference1 does not supply independently authenticated post-update physics/curve-uniform vectors throughout the run; later state records and uniform values are structurally parsed but not certified.
- [V] Shader stream `EIDGLS01` compares31 programs/235 NUL-terminated source-array elements directly with hash-bound effective native shader files; loading program appears last in the probe ABI.
- [V] Host-probe agreement establishes neither Windows x86 numeric behavior nor graphics linking/pass output; standalone production-entrypoint PCM now independently matches natively, with host/target scope kept separate.

## Standalone provenance and data closure

- [V] [standalone.json](../artifacts/verification/rust/standalone.json) binds all15 audio Rust files, independent harness, exact compiler dependency list/command/version, executable dependencies, output and source snapshot.
- [V] The independent harness calls only full `audio::render`; rejects wrong-length buffers without writes, initializes all39929088 samples with a NaN poison, checks complete replacement and caller MXCSR restoration, then writes all159716352 bytes through a preopened descriptor.
- [V] Linux seccomp rejects file-open and exec syscalls after the output descriptor is opened; a deliberately forbidden `/etc/passwd` open verifies enforcement before rendering from an otherwise empty working directory.
- [V] Compiler dependencies close over the15 Rust modules and harness; dynamic dependencies are libc/libgcc/loader only; no source-oracle player is linked.
- [V] Compiled score/patch bytes match the pinned native image; proper RIFF traversal checks all15 reachable instrument waves/85548 PCM16 bytes against the pinned bank;375 formant coefficients match the pinned recovered source, separately labeled from native observations.
- [V] Native full PCM comparison includes the956352-byte tail; host agreement and embedded closure do not certify Windows playback or the shipped audiovisual EXE.

## Prepared production capture and runtime envelope

- [V] `bash tools/run python tools/capture/rust/prepare.py --commit FULL_PUBLICATION_COMMIT --directory NEW_DIRECTORY` follows the committed immutable-bundle pointer, checks every bundle/source-archive entry and committed/generated/recovered asset, copies the exact published PE, verifies imports/marker export, and cross-builds the helper without executing Windows.
- [V] [capture.json](../artifacts/verification/rust/capture.json) pins the immutable request; the request binds EXE/source/assets/helper/adapter/checker files, `--play`, marker RVA,510 retention anchors, expected environment and worst-case storage reservation below30GB.
- [V] `runtime-envelope.template.json` starts `UNEXECUTED` with null observations; the verifier rejects it until an independently supervised runtime publishes actual files/process observations.
- [V] `capture.c` and `inject.js` consume T22's synchronous cdecl marker ABI; kinds1..5 copy284-byte snapshots, kind6 saves complete PCM, kind7 rehashes submitted memory, and terminal kind5 rehashes that source memory again.
- [V] The prepared adapter controls only candidate-origin `waveOutGetPosition` cursors at735*n; graphics-only mode cannot pass because both PCM markers are mandatory.
- [V] Native helper writes pixel/PCM data directly to files; timeline marker3 reads GL_BACK RGBA8/bottom-up1920×1080 with default FBOs/no PBO/no multisampling/sRGB, restores pack/read-buffer state and retains exactly510 raw frames.
- [V] `events.bin` starts `EIDCAP01`; each record has little-endian u32 `(sequence,thread_id,kind,payload_bytes)`. Kinds1..5 have284 bytes;6/7/9 have32-byte PCM digests;8 has `(frame:u32,sha256:32 bytes)`;10 has16 layout/state words.
- [V] Required order is6,7,1; then27000 repetitions of2,3,10,8,4; then5,9; sequences and one capture thread must be continuous. Native cursor/seconds/row/local-beat/pixels, frame-zero physics, endpoint and all PCM digests compare exactly.
- [V] `runtime_events.py LEDGER` validates that protocol; `runtime_events.py ENVELOPE --request-sha256 PIN` additionally rehashes the pinned request inventory, full PCM,510 raws, process evidence, actual command/environment/EXE identities, exit0/no timeout/zero losses.
- [V] Runtime envelope fields are exactly `schema:"eidolon-rust-runtime-envelope-1",status:"CLOSED",request,events,pcm,process`; file fields are `{path,sha256}`. Process fields are `command,environment,exe_before_sha256,exe_after_sha256,exit_code,timeout,dropped_frames,dropped_audio_sample_frames,evidence`.
- [V] D26 validates the separate native `launch.c`/`live.c`/`hook.S` route through `tools/wine-headless`: suspended creation, pinned PE-entry stub, dynamic marker/IAT routing, physical GPR/EFLAGS/FP restoration, and short exact native comparisons. Prepared Frida JavaScript is not the executed attachment route.
- [?] Marker ABI exposes initial physics but not seven native-layout initialization payloads required by the separate general file-envelope below; those must not be fabricated from native copies.

## Candidate file envelope

- [V] D26 live jobs use `tools/capture/rust/live.py NAME`, each with fresh stopped-prefix copy, private audio sink, pre/post EXE hashes, immutable source/build snapshots and durable `state.json`/`runner.log` under `$EIDOLON_DATA/verification/rust/NAME`.
- [V] `tools/verify/rust/review_live.py DIRECTORY` checks closed short jobs and physical fault controls; live reviews are `artifacts/verification/rust/live-{01,02,fp-reject,entry-reject}.json`.
- [V] Actual Windows captures0–2 and complete PCM match accepted native data; marker FP and entry GPR corruption controls exit125 with zero accepted pixels. Scope is this bounded prefix and these routes.
- [V] `tools/capture/rust/launch_full.py NAME` gates on those reviews and starts exactly one `setsid nohup` job; `artifacts/verification/rust/full-job.json` pins PID/log/state and source identity. Full mode keeps510 native retention anchors, disables wrapper stops, requires native terminal marker5 and reserves less than30GB.
- [V] Full runner has closed; instrumented startup, controlled speed, child peak working set and wall duration are recorded in [full-progress.json](../artifacts/verification/rust/full-progress.json), with uninstrumented scope explicitly excluded.

## Step3 completion audit

- [V] `bash tools/run python tools/verify/rust/monitor_full.py` reconciles the pinned full-job request, immutable EXE/helper/source hashes, ledger and every closed output; growing ledgers admit only complete prefix records. Tests: `tests/rust/test_monitor.py`.
- [V] `live-d26-full01` passes27000 native RGBA hashes,510 directly byte-compared native raw anchors, all159716352 PCM bytes including tail,27000 native time/row records, initial physics,27001-query endpoint and three stable PCM digests; [closed result](../artifacts/verification/rust/full-progress.json).
- [V] Every present has a raw GL pack/read-buffer restoration witness; entry/marker GPR/EFLAGS/FP witnesses agree. Existing physical entry-GPR and marker-MXCSR fault controls remain bounded to their reviewed routes.
- [V] Natural completion reports child/Wine/gamescope exit0; process/session/prefix/private-sink cleanup is independently checked. T24's GPU allocation remains exclusive across handoff despite completed acquisition.
- [V] Actual mapped candidate/helper paths and Wine executable hash were observed while running; the20872-frame observation is preserved in Git commit1b9c140's `artifacts/verification/rust/full-progress.json`.
- [V] The measured baseline is instrumented and controlled-clock: size728576 bytes, PCM-ready267636ms, timeline-ready268607ms, mean32.142742 FPS, peak working set782987264 bytes, child wall1108833ms; it includes capture/readback/I/O overhead.
- [V] `bash tools/run python tools/verify/rust/state_scope.py` rehashes/decodes the accepted native stream and audits all seven initialization payloads; [state-scope.json](../artifacts/verification/rust/state-scope.json) records per-payload coverage and every available observation field.
- [V] D28 adopts exact live-field/lifetime correspondence plus separately pinned constants. `live-d28-prefix` observes matching16-byte seed,4-byte tick,4-byte previous-seconds and256-byte initial physics at T25's fingerprinted phases; native entry/prethread storage is not fabricated as a Rust dump. [Semantic prefix](../artifacts/verification/rust/live-d28-prefix.json).
- [V] Saved native later-state evidence includes513000 `scene_pass` observations of `uTimeResolution`/`uClouds`,27000 scene-clock records and24 synthesis `node_rng` observations; it contains no later graphics-physics or curve-uniform vector. The saved candidate ledger has no per-pass uniform-value payload.
- [V] Follow-up diagnostic jobs physically change restored GL_PACK_ALIGNMENT and position-hook MXCSR; both reject with exit125 before any accepted pixel, then clean up. The GL job also witnesses position FP and seven-GPR/EFLAGS preservation, excluding EAX's MMRESULT output. [GL control](../artifacts/verification/rust/control-gl.json), [position control](../artifacts/verification/rust/control-position.json).
- [V] These controls bind their own strengthened diagnostic helper/source snapshots, omit redundant PCM files while checking actual synthesis/submission digests, and do not replace the original full capture's immutable helper identity. Reproduce with `live.py NAME --physical-control gl|position`, then `review_controls.py NAME`, through `bash tools/run python tools/capture/rust/` or `tools/verify/rust/` respectively.
- [V] Independent clean offline build from the immutable source archive reproduces every728576 production byte; [rebuild.json](../artifacts/verification/rust/rebuild.json). Reproduce with `bash tools/run python tools/verify/rust/rebuild.py NEW_JOB_NAME`; source extraction is outside Cargo ancestor configurations and all compiler scratch is removed after preserving output/provenance.
- [V] Initial nested-source rebuilds inherited main and local Cargo rustflags twice, changing17 PE checksum/export-name bytes; [build-diagnostics.json](../artifacts/verification/rust/build-diagnostics.json). Isolated rebuilding resolves this verifier-context issue without modifying or normalizing the candidate.
- [V] `bash tools/run python tools/verify/rust/build_closure.py` resolves132 independent compiler inputs, including all15 audio modules and embedded assets, against the pinned source inventory; the rebuilt PE's16 imports equal the publication. [build-closure.json](../artifacts/verification/rust/build-closure.json).
- [V] All-syscall `resource-d26-all02` closes naturally:14267379 records,91 process/thread IDs,4299 classified resources, zero unresolved successful opens/async engines/unknown syscalls/unterminated PIDs.24 network route probes transfer zero payload bytes; System V shared memory is private; cleanup passes. Post-run file hashes do not claim mutable cache/registry bytes at every read. [Resource closure](../artifacts/verification/rust/resource-closure.json).
- [V] `tools/capture/rust/resources.py NAME` records kernel accesses through the approved launcher with pinned strace7.0; output is streamed losslessly to `syscalls.zst`, with decoded/compressed hashes and durable PID/log/state. The initial whole-launcher selected-I/O run is not an all-syscall claim; target-only mode uses `trace=all` from Wine exec through descendants and avoids compositor-only traffic.
- [V] Linux-only `resource_canary.py` physically exercises fork/thread, descriptor passing, duplication, reads and mmap; the auditor finds its deliberately external PCM path through both open and SCM_RIGHTS/mmap observations. [Canary](../artifacts/verification/rust/resource-canary.json); parser tests: `tests/rust/test_resources.py`.
- [V] Resource audit fails closed on malformed/truncated records and records successful async-I/O engines, unknown syscalls, unfinished processes and unclassified paths for review; capturing an inventory alone does not establish resource closure.
- [V] `semantic.c` reads live fields and queries GPU-active uniforms before the actual glRecti call, with FP/GPR restoration and active-texture restoration checks. A physical seed-hook MXCSR mutation rejects with exit125; [control](../artifacts/verification/rust/live-d28-seed-reject.json).
- [V] Three candidate frames/57 passes match saved native time/cloud observations exactly, with31 observed shader-source identities and framebuffer/volume roles. `semantic.py` derives its native expectations solely from the hash-checked saved native stream.
- [?] Full scalar-only job `live-d28-scalars-full01` is detached and active; [PID/log/state](../artifacts/verification/rust/semantic-job.json). Native later graphics-physics/curve vectors still need a bounded independent oracle; production acceptance remains false.
- [V] Uninjected production `--play` completes on its real waveOut clock:25978 presents/25979 queries, terminal cursor19845000,450 audio seconds, child/Wine/gamescope exit0. The actual process publishes uncorked float32le stereo44100Hz to the private null sink; [playback.json](../artifacts/verification/rust/playback.json).
- [V] External baseline measures270.340s launch-to-first audio,57.728889 mean presents/audio-second, peak host-process RSS768786432 bytes/HWM782598144 bytes,722.743s launcher duration. Sampling interval is at most1.065s; startup overlaps bounded CPU verification and is not an isolated microbenchmark.
- [V] `tools/capture/rust/playback.py NAME` runs the unchanged EXE directly through `tools/wine-headless`, with no injected helper or clock replacement; it binds157 sampled mapped-file hashes, Wine version, actual process/audio metadata and hash-bound logs. `tools/verify/rust/review_playback.py NAME` verifies these records after cleanup.
- [?] This live-clock baseline establishes device submission/natural playback and measured throughput, not speaker output or per-present exact numerical comparison under changing real-time cursors; controlled full exactness remains independently established.
- [V] The general candidate envelope and earlier unexecuted Frida template remain distinct contracts; missing observations are not backfilled with native files. Step3 and production acceptance remain pending.

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
- [?] Production acceptance requires the complete shipped audiovisual EXE, reproducible builds, Windows target execution, exact all-frame/PCM comparison, runtime fault controls and measured startup/runtime/memory/size baselines; reference G6 is accepted.
- [V] Missing native post-update vectors remain explicit; no tolerance, alignment, frame deletion, PCM trimming, normalization or model-as-native substitution is authorized.
