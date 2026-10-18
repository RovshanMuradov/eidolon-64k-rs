# Verification reports

Reports are keyed by the delivered executable's complete SHA-256. They describe
exploratory candidates and never set `production_accepted` to true. The large
acquisition evidence stays in the verifier checkout's ignored `.build/verify/`.

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
