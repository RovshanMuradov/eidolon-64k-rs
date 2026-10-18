# Verification reports

Reports are keyed by the delivered executable's complete SHA-256. They describe
exploratory candidates and never set `production_accepted` to true. The large
acquisition evidence stays in the verifier checkout's ignored `.build/verify/`.

## `bf3e41ad84bedb37dd8d3b8b96f18868c5bee2a4190732605783cf4e08c54513`

44,101 bytes. Phase 1 is in progress; the full capture is running in
`.build/verify/full44101`.

The closed smoke acquisition (`smoke44101b`) matched all three frames, full PCM,
three sampled physics states, decoded sections, and physical restoration. Its
overall result is **FAIL**: Gamescope exited 139 during teardown, after
`CHILD_EXIT 0 stages=111`. Prefix, sink, and runner cleanup passed. The compositor
core confirms SIGSEGV during libc `exit`; the precise failing function remains
unsymbolized. No kernel OOM or NVIDIA Xid event was found in the checked window.

The earlier `smoke44101` attempt was stopped after the outer shell timeout killed
its supervisor during synthesis; it is excluded from media verification.

The public frame/PCM reference files match the pinned private native oracle.
Eighteen offline positive/corruption controls passed. Native Windows, final clean
rebuild, matched solo performance/resources, and formal acceptance remain open.
