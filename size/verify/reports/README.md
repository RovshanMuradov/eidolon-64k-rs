# Verification reports

Reports are keyed by the delivered executable's complete SHA-256. They describe
tested candidates and never set `production_accepted` to true. The large
acquisition evidence stays in the verifier checkout's ignored `.build/verify/`.

## Final Phase 2: `d59888ef0ef7bb1f737e755d96892f0537037118d172073806a5ce26e47cf458`

**44,139 bytes. Exact full media and the two bounded playback observations pass.**
`production_accepted` remains false; no formal performance threshold was agreed.
The candidate, original/prepared PE, build manifest, packer/NASM binaries, and all
194 recorded source-file hashes were validated against the supplied build from
commit `6b4a4657e46d8659b473ab4698ce16fc33c55a5f`.

The full capture (`full44139`) is **`FULL_MEDIA_EXACT_PARTIAL`**:
27,000 exact frame hashes and native times; 510 raw anchors byte-compared; all
159,716,352 PCM bytes exact; 151 physics samples exact; 27,000 GL restoration
witnesses; three restored depacker/OEP stages; exact decoded `.text`, `.data`,
`.rdata`, and `.edata` sections; marker/position GPR and FP restoration; and the
natural 27,001-query endpoint at sample cursor 19,845,000. There are no mismatches.
Child/Wine/Gamescope all exited zero. Supervisor, runner, prefix, and sink cleanup
passed. The full run subsumes a short smoke; no additional smoke was launched.

### Uninjected playback pair

After full-capture closure, one baseline and one final playback ran sequentially
at 1920×1080 on the same RTX 3070 Ti/Gamescope 3.16.25/Wine 11.17 setup. Both used
fresh copied prefixes with identical registry/bank seed hashes, private audio
sinks, and the same observer/wrapper sources. Both reached natural live-clock
exit and passed strict Wine/Gamescope and supervisor/prefix/sink cleanup checks.
The two timed runner windows total **1,361.11 seconds (22.69 minutes)**.

| Observation | Baseline 47,561 bytes (`a46ecc05…`) | Final 44,139 bytes (`d59888ef…`) |
|---|---:|---:|
| Launcher wall time | 670.05 s | 691.05 s |
| Launch → first uncorked audio | 217.02 s | 237.02 s |
| Target sampled peak RSS | 954.95 MiB | 994.73 MiB |
| Target maximum observed VmHWM | 972.85 MiB | 994.73 MiB |
| Owned-process sampled peak RSS sum | 1,911.87 MiB | 1,951.40 MiB |
| Real-clock presentation count | 25,900 | 26,023 |
| Terminal audio cursor | 19,845,000 | 19,845,000 |

The final run's observed startup is **20.00 seconds higher** and sampled target
RSS is **39.78 MiB higher** in this single pair. This is descriptive evidence;
it establishes neither statistical significance nor a slowdown cause. Startup
includes Wine/bootstrap, shader setup, synthesis, and device submission. Memory
is sampled about once per second; the owned-process sum can double-count shared
pages and excludes GPU VRAM/shared system services. No isolated depacker time,
synthesis-only time, frame-time distribution, or native FPS is claimed.

Separate NVIDIA cache paths were requested, but neither requested directory was
present at review. Effective driver-cache behavior and cold-cache
state are therefore **unverified**. The portable runner now creates the requested
directory for future runs; the original acquisition source snapshots stay pinned.
The final run's external `pactl` observer console emitted 129 ASCII metadata
warnings (the diagnostic string is in `libpulsecommon-17.0.so`). Neither target
runner log contains those warnings; JSON parsing and all 450 attributed audio
observations per run passed. The console is preserved and hashed; its precise
metadata trigger was not isolated. No extra playback was launched.

### Reports and remaining scope

- [Phase 2 summary](d59888ef0ef7bb1f737e755d96892f0537037118d172073806a5ce26e47cf458-phase2.json),
  SHA-256 `d68a54e1e025db0e8152166440943e713761910849cee77d7f89550d5d58a0ad`.
- [Full-media review](d59888ef0ef7bb1f737e755d96892f0537037118d172073806a5ce26e47cf458-full.json),
  SHA-256 `b873dba475f1edf40469099e0369bad8897bd6e98891715b35061970c6329e79`.
- [Paired playback review](d59888ef0ef7bb1f737e755d96892f0537037118d172073806a5ce26e47cf458-paired.json),
  SHA-256 `79e0e2ef75b367381055215c6e682725232555fa0dd5a1c40b04920437b7380a`.

The summary pins the input/build/source-validation reports, both playback reviews,
and the **22 media/input controls plus five paired-playback controls**. All pass.
Clean-checkout reproducibility belongs to the integrating session's separate
candidate-keyed attestation; this report makes no claim that it was unperformed.
Native Windows remains explicitly untested and formal acceptance remains open.
All owned acquisitions are closed and GPU ownership is released.

## `bf3e41ad84bedb37dd8d3b8b96f18868c5bee2a4190732605783cf4e08c54513`

**44,101 bytes; Phase 1 complete.** The closed full acquisition
`.build/verify/full44101` passed the strict review as
**`FULL_MEDIA_EXACT_PARTIAL`**, with `production_accepted: false`.

| Full-capture check | Result |
|---|---|
| Final RGBA hashes and observed native times | 27,000 exact; zero differences |
| Retained raw frames | 510 independently captured and byte-compared |
| PCM | All 159,716,352 bytes exact; completion and terminal stability pass |
| Sampled physics | 151 exact; zero differing words |
| GL restoration | 27,000 frame witnesses pass |
| Decoder/OEP restoration | All three stages pass |
| Decoded sections | `.text`, `.data`, `.rdata`, `.edata` exact; entry/marker fingerprints pass |
| Marker and position hooks | GPR and FP restoration pass |
| Natural endpoint | 27,001 queries; terminal sample cursor 19,845,000 |
| Process closure | Exactly one child/Wine/Gamescope exit record, all zero |
| Cleanup | No supervisor, runner, prefix processes, or private sink remain |

The full report is
[`bf3e41ad…-full.json`](bf3e41ad84bedb37dd8d3b8b96f18868c5bee2a4190732605783cf4e08c54513-full.json).
Its SHA-256 is `df544803b8bbbaae19d9057975593ef89283e7cf7260e158663a3f2897152dc4`.
The capture state is pinned by
`5aee80eaa1771415bc545932a9372a9687a151530063d67c5428b9105f022dce`;
the preserved candidate manifest by
`76d10fd8283b12a7c5cffbc3c1d79fb08d5a8d94ccdd13081719a87bf1de1dfe`.

This is the exploratory checkpoint, before the parent's corrected constant
merging and restored extent checks. Those changes produce a different candidate
and need their own Phase 2 evidence. This result cannot be transferred by size or
filename. The observed 1,084.49-second instrumented run included concurrent host
work and is **not a solo performance benchmark**. GPU ownership is released.

### Smoke failure retained

The closed smoke acquisition (`smoke44101b`) matched all three frames, full PCM,
three sampled physics states, decoded sections, and physical restoration. Its
overall result is **FAIL**: Gamescope exited 139 during teardown, after
`CHILD_EXIT 0 stages=111`. Prefix, sink, and runner cleanup passed. The compositor
core confirms SIGSEGV during libc `exit`; the precise failing function remains
unsymbolized. No kernel OOM or NVIDIA Xid event was found in the UTC crash window.
See [`bf3e41ad…-smoke-crash.json`](bf3e41ad84bedb37dd8d3b8b96f18868c5bee2a4190732605783cf4e08c54513-smoke-crash.json).
The full run's clean exit does not reclassify the failed smoke. The full wrapper
retained inherited `DISPLAY`, matching the original private wrapper; this
configuration difference is not established as a fix for the teardown crash.

The earlier `smoke44101` attempt was stopped after the outer shell timeout killed
its supervisor during synthesis; it is excluded from media verification.

The public frame/PCM reference files match the pinned private native oracle.
Twenty-two offline positive/corruption controls passed. The adapted wrapper now
propagates a nonzero Gamescope exit even when Wine exits zero, and the reviewer
requires unambiguous exit records and supervisor cleanup. The capture's actual
source snapshots and hashes remain preserved separately from this later review.

Native Windows, final clean
rebuild, matched solo performance/resources, and formal acceptance remain open.
