import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/verify/rust'))
from curves import compare_draw,complete_curve_prefix
from test_native_vectors import curve_blob
from conformance import Failure


def pair():
    a=(1440,1058400,9,0x4143d5,55,80,0,0,1920,1080,1)
    b=(1440,1058400,9,0x4085d7,22,10,0,0,1920,1080,1)
    values={'uOrigin':{'type':0x8b51,'words':(0x80000000,0x3f800001,0x7f7fffff)}}
    return (a,{k:dict(v) for k,v in values.items()}),(b,values)


def check(a,b):return compare_draw(a,b,{55:20},{22:20},[80],{0:0},{0:0})


def test_exact_float_bits_with_distinct_process_local_handles():
    assert check(*pair())==3


@pytest.mark.parametrize('index,value',[(0,1439),(1,1058401),(2,18),(8,960)])
def test_clock_pass_or_viewport_mismatch_rejected(index,value):
    a,b=pair();h=list(a[0]);h[index]=value
    with pytest.raises(Failure):check((tuple(h),a[1]),b)


def test_negative_zero_change_is_rejected():
    a,b=pair();a[1]['uOrigin']['words']=(0,0x3f800001,0x7f7fffff)
    with pytest.raises(Failure,match='bits/type'):check(a,b)


def test_missing_active_uniform_is_rejected():
    a,b=pair();a[1].clear()
    with pytest.raises(Failure,match='active-name'):check(a,b)


def test_uniform_type_change_is_rejected():
    a,b=pair();a[1]['uOrigin']['type']=0x8b52
    with pytest.raises(Failure,match='bits/type'):check(a,b)


def test_source_identity_must_match_even_when_uniform_bits_do():
    a,b=pair()
    with pytest.raises(Failure,match='shader'):compare_draw(a,b,{55:19},{22:20},[80],{0:0},{0:0})


def test_growing_curve_truncation_is_not_counted_as_complete_pair():
    raw=curve_blob();complete,pending=complete_curve_prefix(raw[:-1],[12]);assert complete==[] and pending==len(raw)-1
    complete,pending=complete_curve_prefix(raw,[12]);assert len(complete)==2 and pending==0
