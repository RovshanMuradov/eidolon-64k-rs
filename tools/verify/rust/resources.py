#!/usr/bin/env python3
"""Audit complete compressed ptrace records; distinguish selected-I/O from all-syscall coverage."""
from collections import Counter,defaultdict
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import zstandard
from conformance import CHECKOUT,DATA,ROOT,load,checked,sha,need

HEADER=re.compile(r"^(\d+) (\d+\.\d+) (.*)$")
ANNOTATION=re.compile(r"(?:\d+|AT_FDCWD)<([^>]+)>")
TOKENS=re.compile(r'"(?:\\.|[^"\\])*"|(?:\d+|AT_FDCWD)<([^>]+)>')
RESULT=re.compile(r"^(-?0x[0-9a-f]+|-?\d+)(?:\b|<)")
OPEN={"open","openat","openat2","creat","open_by_handle_at"}
ASYNC={"io_uring_setup","io_setup"}


def annotations(text):
    # Quoted payload bytes are data, even if they happen to resemble fd<path>.
    return [match[1] for match in TOKENS.finditer(text) if match[1] is not None]


def records(lines):
    pending={}
    for line_number,line in enumerate(lines,1):
        match=HEADER.match(line.rstrip("\n"));need(match is not None,f"unparsed trace header line {line_number}")
        pid,timestamp,body=match.groups();pid=int(pid)
        if body.startswith("+++ "):
            abandoned=pending.pop(pid,None)
            yield dict(pid=pid,time=timestamp,terminal=body,abandoned=abandoned,line=line_number)
            continue
        if body.startswith("<... "):
            resumed=re.match(r"<\.\.\. (\w+) resumed>(.*)",body);need(resumed and pid in pending,"unpaired resumed syscall")
            start,name,prefix=pending.pop(pid);need(name==resumed[1],"resumed syscall name differs")
            body=prefix+resumed[2]
        else:start=line_number
        if body.endswith("<unfinished ...>"):
            name=body.split("(",1)[0];need(pid not in pending,"duplicate pending syscall")
            pending[pid]=(start,name,body[:-len("<unfinished ...>")]);continue
        call=re.match(r"^(\w+)\((.*)\)\s+=\s+(.*)$",body)
        need(call is not None,f"unparsed syscall line {line_number}: {body[:160]}")
        name,args,result=call.groups()
        value=RESULT.match(result)
        token=value[1] if value else None
        base=16 if token and "0x" in token else (8 if token and len(token)>1 and token.startswith("0") else 10)
        yield dict(pid=pid,time=timestamp,name=name,args=args,result=result,value=int(token,base) if token else None,line=start)
    need(not pending,"unterminated live trace records")


def category(path,candidate):
    if path==candidate:return "immutable_candidate"
    if path.startswith(str(DATA/"reference")+"/"):return "FORBIDDEN_REFERENCE_INPUT"
    if path.startswith(str(DATA/"verification/rust/prefix")+"/") or path.startswith("/tmp/opencode/eidolon/T24/prefix/"):return "wine_prefix"
    if path.startswith(str(DATA)+"/"):return "project_data_REVIEW"
    if path.startswith(("/usr/","/etc/","/opt/cuda/","/var/lib/","/var/cache/")):return "system_runtime"
    if path.startswith(("/proc/","/sys/","/dev/")):return "kernel_or_device"
    if path.startswith(("/run/","/tmp/")):return "runtime_ipc_or_scratch"
    if path.startswith(str(ROOT)+"/"):return "launcher_checkout_REVIEW"
    if path.startswith(str(Path.home()/".cache")+"/"):return "host_cache_REVIEW"
    if path.startswith(str(Path.home()/".config")+"/"):return "host_configuration_REVIEW"
    return "unclassified_REVIEW"


def summarize(lines,candidate):
    calls=Counter();pids=set();exited={};executions=[];resources=defaultdict(lambda:dict(calls=Counter(),pids=set(),open_flags=set()))
    candidate_mappers=set();async_success=[];sockets=[];abandoned=[];unknown=[];unresolved_opens=[]
    for event in records(lines):
        pid=event["pid"];pids.add(pid)
        if "terminal" in event:
            exited[pid]=event["terminal"]
            if event["abandoned"]:abandoned.append(dict(pid=pid,pending=event["abandoned"]))
            continue
        name=event["name"];calls[name]+=1;args=event["args"];value=event["value"]
        if name.startswith("syscall_"):unknown.append(event)
        if name in ("execve","execveat") and value==0:executions.append(dict(pid=pid,args=args))
        if name in ASYNC and value is not None and value>=0:async_success.append(event)
        if name in ("connect","socket","socketpair") and value is not None and value>=0:sockets.append(event)
        if value is None or value<0:continue
        if name in OPEN and not ANNOTATION.search(event["result"]):unresolved_opens.append(event)
        # All successful descriptor-bearing observations are an over-approximation
        # of inputs, including descriptors transferred via SCM_RIGHTS and mmaps.
        for path in annotations(args+" "+event["result"]):
            if not path.startswith("/"):continue
            item=resources[path];item["calls"][name]+=1;item["pids"].add(pid)
            if name in OPEN:item["open_flags"].add(args)
            if path==candidate and name in ("mmap","mmap2"):candidate_mappers.add(pid)
    inventory={path:dict(category=category(path,candidate),calls=dict(item["calls"]),pids=sorted(item["pids"]),open_flags=sorted(item["open_flags"])) for path,item in sorted(resources.items())}
    return dict(calls=dict(calls),pids=sorted(pids),exit_records=exited,unterminated_pids=sorted(pids-exited.keys()),
                executions=executions,inventory=inventory,candidate_mappers=sorted(candidate_mappers),
                successful_async_engines=async_success,sockets=sockets,abandoned_at_exit=abandoned,unknown_syscalls=unknown,
                unresolved_successful_opens=unresolved_opens)


def review(name):
    job=DATA/"verification/rust"/name;state=load(job/"state.json")
    need(state["phase"]=="closed","trace acquisition still active")
    need(state["trace"]["complete"] and not state["trace"]["errors"],"trace compressor failed")
    checked(job/"resources.py",state["source_sha256"]);checked(job/"syscalls.zst",state["trace_sha256"])
    checked(job/"runner.log",state["runner_log_sha256"]);checked(state["candidate"],state["candidate_sha256"])
    need(state["candidate_sha256"]==state["candidate_after_sha256"],"candidate changed")
    digest=hashlib.sha256();size=0;count=0
    def lines():
        nonlocal size,count
        with (job/"syscalls.zst").open("rb") as source:
            with zstandard.ZstdDecompressor().stream_reader(source) as decoded:
                for line in io.BufferedReader(decoded):
                    digest.update(line);size+=len(line);count+=1
                    yield line.decode("utf-8",errors="strict")
    summary=summarize(lines(),state["candidate"])
    need(size==state["trace"]["raw_bytes"] and count==state["trace"]["lines"] and digest.hexdigest()==state["trace"]["raw_sha256"],"decoded trace coverage/hash")
    log=(job/"runner.log").read_text(errors="replace")
    natural=re.search(r"EIDOLON_RUNTIME mode=playback reason=natural_exit queries=(\d+) frames=(\d+) terminal_cursor=(\d+)",log)
    need(state["exit_code"]==0 and natural and "WINE_EXIT=0 GAMESCOPE_EXIT=0" in log,"trace run did not complete naturally")
    need(not re.search(r"strace:.*(?:detached|Operation not permitted|No space|write.*failed)|TIMEOUT|EIDOLON_RUNTIME error:",log),"trace/runtime error")
    need(summary["candidate_mappers"],"candidate was not mapped in traced tree")
    bindings={}
    for path in summary["inventory"]:
        file=Path(path)
        if file.is_file() and not path.startswith(("/proc/","/sys/","/dev/")):
            try:bindings[path]=dict(bytes=file.stat().st_size,sha256=sha(file))
            except OSError:pass
    inventory=job/"resource-inventory.json";inventory.write_text(json.dumps(dict(summary=summary,post_run_file_bindings=bindings),indent=2)+"\n")
    categories=Counter(item["category"] for item in summary["inventory"].values())
    all_syscalls="trace=all" in state["command"]
    if state.get("wine_trace_shim_sha256"):
        shim=checked(job/"bin/wine",state["wine_trace_shim_sha256"])
        need("-e trace=all" in shim.read_text() and state["trace_environment"]["EIDOLON_TRACE_EXE"]==state["candidate"],"target-only trace configuration")
        need(any('"/usr/bin/wine"' in e["args"] and state["candidate"] in e["args"] for e in summary["executions"]),"candidate Wine exec missing")
        all_syscalls=True
    result=dict(schema="eidolon-resource-review-1",job=name,status="ALL_SYSCALLS_CAPTURED_REVIEW_PENDING" if all_syscalls else "SELECTED_IO_CAPTURED_NOT_COMPLETE_SYSCALL_CLOSURE",
                state_sha256=sha(job/"state.json"),inventory=str(inventory.relative_to(DATA)),inventory_sha256=sha(inventory),
                candidate_sha256=state["candidate_sha256"],all_syscalls=all_syscalls,raw_bytes=size,records=count,
                process_threads=len(summary["pids"]),candidate_mappers=summary["candidate_mappers"],resource_categories=dict(categories),
                successful_async_engines=len(summary["successful_async_engines"]),unknown_syscalls=len(summary["unknown_syscalls"]),
                unresolved_successful_opens=len(summary["unresolved_successful_opens"]),
                unterminated_pids=summary["unterminated_pids"],natural_endpoint=dict(queries=int(natural[1]),frames=int(natural[2]),cursor=int(natural[3])),
                runtime_resource_closure=False,production_accepted=False)
    (CHECKOUT/f"artifacts/verification/rust/{name}.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result));return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("name");review(parser.parse_args().name)
