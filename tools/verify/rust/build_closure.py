#!/usr/bin/env python3
"""Resolve independently generated compiler dependencies against the pinned source archive."""
import json
from pathlib import Path
from conformance import CHECKOUT,DATA,load,checked,sha,need,pe_identity


def audit():
    p=load(CHECKOUT/"artifacts/verification/rust/rebuild.json");m=load(checked(DATA/p["result"],p["sha256"]))
    candidate=load(CHECKOUT/"artifacts/rust/engine/candidate.json");bundle=Path(candidate["directory"])
    inventory=load(checked(bundle/"source-inventory.json",m["inventory_sha256"]))
    source=Path(m["cwd"])
    primary=m["dependency_files"]["i686-pc-windows-gnu/release/eidolon-runtime.d"]
    dependencies=primary.splitlines()[0].split(": ",1)[1].split()
    inputs={}
    for name in dependencies:
        path=Path(name);need(path.is_relative_to(source),"compiler input outside independent source snapshot")
        relative=str(path.relative_to(source));need(relative in inventory,"compiler dependency absent from source inventory")
        inputs[relative]=inventory[relative]["sha256"]
    need(len([p for p in inputs if p.startswith("src/audio/") and p.endswith(".rs")])==15,"audio compiler-module closure")
    identity=pe_identity(m["executable"])
    expected=load(checked(bundle/"build.json",load(bundle/"candidate.json")["files"]["build.json"]["sha256"]))["runtime_candidate"]["imports"]
    need(identity["imports"]==expected,"published/rebuilt PE import closure")
    result=dict(status="INDEPENDENT_COMPILER_INPUT_CLOSURE",rebuild_result_sha256=p["sha256"],inputs=inputs,
                production_identity=identity,scope="Compiler inputs and PE imports; dynamic file-open trace is separate",production_accepted=False)
    (CHECKOUT/"artifacts/verification/rust/build-closure.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(dict(status=result["status"],inputs=len(inputs),imports=len(expected))))


if __name__=="__main__":audit()
