# GM DLS provision

- [V] Pin, provenance, format, sample ordering and tool versions: [manifest](../../../artifacts/reference/dependencies/gm-dls.json).
- [V] Acquire from the archived official distribution or recheck cached sources: `bash tools/run python tools/capture/dependencies/gm_dls.py acquire`; requires Python, `bsdtar` and OpenSSL; binaries remain in `$EIDOLON_DATA/reference/dependencies/`.
- [V] Verify the ready bank offline: `bash tools/run python tools/capture/dependencies/gm_dls.py verify`; `PASS` requires exact size/SHA-256, nested RIFF bounds, instrument count, wave-pool offsets, PCM formats and physical sample ordering.
- [V] Verify a copied bank: append `--bank /absolute/path/gm.dls` to the verification command; missing, changed or structurally mismatched banks exit 1.
- [V] Acquisition checks the package signature mathematically against its embedded pinned signer; certificate-chain trust, timestamp and revocation are outside that check; see `signature_check` in the manifest.
- [V] The vendor's `directx.inf` maps `gm16.dls` to `gm.dls`; acquisition preserves the bank's bytes and retains that INF and `gmreadme.txt` under the external `source/` directory.
- [V] T2 installation into an already initialized, stopped prefix: copy the bank to `$WINEPREFIX/drive_c/windows/system32/drivers/gm.dls`; for a 64-bit prefix also copy identical bytes to `$WINEPREFIX/drive_c/windows/syswow64/drivers/gm.dls`, creating the drivers directories if absent.
- [V] Verify both installed paths before launching; inspect an existing different bank before replacing it and record the pinned manifest in the capture environment.
- [?] The original author's bank hash/version and live recovery remain unknown; T2 must verify the resolved file, loaded sample 127 and full playback in its assigned GPU slot.
