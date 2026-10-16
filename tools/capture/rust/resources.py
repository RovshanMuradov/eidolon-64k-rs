#!/usr/bin/env python3
"""Trace the complete approved launcher process tree; stream-compress without sampling."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import zstandard
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"verify/rust"))
from conformance import CHECKOUT,DATA,ROOT,checked,load,sha,need

CALLS="%file,%process,read,readv,pread64,preadv,preadv2,write,writev,pwrite64,pwritev,pwritev2,mmap,mmap2,munmap,close,close_range,dup,dup2,dup3,fcntl,recvmsg,recvmmsg,sendmsg,sendmmsg,recvfrom,sendto,connect,socket,socketpair,accept,accept4,memfd_create,ioctl,io_uring_setup,io_uring_enter,io_uring_register,io_setup,io_submit,io_getevents,splice,copy_file_range,sendfile"
RAW="read,readv,pread64,preadv,preadv2,write,writev,pwrite64,pwritev,pwritev2,ioctl"


def run(name,filtered=False,target_only=False):
    root=DATA/"verification/rust";job=root/name;job.mkdir(exist_ok=False)
    for pattern in ("live-*/state.json","playback-*/state.json","resource-*/state.json"):
        for previous in root.glob(pattern):need(load(previous)["phase"]=="closed","another target job is active")
    pointer=load(CHECKOUT/"artifacts/rust/engine/candidate.json");bundle=Path(pointer["directory"])
    checked(bundle/"candidate.json",pointer["manifest_sha256"]);exe=checked(bundle/"eidolon-runtime.exe",pointer["executable_sha256"])
    tools=root/"resource-tools";tool=load(tools/"manifest.json");tracer=checked(tools/"strace",tool["exe_sha256"])
    reserve=150000000 if target_only else 350000000
    existing=sum(p.stat().st_size for p in DATA.rglob("*") if p.is_file());need(existing+reserve<30000000000,"trace reservation exceeds storage budget")
    prefix=root/"prefix";scratch=Path("/tmp/opencode/eidolon/T24")
    need((scratch/"prefix").resolve()==prefix.resolve(),"unexpected Wine prefix")
    if prefix.exists():shutil.rmtree(prefix)
    subprocess.run(["cp","-a","--reflink=auto",str(ROOT/".tools/capture/T11-prefix-baseline"),str(prefix)],check=True)
    sink="eidolon_T24_resources";module=subprocess.check_output(["pactl","load-module","module-null-sink",f"sink_name={sink}"],text=True).strip()
    env=dict(os.environ,AGENT="T24",WINE_TIMEOUT="1200",WINEDEBUG="-all",PULSE_SINK=sink,WINEDLLOVERRIDES="winemenubuilder.exe,mscoree,mshtml=d")
    if target_only:
        fifo=job/"trace.pipe";os.mkfifo(fifo)
        read_fd=os.open(fifo,os.O_RDONLY|os.O_NONBLOCK);write_fd=os.open(fifo,os.O_WRONLY|os.O_NONBLOCK);os.set_blocking(read_fd,True)
    else:read_fd,write_fd=os.pipe()
    command=[str(tracer),"-f","-ttt","-yy","-s","4096","-e",f"trace={CALLS if filtered else 'all'}","-e",f"raw={RAW}","-e","signal=none","-o",f"/proc/self/fd/{write_fd}",
             "bash","tools/run","tools/wine-headless",str(exe),"--play"]
    shim=None
    if target_only:
        bin_dir=job/"bin";bin_dir.mkdir();shim=bin_dir/"wine"
        shutil.copyfile(CHECKOUT/"tools/capture/rust/wine-trace",shim);shim.chmod(0o755)
        env.update(PATH=str(bin_dir)+":"+env["PATH"],EIDOLON_TRACE_EXE=str(exe),EIDOLON_STRACE=str(tracer),EIDOLON_TRACE_FIFO=str(fifo))
        command=["bash","tools/run","tools/wine-headless",str(exe),"--play"]
    shutil.copyfile(__file__,job/"resources.py")
    state=dict(schema="eidolon-rust-resource-trace-1",phase="running",name=name,pid=os.getpid(),sid=os.getsid(0),
               started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),command=command,candidate=str(exe),candidate_sha256=sha(exe),
               source_sha256=sha(job/"resources.py"),tracer=tool,wine_launcher_sha256=sha(CHECKOUT/"tools/wine-headless"),
               environment={k:env[k] for k in ("AGENT","WINE_TIMEOUT","WINEDEBUG","PULSE_SINK","WINEDLLOVERRIDES")},
               storage=dict(existing_bytes=existing,reserved_bytes=reserve,limit_bytes=30000000000),all_syscalls=not filtered,
               trace_scope="Wine candidate exec and all descendants" if target_only else "approved launcher and all descendants",
               wine_trace_shim_sha256=sha(shim) if shim else None,
               trace_environment={k:v for k,v in env.items() if k.startswith("EIDOLON_TRACE_") or k=="EIDOLON_STRACE"},production_accepted=False)
    def persist():
        temp=job/"state.tmp";temp.write_text(json.dumps(state,indent=2)+"\n");temp.replace(job/"state.json")
    persist();digest=hashlib.sha256();trace=dict(raw_bytes=0,lines=0,complete=False,errors=[])
    def consume():
        try:
            with os.fdopen(read_fd,"rb") as source,(job/"syscalls.zst").open("wb") as file:
                with zstandard.ZstdCompressor(level=5).stream_writer(file,closefd=False) as out:
                    while data:=source.read(1<<20):
                        digest.update(data);trace["raw_bytes"]+=len(data);trace["lines"]+=data.count(b"\n");out.write(data)
                        need(file.tell()<reserve-10000000,"compressed trace exceeded reservation")
                trace["complete"]=True
        except BaseException as exc:trace["errors"].append(repr(exc))
        trace["raw_sha256"]=digest.hexdigest()
    worker=threading.Thread(target=consume);worker.start();started=time.monotonic()
    try:
        with (job/"runner.log").open("wb") as log:
            process=subprocess.Popen(command,cwd=CHECKOUT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,pass_fds=() if target_only else (write_fd,))
            if not target_only:os.close(write_fd)
            state["runner_pid" if target_only else "tracer_pid"]=process.pid;persist()
            result=process.wait()
            if target_only:os.close(write_fd)
        worker.join()
    finally:subprocess.run(["pactl","unload-module",module],check=False)
    state.update(phase="closed",exit_code=result,elapsed_seconds=time.monotonic()-started,trace=trace,
                 trace_sha256=sha(job/"syscalls.zst"),trace_bytes=(job/"syscalls.zst").stat().st_size,
                 runner_log_sha256=sha(job/"runner.log"),candidate_after_sha256=sha(exe),finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    persist();print(json.dumps(dict(job=str(job),exit_code=result,trace=trace)),flush=True)


if __name__=="__main__":run(sys.argv[1],"--filtered" in sys.argv[2:],"--target-only" in sys.argv[2:])
