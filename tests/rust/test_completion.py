import copy
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/verify/rust'))
from completion import full_gate,sampled_gate
from conformance import CHECKOUT,Failure


def full():return json.loads((CHECKOUT/'artifacts/verification/rust/full-progress.json').read_text())


def test_existing_full_capture_gate():full_gate(full())


@pytest.mark.parametrize('field,value',[('matching_frame_hashes',26999),('frame_hashes',True),('time_mismatches',1),('terminal_stability',False)])
def test_partial_or_mismatched_full_proof_cannot_close_audit(field,value):
    evidence=full();evidence['progress'][field]=value
    with pytest.raises(Failure):full_gate(evidence)


def test_timeout_cannot_become_natural_endpoint():
    evidence=full();evidence['natural_exit_log']=False
    with pytest.raises(Failure):full_gate(evidence)


def test_missing_physical_restoration_witnesses_reject():
    evidence=full();evidence['physical_restoration']={}
    with pytest.raises(Failure,match='physical'):full_gate(evidence)


def test_unpaired_native_curve_oracle_cannot_close_audit():
    native=json.loads((CHECKOUT/'artifacts/verification/rust/native-d28-vectors01.json').read_text())
    with pytest.raises(Failure,match='paired'):sampled_gate(native,native)
