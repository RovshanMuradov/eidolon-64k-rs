#!/usr/bin/env python3
"""Independent clean offline rebuild directly from the immutable publication archive."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
import sys
from conformance import CHECKOUT,DATA,load,checked,sha,need,exact_files


def rebuild(job_name):
    p=load(CHECKOUT/"artifacts/rust/engine/candidate.json");bundle=Path(p["directory"])
    m=load(checked(bundle/"candidate.json",p["manifest_sha256"]))
    for name,item in m["files"].items():checked(bundle/name,item["sha256"])
    job=DATA/"verification/rust"/job_name;job.mkdir(exist_ok=False)
    source=Path("/tmp/opencode/eidolon")/("T24-"+job_name);source.mkdir(exist_ok=False)
    target=job/"target";temporary=job/"tmp";temporary.mkdir()
    inventory=load(bundle/"source-inventory.json")
    with tarfile.open(bundle/"source.tar") as archive:
        need({x.name for x in archive.getmembers()}==set(inventory),"source inventory coverage")
        for item in archive.getmembers():
            need(item.isfile() and not Path(item.name).is_absolute() and ".." not in Path(item.name).parts,"unsafe archive member")
            data=archive.extractfile(item).read();want=inventory[item.name]
            need(len(data)==want["bytes"] and hashlib.sha256(data).hexdigest()==want["sha256"],"source member identity")
            path=source/item.name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    env=dict(os.environ,CARGO_TARGET_DIR=str(target),TMPDIR=str(temporary))
    env.pop("CARGO_INCREMENTAL",None) # Preserve the published Cargo profile fingerprint.
    for key in ("RUSTFLAGS","CARGO_ENCODED_RUSTFLAGS","RUSTC_WRAPPER","RUSTC_WORKSPACE_WRAPPER"):env.pop(key,None)
    command=["cargo","build","--locked","--offline","--release","--target","i686-pc-windows-gnu","--bin","eidolon-runtime"]
    need(not target.exists(),"build directory was not empty")
    started=time.monotonic()
    with (job/"build.log").open("wb") as log:subprocess.run(command,cwd=source,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    exe=target/"i686-pc-windows-gnu/release/eidolon-runtime.exe"
    exact_files(bundle/"eidolon-runtime.exe",exe,728576)
    shutil.copyfile(exe,job/"eidolon-runtime.exe")
    dependencies={str(f.relative_to(target)):f.read_text() for f in target.rglob("*.d")}
    fingerprints={str(f.relative_to(target)):load(f) for f in target.rglob("bin-eidolon-runtime.json")}
    result=dict(status="INDEPENDENT_CLEAN_BUILD_EXACT",candidate_sha256=sha(exe),source_commit=p["source_commit"],
                source_archive_sha256=sha(bundle/"source.tar"),inventory_sha256=sha(bundle/"source-inventory.json"),
                source_files=len(inventory),command=command,cwd=str(source),target_initially_absent=True,
                versions={tool:subprocess.check_output([tool,"--version"],text=True).splitlines()[0] for tool in ("rustc","cargo","i686-w64-mingw32-gcc")},
                elapsed_seconds=time.monotonic()-started,dependency_files=dependencies,fingerprints=fingerprints,
                build_log_sha256=sha(job/"build.log"),ancestor_config_isolated=True,
                executable=str(job/"eidolon-runtime.exe"),production_accepted=False)
    (job/"result.json").write_text(json.dumps(result,indent=2)+"\n")
    # Preserve source, output and dependency inventory; remove reproducible compiler scratch only.
    shutil.rmtree(target);shutil.rmtree(temporary);shutil.rmtree(source)
    pointer=dict(status=result["status"],result=str((job/"result.json").relative_to(DATA)),sha256=sha(job/"result.json"),
                 candidate_sha256=result["candidate_sha256"],elapsed_seconds=result["elapsed_seconds"],production_accepted=False)
    (CHECKOUT/"artifacts/verification/rust/rebuild.json").write_text(json.dumps(pointer,indent=2)+"\n")
    print(json.dumps(pointer))


if __name__=="__main__":rebuild(sys.argv[1])
