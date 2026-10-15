#!/usr/bin/env python3
"""Prepare a stopped T2 prefix and byte-identical native/dependency copies."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

from dependencies.gm_dls import check_blob, inspect_bank, require


def main():
    require("EIDOLON_DATA" in os.environ, "invoke through bash tools/run")
    scratch = Path("/tmp/opencode/eidolon/T2")
    prefix = scratch / "prefix"
    marker = f"WINEPREFIX={prefix}".encode()
    for process in Path("/proc").glob("[0-9]*/environ"):
        try:
            require(marker not in process.read_bytes().split(b"\0"),
                    f"prefix is busy: {process.parent.name}")
        except (PermissionError, ProcessLookupError, FileNotFoundError):
            continue
    if not (prefix / "system.reg").exists():
        env = dict(os.environ, AGENT="T2", WINEDEBUG="-all")
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
        subprocess.run(["bash", "tools/run", "tools/wine-headless", "cmd", "/c", "exit", "0"],
                       env=env, check=True)

    manifest = json.loads(Path("artifacts/reference/dependencies/gm-dls.json").read_text())
    bank = (Path(os.environ["EIDOLON_DATA"]) / "reference/dependencies/gm.dls").read_bytes()
    check_blob(bank, manifest["bank"])
    require(inspect_bank(bank) == manifest["dls"], "DLS metadata differs")
    destinations = [prefix / f"drive_c/windows/{arch}/drivers/gm.dls"
                    for arch in ("system32", "syswow64")]
    for path in destinations:
        if path.exists():
            require(path.read_bytes() == bank, f"inspect differing existing bank before replacing: {path}")
    for path in destinations:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bank)
        check_blob(path.read_bytes(), manifest["bank"])

    old = json.loads(Path("artifacts/reference/wine-smoke-manifest.json").read_text())["input"]
    archive = Path(old["archive"])
    require(hashlib.sha256(archive.read_bytes()).hexdigest() == old["archive_sha256"], "archive hash")
    with zipfile.ZipFile(archive) as z:
        executable = z.read(old["exe"])
    require(hashlib.sha256(executable).hexdigest() == old["exe_sha256"], "native hash")
    destination = scratch / "input" / old["exe"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(executable)
    print(json.dumps({"status": "prepared", "native": str(destination),
                      "dependency_manifest": "artifacts/reference/dependencies/gm-dls.json",
                      "installed_bank_paths": [str(p) for p in destinations]}))


if __name__ == "__main__":
    main()
