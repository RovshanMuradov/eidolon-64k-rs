"""Native-backed offline capture protocol and standalone embedded-data fault controls."""
import hashlib
import json
from pathlib import Path
import struct
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"tools/verify/rust"))
import conformance as c
import runtime_events as runtime
import standalone
from test_conformance import native, vectors


@pytest.fixture(scope="session")
def ledger(native,vectors,tmp_path_factory):
    path=tmp_path_factory.mktemp("runtime")/"events.bin"
    locations={}; seq=0
    with path.open("wb") as f:
        f.write(b"EIDCAP01")
        def emit(kind,payload):
            nonlocal seq
            locations.setdefault(kind,f.tell()); seq+=1
            f.write(struct.pack("<4I",seq,99,kind,len(payload))+payload)
        digest=bytes.fromhex(native.manifest["audio"]["sha256"])
        state=native.states["first-query/physics"].read_bytes()
        emit(6,digest);emit(7,digest);emit(1,bytes(28)+state)
        rows=[i for i,r in enumerate(native.manifest["scenes"]) for _ in range(r["last"]-r["first"]+1)]
        for n,cursor,sec,local,_ in vectors:
            # Later physics is deliberately not called a native expected vector.
            query=struct.pack("<7I",n,cursor,sec,0,rows[n],local,0)+state
            emit(2,query);emit(3,query)
            emit(10,struct.pack("<16I",n,1920,1080,8,8,8,8,0,0,0,0,0,0x405,0,0,0))
            emit(8,struct.pack("<I",n)+bytes.fromhex(native.frames[n]["sha256"]))
            emit(4,query)
        emit(5,struct.pack("<7I",27000,19845000,0x43e10000,0x44160000,0xffffffff,0,0)+state)
        emit(9,digest)
    return path,locations


def test_complete_offline_ledger_is_not_runtime_acceptance(native,vectors,ledger):
    result=runtime.audit(ledger[0],native,vectors)
    assert result["frames"]==27000 and result["production_accepted"] is False


@pytest.mark.parametrize("fault",["truncated","extra","order","thread","time","state","pixels","pcm","stable","endpoint","layout"])
def test_runtime_faults(native,vectors,ledger,tmp_path,fault):
    path,at=ledger; raw=bytearray(path.read_bytes())
    if fault=="truncated": raw.pop()
    elif fault=="extra": raw+=b"\0"
    else:
        offsets={"order":at[2],"thread":at[2]+4,"time":at[2]+16+4,
                 "state":at[1]+16+28,"pixels":at[8]+16+4,"pcm":at[6]+16,
                 "stable":at[9]+16,"endpoint":at[5]+16,"layout":at[10]+16+4}
        raw[offsets[fault]]^=1
    target=tmp_path/"fault.bin";target.write_bytes(raw)
    try:
        with pytest.raises(ValueError):runtime.audit(target,native,vectors)
    finally:target.unlink()


def test_unexecuted_envelope_rejected(tmp_path):
    value=dict(schema="eidolon-rust-runtime-envelope-1",status="UNEXECUTED",request=None,events=None,pcm=None,process=None)
    path=tmp_path/"envelope.json";path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match="unexecuted/unclosed"):runtime.envelope(path,"0"*64)


@pytest.fixture(scope="session")
def embedded():
    result=c.load(c.CHECKOUT/"artifacts/verification/rust/standalone.json")
    directory=(c.DATA/result["output"]["path"]).parent
    return c.checked(directory/"embedded.bin",result["embedded"]["dump_sha256"])


def test_independent_standalone_output_and_assets(native,embedded):
    result=c.load(c.CHECKOUT/"artifacts/verification/rust/standalone.json")
    assert result["file_inputs_denied_during_render"] is True
    assert result["production_accepted"] is False
    assert c.exact_files(native.pcm,c.DATA/result["output"]["path"],c.PCM_BYTES)==c.PCM_BYTES
    assert standalone.closure(embedded)["instrument_pcm16_bytes"]==85548


@pytest.mark.parametrize("fault",["score","patch","wave","formant","truncated","extra"])
def test_embedded_closure_faults(embedded,tmp_path,fault):
    raw=bytearray(embedded.read_bytes())
    if fault=="truncated":raw.pop()
    elif fault=="extra":raw+=b"\0"
    else:
        offsets={"score":12,"patch":12+32143+4,"wave":12+32143+4+7744+4+8,"formant":len(raw)-1}
        raw[offsets[fault]]^=1
    path=tmp_path/"embedded.bin";path.write_bytes(raw)
    # Refreshing a candidate dump digest cannot change the native/source closure.
    c.checked(path,c.sha(path))
    with pytest.raises(ValueError):standalone.closure(path)
