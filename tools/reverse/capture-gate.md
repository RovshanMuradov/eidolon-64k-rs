# T14 static map and pending capture probes

## Reproduction and scope
- [V] `bash tools/run python tools/reverse/confirm_capture_gate.py --timeline` checks pinned native dumps and both T11 boundary bundles; output is `TECHNICAL_CONFIRMATION_ONLY`, never reference acceptance.
- [V] Add `--static-only` to reproduce the map using only Reverse dumps; Python 3.14.7 / GNU objdump 2.47; input hashes and paths are emitted as `native_inputs`, rooted at `$EIDOLON_DATA`.
- [V] Saved-run identities/environment remain in T11 `artifacts/reference/proxy-b-d11-{boundary3,boundary-repeat}-20261016.json`; the checker emits their hashes and verifies backend, source-snapshot, atlas and CONTEXT bytes.
- [?] All S1/S2/V1/E1 probes below remain pending: T11 acquires them, T15 independently validates them later; T13 owns `tests/reference-format.md`. Static/saved-evidence completion does not close the live gate.

## Native boundary, sampling and endpoint
- [V] `0x407ba1..0x407be5`: unsigned cursor → double → float32 → float32 division by 44100 → float32 multiplication by float32(80/60); controlled cursor is `735*n`, with round-to-nearest-even modeled from the saved FP controls.
- [V] `0x407bf7/0x407bfa` selects the first row whose end beat is strictly greater; `0x407c0f` subtracts its start. All 1443 native seconds/local-beat/token triples match independently in each saved run.
- [V] Frame 1439 has seconds/local bits `1103093214/1107284606`; frame 1440 has `1103101952/0`: row 0→1 at 24 seconds/beat 32, despite both rows using token 0 and final program 20.
- [V] `[EBP-0x2c]` contains dt at `0x407be9..0x408291`; `0x4082c6` overwrites it with pass index 18 before presentation, explaining T11's `delta_f32_bits=18`.
- [V] `--timeline` emits 50 `sampling_ranges` with row, half-open beat range, reused scene token, inclusive frame range, first/last native float bits/cursors and static cloud routes; `retain_frames` has 510 unique indices (every 60th frame plus each row's first/last).
- [V] The map covers frames 0…26999 exactly; `endpoint_static` describes query n=27000/cursor 19845000/450 seconds/beat 600: EAX=-1 at `0x407c1d`, branch `0x407c20→0x408617`, EDI=0 pushed to ExitProcess at `0x408618`, no presentation. Null local/token fields mean no selected row, not cleared native storage.
- [V] Final shader `0x41b0b0` fades to black at beat 597 (447.75 seconds); native termination still occurs at beat 600, so retain through frame 26999.
- [?] E1: during the approved full sequential run, retain last presentation 26999, query n=27000 and its cursor, native seconds/beat/EAX/EDI at `0x407c1d` plus the exit path/call and process status 0; prove no presentation at 27000 and no wrapper partial-stop trigger. The saved 1443-frame stops precede native end selection.

## RNG and persistent state ownership
- [V] Synth RNG `0x401038` owns 16 bytes at `0x0b16b810`; initializer `0x401115` copies `[1,0,31337,0]` from `0x437000`. Signed PMULDQ uses `[16007,0,16007,0]` at `0x0b16b830`, shuffle `0x72`, double scale 2^-31 at `0x0b16b840`.
- [V] The checker emits all ten direct RNG call sites in reviewed code `0x401000..0x408646`; computed-call coverage is not established.
- [V] Sampler `ESI+0x190` owns a 16-byte node RNG: `0x405402..0x405437` derives it from the high double at the pointer stored in `[ESI+0x24c]` (scale 32768, conversion/shuffle/bias), or copies the global state if that double's bits are zero.
- [V] `0x405650/0x405657` swap node/global states; `0x40565e/0x4056d5` advance the node stream; `0x405730/0x405737` restore the outer global state and retain the advanced node state. Resetting only the global seed mid-run is invalid.
- [V] Allocator `0x40176b` uses GlobalAlloc flag 0x40 (zero initialization); tick `0x0b16bd20` is a node evaluation-cache stamp, not RNG, incremented 0→1 in initialization and once per stereo frame during synthesis.
- [V] Pinned T1 pre-thread dump confirms seed/multiplier/scale and tick=1; T11 records entry tick=0 and launch tick=1 but lacks explicit RNG bytes or node-local seed observations.
- [V] T11 resource digest covers `0x409100..0x43edbf`, including static seed/score/shaders but excluding RNG constants `0x4090b8..0x4090c7` and mutable RNG/node/physics allocations.
- [V] Saved bootstrap and synth-completion CONTEXTs show x87 CW=0x027f/MXCSR=0x1f80 in both runs; native `0x401665` sets interior MXCSR=0xffc0 and `0x401760` restores entry control bits. Completion controls do not attest interior synthesis mode.
- [V] Physics records `0x0b17bdf0`, `0x0b17be30`, `0x0b17be70`, `0x0b17beb0` are 0x40 bytes each; `0x406019` mutates prior position/velocity/rotation. Previous seconds starts at zero (`0x406454`); dt at `0x408291` is successive audio-derived seconds, not constant float 1/60.
- [?] S1: in each fresh run extend pre-forward CreateThread (`0x40639f`, return `0x4063a5`) with raw `0x0b16b800..0x0b16bd1f` (0x520 bytes), tick (4 bytes) and main-thread native FP; exclude allocation-pointer slots beyond the tick. Preserve bytes and compare hashes/decoded owners between runs.
- [?] S1: record synth-thread x87 CW/MXCSR immediately after `ldmxcsr` at `0x40166a`; record all four physics records at native entry `0x406379` and first timeline query `0x407b91`, plus previous seconds `[EBP-0x38]` and native main-thread FP there.
- [?] S2: at `0x40543e`, once per node initialization/activation, retain synth TID, ESI, the pointer from `[ESI+0x24c]` and its 16 pointee bytes, global RNG and node `[ESI+0x190]`; capture both RNG states before its first executed swap (`0x40563e`) and after (`0x40573e`, only paired with that swap). Match nodes by allocation/activation order, never cross-run pointer equality; retain explicit zero-hit coverage if no swap executes.

## Volume provenance and consumer
- [V] Atlas readback `0x4079d6` and 3D upload `0x407a58` share `0x0b17bff0`; both saved runs match all 33554432 atlas bytes to upload-source hash, 128³ RGBA32F, unpack `[4,0,0,0,0,0,0,0,0]`.
- [V] Native upload does no retiling: linear 3D index `x+128*y+16384*z` maps to atlas pixel `(x+128*y,z)`; shader coordinates are `(x+0.5,z+0.5,y)/128`. Atlas shader `0x409918` uses sin/fract coordinate hashing, independently of CPU RNG.
- [V] `0x407a13..0x407aa4` selects unit 0, binds/uploads level 0, sets min/mag LINEAR and S/T/R REPEAT; later 2D inputs use units 1 onward. Binding/upload success alone does not prove consumption.
- [V] Reconstructed stack shader arrays `0x4064e7..0x406dac` match all 234 timeline-program source observations per saved run; only program indices 20/21 define CLOUDS (observed handles 22/23, not portable identifiers).
- [V] Earliest static cloud-capable selection is row 6/beat 128/frame 5760/96 seconds, token 40, pass 20, program index 20, framebuffer descriptor 9 (table selector 10 minus one at `0x4082d0`, saved handle 10); program 21 starts at frame 7920.
- [V] Program 20 source `0x41d710` samples `uClouds` in Lighting; common source `0x4184b8` calls SampleClouds from the CLOUDS raymarch and blends cloud color/alpha into output.
- [V] All 27417 saved timeline draws per run have `cloud_location=-1`; the first nine draws/frame skip state setup via `0x4082df→0x4085c9` and retain the previous program. Their pass descriptors alone cannot attest sampled resources.
- [?] V1: acquire two fresh sequential runs through n=5762, executing every intervening frame; retain raw 5758…5762 and the map's earlier periodic/row endpoints. Record native row/local time and actual program-20 draw at `0x4085d1`/return `0x4085d7` on 5760…5762; saved early equality does not establish these pixels.
- [?] V1: at that draw record active uClouds location/unit/bound 3D texture, level-0 dimensions/format, effective texture/sampler-object filtering/wrap, program/source identity, FBO attachments/draw buffers, viewport and uTimeResolution. Read bound level-0 RGBA32F bytes at the first consumer and compare with the original upload-source hash, preserving pack/PBO/GL/FP state.
- [?] V1: retain/compare that pass's color attachments and final buffers between runs with downstream per-pass routing; combine executed active-sampler draw evidence with the linked Lighting path. A final-present unit-0 binding query alone is insufficient.
- [?] Probe records must bind run/build identity, native PC/TID/frame or synthesis phase, raw bytes/hash and before/after restoration evidence to retained artifacts; distinguish absent observations from observed zero-hit paths. T11 implements acquisition; T15 checks state, route, coverage and byte equality without inferring full-run acceptance from bounded probes.
