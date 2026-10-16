import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/verify/rust'))
from semantic import compare_uniform
from conformance import Failure


def vectors():
    native=(6,2,8,10,0,0,1920,1080,4,0x3f800000,1920,1080,9,0,16)
    actual=(6,2,55,80,0,0,1920,1080,11,0x3f800000,1920,1080,12,0,99,0x84c0,0x84c0,0,0)
    return actual,native


def check(a,b,mapping=None,reverse=None):
    compare_uniform(a,b,6,2,{55:7},{8:7},[80],99,16,mapping or {0:0},reverse or {0:0})


def test_process_local_ids_are_mapped_by_role():
    check(*vectors())


@pytest.mark.parametrize('index,value',[(0,7),(1,3),(6,1280),(8,0xffffffff),(9,0x3f800001),(12,0xffffffff),(13,1),(14,98),(16,0x84c1),(18,1280)])
def test_uniform_corruption_is_rejected(index,value):
    actual,native=vectors();bad=list(actual);bad[index]=value
    with pytest.raises(Failure):check(tuple(bad),native)


def test_framebuffer_correspondence_cannot_change_mid_run():
    with pytest.raises(Failure,match='framebuffer'):check(*vectors(),mapping={0:0,10:2})


def test_inactive_values_do_not_claim_runtime_uniform_data():
    a,b=map(list,vectors());a[8]=b[8]=0xffffffff;a[9]=0xdeadbeef
    check(tuple(a),tuple(b))
