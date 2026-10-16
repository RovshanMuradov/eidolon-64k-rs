# Playback diagnostics

- [V] `bash tools/run python tools/capture/dependencies/gm_dls.py acquire` acquires/verifies the dependency pinned in `artifacts/reference/dependencies/gm-dls.json`.
- [V] `bash tools/run python tools/capture/prepare-native.py` checks the stopped T2 prefix, initializes a missing prefix through `tools/wine-headless`, installs identical banks in both Windows drivers directories, and extracts a hash-checked native copy; a differing installed bank is an error.
- [V] `bash tools/run bash tools/capture/smoke-native.sh` executes the native copy through the approved runner with a 600-second bound; `SMOKE_WINEDEBUG` overrides its diagnostic channels.
- [V] `bash tools/run bash tools/capture/diagnose-playback.sh` builds an x86 Windows debugger and launches it through the same runner; it restores one-shot breakpoints, counts successful timeline swaps using one hardware breakpoint, reads runtime metadata, and returns the native child's exit code.
- [V] The diagnostic samples statistics from eight small PCM windows at submission; synthesis may still be writing the buffer, so these statistics cannot establish complete or immutable audio.
- [V] Isolated audio proof uses `bash tools/run pactl load-module module-null-sink sink_name=eidolon_T2 rate=44100 channels=2`, sets `PULSE_SINK=eidolon_T2` for the run, and unloads the returned module ID afterward; monitor commands and measured levels are in `artifacts/reference/playback-manifest.json`.
- [V] D2 treats `WINE_EXIT` as authoritative; compositor exit `139` is acceptable only after native termination, and a timeout remains failure.
- [V] Playback-only diagnostics above retain real-time behavior; controlled proxy-B results are separate in `artifacts/reference/proxy-b-g1-20261016.json`.

## Proxy-B G1 diagnostic

- [V] `bash tools/run python tools/capture/proxy-b/probe.py --run-id <fresh-id> --capture-probe` builds PE32 proxy DLLs under `$EIDOLON_ROOT/.tools/capture/B/`, stages them beside a byte-identical demo, and uses the unattended runner with native/builtin overrides and a 300-second bound.
- [V] `tools/capture/proxy-b/build.py` preserves all installed backend export names/ordinals; forwarding trampolines save integer/EFLAGS/FXSAVE state, while a page-guard rendezvous installs application-IAT clocks and completion hooks at post-fixup entry.
- [V] The diagnostic gates cursor zero on synthesis completion, writes complete PCM directly, separately hashes its source memory again, and plans to stop after three successful timeline swaps; private audio routing is created and removed automatically.
- [V] The recorded first G1 failure precedes frame-zero readback: `GL_initial_error`, zero saved frames, native exit 125; no further B runtime was attempted after this failure.
- [?] The GL guard does not retain its numeric GL error or distinguish a preexisting error from state-query errors; the saved Win32 last-error value cannot resolve this ambiguity.
- [V] `bash tools/run python tools/capture/audit-proxy-b.py` rechecks the failure artifact, complete PCM hash/extent, ordered completion events, source/build hashes and released resources; it does not certify instrumentation fidelity or produce a reference PASS.
- [V] `artifacts/reference/proxy-b-g1-failure-review.json` lists unpassed gates and compressed error evidence; D3 requires the coordinator to record fallback A before further capture work.
