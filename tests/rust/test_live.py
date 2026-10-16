"""Read-only checks of completed real D26 jobs; never starts Wine/GPU."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"tools/verify/rust"))
import conformance as c
from review_live import review


def test_actual_production_short_restoration_and_exact_outputs():
    result=review(c.DATA/"verification/rust/live-d26-02")
    assert result["status"]=="SHORT_EXACT_PARTIAL"
    assert result["checks"]["entry"] is True
    assert result["checks"]["marker_fp"] is True
    assert result["checks"]["marker_gpr"] is True
    assert result["checks"]["gl_restoration_witnesses"]==3
    assert result["checks"]["pcm"]=="EXACT_NATIVE_PCM"
    assert result["checks"]["pixels"]==3 and result["production_accepted"] is False


def test_actual_hook_fault_is_physical_and_rejected():
    result=review(c.DATA/"verification/rust/live-d26-fp-reject")
    assert result["status"]=="FAULT_REJECTED"
    assert result["checks"]["physical_fault_changed_and_rejected"] is True
    assert result["checks"]["pixels"]==0 and result["exit_code"]==125
