"""ProteinDesignLabAdapter — protein design as a BioNexus LabAdapter.

The contract: submit a protocol → execute → get AssayResult with
per-design ipTM measurements. Mock mode proves the pipeline shape;
real BindCraft/Boltz integration plugs in behind the same interface.
"""
import pytest

from bionexus.core.contracts.models import (
    Envelope, ProtocolSubmission, AssayType, Priority, ProtocolStep,
    SampleSpec, ProtocolOp,
)
from bionexus.adapters.lab.protein_design import ProteinDesignLabAdapter


def _make_submission(protocol_id="prot-design-001"):
    return ProtocolSubmission(
        envelope=Envelope(experiment_branch_id="design/prot-001"),
        protocol_id=protocol_id,
        title="protein binder design",
        assay_type=AssayType.binding,
        priority=Priority.normal,
        steps=[ProtocolStep(seq=1, op=ProtocolOp.measure, params={"design": True})],
        constraints={"hotspot_residues": "56", "binder_lengths": [70, 120],
                      "n_designs": 20, "iptm_threshold": 0.7},
    )


def test_mock_produces_measurements():
    adapter = ProteinDesignLabAdapter(mock=True, seed=7)
    sub = _make_submission()
    run_id = adapter.submit_protocol(sub)
    assert adapter.get_status(run_id) == "queued"

    result = adapter.execute(run_id, target_pdb="mock.pdb", n_designs=20)
    assert result.status.value == "completed"
    assert len(result.measurements) == 20
    assert result.instrument.adapter == "protein-design"
    assert result.qc.controls_passed is True

    # every measurement has an ipTM value in [0, 1]
    for m in result.measurements:
        assert 0.0 <= m.value <= 1.0
        assert m.unit == "iptm"

    assert adapter.get_status(run_id) == "done"


def test_mock_is_deterministic():
    a = ProteinDesignLabAdapter(mock=True, seed=42)
    b = ProteinDesignLabAdapter(mock=True, seed=42)
    ra = a.execute(a.submit_protocol(_make_submission()), target_pdb="x.pdb", n_designs=10)
    rb = b.execute(b.submit_protocol(_make_submission()), target_pdb="x.pdb", n_designs=10)
    assert [m.value for m in ra.measurements] == [m.value for m in rb.measurements]


def test_capabilities_document_constraints():
    caps = ProteinDesignLabAdapter(mock=True).list_capabilities()
    assert "protein_binder_design" in caps["assays"]
    assert caps["constraints"]["max_binder_length"] == 250
    assert "BindCraft" in caps["make_tool"]


def test_cancel_stops_run():
    adapter = ProteinDesignLabAdapter(mock=True, seed=1)
    rid = adapter.submit_protocol(_make_submission())
    adapter.cancel(rid)
    assert adapter.get_status(rid) == "cancelled"
