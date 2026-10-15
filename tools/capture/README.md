# Playback diagnostics

- [V] `bash tools/run python tools/capture/dependencies/gm_dls.py acquire` acquires/verifies the dependency pinned in `artifacts/reference/dependencies/gm-dls.json`.
- [V] `bash tools/run python tools/capture/prepare-native.py` checks the stopped T2 prefix, initializes a missing prefix through `tools/wine-headless`, installs identical banks in both Windows drivers directories, and extracts a hash-checked native copy; a differing installed bank is an error.
- [V] `bash tools/run bash tools/capture/smoke-native.sh` executes the native copy through the approved runner with a 600-second bound; `SMOKE_WINEDEBUG` overrides its diagnostic channels.
- [V] `bash tools/run bash tools/capture/diagnose-playback.sh` builds an x86 Windows debugger and launches it through the same runner; it restores one-shot breakpoints, counts successful timeline swaps using one hardware breakpoint, reads runtime metadata, and returns the native child's exit code.
- [V] The diagnostic samples statistics from eight small PCM windows at submission; synthesis may still be writing the buffer, so these statistics cannot establish complete or immutable audio.
- [V] Isolated audio proof uses `bash tools/run pactl load-module module-null-sink sink_name=eidolon_T2 rate=44100 channels=2`, sets `PULSE_SINK=eidolon_T2` for the run, and unloads the returned module ID afterward; monitor commands and measured levels are in `artifacts/reference/playback-manifest.json`.
- [V] D2 treats `WINE_EXIT` as authoritative; compositor exit `139` is acceptable only after native termination, and a timeout remains failure.
- [?] Exact framebuffer readback, fixed-clock replay, full PCM acquisition and repeatability require the shared-checkpoint capture-method decision; the diagnostic produces no reference-format capture.
