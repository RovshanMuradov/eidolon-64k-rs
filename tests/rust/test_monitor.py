"""Complete-prefix and corruption tests; monitor never executes/signals a process."""
from pathlib import Path
import struct
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"tools/verify/rust"))
import conformance as c
from monitor_full import bounded_records, native_times, prefix, closure_status, exact_retained


@pytest.fixture(scope="module")
def native():return c.Native()


@pytest.fixture(scope="module")
def times(native):return native_times(native)


@pytest.fixture(scope="module")
def captured():
    return (c.DATA/"verification/rust/live-d26-02/output/events.bin").read_bytes()


def test_real_short_prefix(native,times,captured):
    records,pending=bounded_records(captured,closed=True)
    result,_=prefix(records,native,times)
    assert pending==0 and result["post_presents"]==3 and result["frame_mismatches"]==0
    assert result["endpoint"] is False and result["initial_physics"] is True


@pytest.mark.parametrize("cut",[1,15,16,17,100,299])
def test_active_tail_is_not_claimed_complete(native,times,captured,cut):
    raw=captured[:-cut]
    records,pending=bounded_records(raw)
    result,_=prefix(records,native,times)
    assert result["post_presents"]==2 and pending>0
    with pytest.raises(ValueError,match="truncated"):bounded_records(raw,closed=True)


@pytest.mark.parametrize("fault",["sequence","thread","kind","size","magic"])
def test_malformed_complete_header_rejected(captured,fault):
    raw=bytearray(captured)
    offsets={"sequence":8,"thread":8+48+4,"kind":16,"size":20,"magic":0}
    if fault=="kind":raw[offsets[fault]]=255
    else:raw[offsets[fault]]^=1
    with pytest.raises(ValueError):bounded_records(raw)


def test_pixel_difference_is_preserved_for_active_job(native,times,captured):
    records,_=bounded_records(captured)
    for i,(kind,payload) in enumerate(records):
        if kind==8 and struct.unpack_from("<I",payload)[0]==1:
            data=bytearray(payload);data[4]^=1;records[i]=(kind,bytes(data));break
    result,_=prefix(records,native,times)
    assert result["frame_mismatches"]==1 and result["first_frame_mismatch"]["n"]==1
    assert result["post_presents"]==3


def test_consistently_shifted_snapshots_are_not_native(native,times,captured):
    records,_=bounded_records(captured)
    for i,(kind,payload) in enumerate(records):
        if kind in (2,3,4) and struct.unpack_from("<I",payload)[0]==1:
            data=bytearray(payload);data[8]^=1;records[i]=(kind,bytes(data))
    result,_=prefix(records,native,times)
    assert result["time_mismatches"]==1 and result["first_time_mismatch"]["n"]==1


def test_reordered_whole_records_fail(native,times,captured):
    records,_=bounded_records(captured);records[3],records[4]=records[4],records[3]
    with pytest.raises(ValueError,match="order"):prefix(records,native,times)


@pytest.mark.parametrize("exit_code,complete,natural,errors,differences,cleanup,expected",[
    (0,True,True,[],0,False,"CLOSED_EXACT_FILES"),
    (124,True,True,[],0,False,"CLOSED_FAILED"),
    (0,True,True,["waveOut cleanup failed"],0,False,"CLOSED_FAILED"),
    (0,False,True,[],0,False,"CLOSED_INCOMPLETE"),
    (0,True,False,[],0,False,"CLOSED_INCOMPLETE"),
    (0,True,True,[],1,False,"CLOSED_WITH_DIFFERENCES"),
    (0,True,True,[],0,True,"CLOSED_EXACT_FILES_CLEANUP_PENDING"),
])
def test_full_output_does_not_hide_exit_endpoint_or_cleanup_failure(exit_code,complete,natural,errors,differences,cleanup,expected):
    resources=dict(wine_pids=[],private_sink_present=cleanup,runner_alive=False)
    assert closure_status(exit_code,complete,natural,errors,differences,resources)==expected


def test_retained_native_bytes_detect_mutation(native,tmp_path):
    record=native.frames[0]
    expected=c.ref.payload_path(native.directory,record["raw_zst"])
    actual=c.DATA/"verification/rust/live-d26-02/output/frame-00000.raw"
    exact_retained(expected,actual,record["sha256"])
    damaged=bytearray(actual.read_bytes());damaged[-1]^=1
    path=tmp_path/"damaged.raw";path.write_bytes(damaged)
    with pytest.raises(ValueError,match="byte mismatch"):exact_retained(expected,path,record["sha256"])


def test_session_survivor_prevents_cleanup_acceptance():
    resources=dict(wine_pids=[],private_sink_present=False,runner_alive=False,session_pids=[123])
    assert closure_status(0,True,True,[],0,resources)=="CLOSED_EXACT_FILES_CLEANUP_PENDING"
