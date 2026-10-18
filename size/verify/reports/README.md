# Verification reports

Reports are named after the EXE's SHA-256. Large captures are stored locally in
`.build/verify/`; these files contain results and hashes. See
[the verifier guide](../README.md) to repeat a check.

## Verified build: 44 139 bytes

SHA-256: `d59888ef0ef7bb1f737e755d96892f0537037118d172073806a5ce26e47cf458`.
The full capture passed as `FULL_MEDIA_EXACT_PARTIAL`:

| Check | Result |
|---|---|
| Frames and native times | All 27 000 exact |
| Raw frames | 510 independently captured and byte-compared |
| PCM | All 159 716 352 bytes exact; completion and terminal memory stable |
| Physics | All 151 samples exact |
| Unpacking | Three register/FP restoration checks; decoded `.text`, `.data`, `.rdata` and `.edata` exact |
| Runtime state | 27 000 GL restoration records; marker/position register and FP state exact |
| Endpoint | 27 001 queries; terminal audio cursor 19 845 000 |
| Exit and cleanup | Child, Wine and Gamescope exited zero; no owned processes or audio sink remained |

The EXE, PE inputs, build tools and 194 source-file hashes matched the build from
`6b4a465`. All 22 media/input controls and five playback controls passed.
A [clean checkout](../../../artifacts/verification/size/build.json) reproduced the
same EXE. Native Windows is untested; `production_accepted` remains false.

| Report | Contents |
|---|---|
| [Summary](d59888ef0ef7bb1f737e755d96892f0537037118d172073806a5ce26e47cf458-phase2.json) | Input, build, source and control results with their hashes |
| [Full capture](d59888ef0ef7bb1f737e755d96892f0537037118d172073806a5ce26e47cf458-full.json) | Frame, PCM, state, restoration and cleanup results |
| [Playback pair](d59888ef0ef7bb1f737e755d96892f0537037118d172073806a5ce26e47cf458-paired.json) | Matched run conditions, measurements and observer diagnostics |
| [Completion](../../../artifacts/verification/size/completion.json) | Final build/capture hashes and the concurrent-workload audit |

## Playback measurements

One baseline and one final run, sequentially at 1920×1080 on an RTX 3070 Ti with
Gamescope 3.16.25 and Wine 11.17. Both used fresh prefixes with the same registry
and sample-bank seed, private audio sinks and the same observer. Both exited
naturally and passed cleanup checks.

| Observation | Baseline 47 561 bytes (`a46ecc05…`) | Final 44 139 bytes (`d59888ef…`) |
|---|---:|---:|
| Launcher wall time | 670.05 s | 691.05 s |
| Launch → first uncorked audio | 217.02 s | 237.02 s |
| Target sampled peak RSS | 954.95 MiB | 994.73 MiB |
| Target maximum observed VmHWM | 972.85 MiB | 994.73 MiB |
| Owned-process sampled peak RSS sum | 1 911.87 MiB | 1 951.40 MiB |
| Real-clock presentation count | 25 900 | 26 023 |
| Terminal audio cursor | 19 845 000 | 19 845 000 |

Startup was 20.00 seconds longer and sampled target RSS 39.78 MiB higher in this
pair. Startup includes Wine, shader setup, synthesis and audio submission.
One-second samples can miss peaks; process sums can count shared pages twice and
exclude GPU memory. Repeated isolated runs would be needed to establish a trend.

Review-branch tests and a build overlapped the last 31.75 seconds of the final
playback. The workload ran from `2026-10-18T04:04:37.792855Z` to
`04:05:39.349943Z`, after both startup measurements. There was no overlap with
the baseline. The completion report records these intervals.

Cold-cache state is unknown: neither requested NVIDIA cache directory existed
at review. The external `pactl` observer also logged 129 ASCII metadata warnings
during the final run. Parsing and all 450 audio observations per run passed;
the warning's metadata trigger was not identified. Logs and source hashes are
preserved in the playback reports.

## Earlier experiment: 44 101 bytes

SHA-256: `bf3e41ad84bedb37dd8d3b8b96f18868c5bee2a4190732605783cf4e08c54513`.
Its [full capture](bf3e41ad84bedb37dd8d3b8b96f18868c5bee2a4190732605783cf4e08c54513-full.json)
also passed: 27 000 frames, 510 raw anchors, full PCM, 151 physics samples,
restoration, endpoint and cleanup. This predates the corrected constant pass and
restored audio extent checks. The 44 139-byte build was verified separately.
The 1 084.49-second instrumented run included concurrent host work.

The [smoke run](bf3e41ad84bedb37dd8d3b8b96f18868c5bee2a4190732605783cf4e08c54513-smoke-crash.json)
remains **FAIL**: its media matched, but Gamescope exited 139 during teardown
after the child exited zero. The core confirmed SIGSEGV during libc `exit`;
the failing function was not identified. The full run's inherited `DISPLAY`
differed from the smoke configuration, but is not a confirmed fix. An earlier
smoke attempt was interrupted by the outer shell timeout during synthesis and
provides no media result.
