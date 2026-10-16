#!/usr/bin/env python3
"""Bounded by probe.py; Frida transports control and injection bytes only."""
import argparse
import json
from pathlib import Path
import frida

def inject(pid,config,output):
    session=None
    try:
        session=frida.attach(pid)
        script=session.create_script(Path('tools/capture/frida-a/bootstrap.js').read_text())
        messages=[]
        script.on('message',lambda message,data:messages.append(message))
        script.load()
        result=script.exports_sync.inject(config)
        output.write_text(json.dumps({'frida':frida.__version__,'status':'injected',
                                     'result':result,'messages':messages},indent=2)+'\n')
        return 0
    except Exception as exc:
        output.write_text(json.dumps({'frida':frida.__version__,'status':'failed',
                                     'exception_type':type(exc).__name__,'error':str(exc)},indent=2)+'\n')
        return 1
    finally:
        if session: session.detach()

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('pid',type=int)
    parser.add_argument('config',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    raise SystemExit(inject(args.pid,json.loads(args.config.read_text()),args.output))
