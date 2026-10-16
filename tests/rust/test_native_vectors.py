import sys
from pathlib import Path
import struct
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/verify/rust'))
from native_vectors import curve_records,physics_records
from conformance import Failure


def curve_blob():
    uniform=b'uOrigin\0'.ljust(64,b'\0')+struct.pack('<3I',3,0x8b51,4)+struct.pack('<16I',0x80000000,0x3f800001,0x7f7fffff,*([0]*13))
    return b''.join(struct.pack('<11I',12,12*735,ordinal,0x4085d7,22,1,0,0,1920,1080,1)+uniform for ordinal in (9,18))


def test_curve_keeps_exact_float_bits():
    result=list(curve_records(curve_blob(),[12]));assert result[0][1]['uOrigin']['words']==(0x80000000,0x3f800001,0x7f7fffff)


@pytest.mark.parametrize('raw',[curve_blob()[:-1],curve_blob()+b'\0',curve_blob()[184:]+curve_blob()[:184]])
def test_missing_extra_reordered_curve_payload_rejected(raw):
    with pytest.raises(Failure):list(curve_records(raw,[12]))


def test_wrong_curve_type_rejected():
    raw=bytearray(curve_blob());struct.pack_into('<I',raw,44+68,0x8b52)
    with pytest.raises(Failure,match='type'):list(curve_records(raw,[12]))


def test_physics_coverage_and_clock_not_inferred_from_payload():
    samples=[0,1,1440,26999]
    with pytest.raises(Failure,match='extent'):list(physics_records(b'',samples))
    raw=b''.join(struct.pack('<3I',n,n*735,n*735)+bytes(256) for n in samples)
    assert len(list(physics_records(raw,samples)))==len(samples)
    bad=bytearray(raw);struct.pack_into('<I',bad,268+8,734)
    with pytest.raises(Failure,match='clock'):list(physics_records(bad,samples))
