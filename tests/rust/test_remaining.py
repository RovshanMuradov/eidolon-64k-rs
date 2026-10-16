"""Read-only regression checks of independently acquired Step3 follow-up evidence."""
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"tools/verify/rust"))
from conformance import CHECKOUT,DATA,load,checked,exact_files
from review_controls import review


def test_independent_rebuilt_executable_matches_all_bytes():
    pointer=load(CHECKOUT/"artifacts/verification/rust/rebuild.json")
    result=load(checked(DATA/pointer["result"],pointer["sha256"]))
    candidate=load(CHECKOUT/"artifacts/rust/engine/candidate.json")
    assert result["ancestor_config_isolated"] and result["target_initially_absent"]
    assert exact_files(Path(candidate["directory"])/"eidolon-runtime.exe",result["executable"],728576)==728576


@pytest.mark.parametrize("mode",["gl","position"])
def test_real_physical_control_rejects_before_any_pixel(mode):
    result=review(f"live-d26-{mode}-reject")
    assert result["status"]=="PHYSICAL_FAULT_REJECTED"
    assert result["accepted_pixels"]==0 and result["exit_code"]==125
