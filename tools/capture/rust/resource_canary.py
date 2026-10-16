#!/usr/bin/env python3
"""Linux-only tracer coverage control: fork/thread, FD transfer, dup, read and mmap."""
import array
import mmap
import os
from pathlib import Path
import socket
import sys
import threading

path=Path(sys.argv[1]);path.write_bytes(b"EIDOLON_RESOURCE_CANARY\n"*1024)
left,right=socket.socketpair();fd=os.open(path,os.O_RDONLY)
child=os.fork()
if child==0:
    left.close();os.close(fd)
    _,ancillary,_,_=right.recvmsg(1,socket.CMSG_SPACE(array.array("i").itemsize))
    received=array.array("i");received.frombytes(ancillary[0][2]);dup=os.dup(received[0])
    expected=b"EIDOLON_RESOURCE_CANARY"
    assert os.read(dup,len(expected))==expected
    with mmap.mmap(dup,0,access=mmap.ACCESS_READ) as image:assert image[:7]==b"EIDOLON"
    worker=threading.Thread(target=lambda:os.pread(dup,16,0));worker.start();worker.join()
    os.close(dup);os.close(received[0]);right.close();os._exit(0)
right.close();left.sendmsg([b"x"],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array("i",[fd]))]);os.close(fd);left.close()
assert os.waitpid(child,0)[1]==0
