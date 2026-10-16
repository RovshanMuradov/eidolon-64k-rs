#!/usr/bin/env python3
"""Close the observed resource inventory with explicit runtime roles and IPC checks."""
from collections import Counter
import io
import json
import os
from pathlib import Path
import re
import subprocess
import zstandard
from conformance import CHECKOUT,DATA,ROOT,load,checked,sha,need
from resources import records


def role(path,item,candidate,job):
    p=Path(path)
    need(not path.startswith(str(DATA/"reference")+"/"),"native reference resource")
    need(p.suffix.lower() not in (".pcm",".f32le",".rgba",".dls",".sf2",".wav"),"external media resource")
    if path==candidate:return "immutable production image"
    if p.is_dir():return "directory navigation"
    if path==str(job/"runner.log"):return "inherited diagnostic output"
    if path.startswith(("/proc/","/sys/","/dev/","/memfd:","/dmabuf:")):return "kernel/device/anonymous memory"
    if path.startswith(("/usr/","/etc/","/opt/cuda/","/var/lib/","/var/cache/")):return "system runtime"
    if path.startswith((str(DATA/"verification/rust/prefix")+"/","/tmp/opencode/eidolon/T24/prefix/")):return "fresh Wine runtime prefix"
    if path.startswith(("/run/","/tmp/")):return "runtime IPC/scratch"
    home=str(Path.home())
    if path.startswith((home+"/.cache/nvidia/GLCache/",home+"/.cache/fontconfig/")):return "driver/font runtime cache"
    if path.startswith((home+"/.local/share/fonts/",home+"/.local/share/vulkan/implicit_layer.d/",home+"/.nv/nvidia-application-profiles-rc.d/")):return "font/graphics runtime configuration"
    if path==home+"/.config/pulse/cookie":return "audio server authentication"
    raise ValueError("unclassified resource: "+path)


def review():
    pointer=load(CHECKOUT/"artifacts/verification/rust/resource-d26-all02.json")
    need(pointer["all_syscalls"] and not any(pointer[k] for k in ("successful_async_engines","unknown_syscalls","unresolved_successful_opens","unterminated_pids")),"syscall coverage incomplete")
    job=DATA/"verification/rust/resource-d26-all02";state=load(checked(job/"state.json",pointer["state_sha256"]))
    inventory=load(checked(DATA/pointer["inventory"],pointer["inventory_sha256"]));summary=inventory["summary"]
    roles={p:role(p,item,state["candidate"],job) for p,item in summary["inventory"].items()}
    # Internet-family connect calls are local-address route probes only if no
    # payload I/O succeeds before descriptor closure; port-zero alone is insufficient.
    network_pids={e["pid"] for e in summary["sockets"] if e["name"]=="connect" and "AF_INET" in e["args"]}
    prefixes=tuple(str(pid).encode()+b" " for pid in network_pids);active=set();probes=0;shm=[]
    def selected():
        with (job/"syscalls.zst").open("rb") as f:
            with zstandard.ZstdDecompressor().stream_reader(f) as stream:
                for raw in io.BufferedReader(stream):
                    if raw.startswith(prefixes) or any(k in raw for k in (b" shmget(",b" shmat(",b" shmctl(",b" shmdt(",b"<... shm")):
                        yield raw.decode()
    for e in records(selected()):
        if "name" not in e:continue
        name,args,value=e["name"],e["args"],e["value"]
        if name.startswith("shm"):shm.append(e)
        first=re.match(r"(0x[0-9a-f]+|\d+)",args)
        if not first:continue
        fd=int(first[1],16 if first[1].startswith("0x") else 10);key=(e["pid"],fd)
        if name=="connect" and "AF_INET" in args and value==0:
            need("port=htons(0)" in args,"non-route network endpoint");active.add(key);probes+=1
        if key in active and name in ("read","readv","recvmsg","recvfrom","recvmmsg","write","writev","sendmsg","sendto","sendmmsg"):
            need(value is None or value<=0,"network route socket transferred payload")
        if name=="close":active.discard(key)
    need(not active,"unclosed route socket")
    allocations=[e for e in shm if e["name"]=="shmget" and e["value"] is not None and e["value"]>=0]
    need(all("IPC_PRIVATE" in e["args"] for e in allocations),"foreign System V shared-memory lookup")
    ids={e["value"] for e in allocations}
    for e in shm:
        if e["name"] in ("shmat","shmctl") and e["value"] is not None and e["value"]>=0:need(int(e["args"].split(",",1)[0]) in ids,"unbound System V segment")
    leftovers=[]
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():continue
        try:
            if b"WINEPREFIX=/tmp/opencode/eidolon/T24/prefix" in (p/"environ").read_bytes().split(b"\0") and "wine" in str((p/"exe").resolve()):leftovers.append(int(p.name))
        except OSError:pass
    need(not leftovers and "eidolon_T24_resources" not in subprocess.check_output(["pactl","list","short","sinks"],text=True),"resource run cleanup")
    for key in ("pid","runner_pid"):need(not Path(f"/proc/{state[key]}").exists(),"resource supervisor survives")
    result=dict(status="OBSERVED_RUNTIME_RESOURCE_CLOSURE",capture_review_sha256=sha(CHECKOUT/"artifacts/verification/rust/resource-d26-all02.json"),
                records=pointer["records"],resource_roles=dict(Counter(roles.values())),classified_resources=len(roles),route_probe_connects=probes,
                route_probe_payload_transfers=0,private_system_v_segments=len(ids),cleanup_verified=True,external_demo_media_resources=0,
                immutable_file_binding_scope="Post-run hashes bind regular files; mutable runtime cache/registry content is not claimed immutable at each read",
                runtime_resource_closure=True,production_accepted=False)
    (CHECKOUT/"artifacts/verification/rust/resource-closure.json").write_text(json.dumps(result,indent=2)+"\n");print(json.dumps(result))


if __name__=="__main__":review()
