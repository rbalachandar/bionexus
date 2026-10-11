"""S-T5: the operator's fence + the matcher inside it."""
import tempfile
from pathlib import Path

import pytest

from bionexus.adapters.lab.simulator import SimulatorLab
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.autoloop import CampaignConfig, run_campaign
from bionexus.core.contracts import Envelope
from bionexus.core.hypothesis import ProblemStatement
from bionexus.labselect import (LabRequirement, build_pool, normalize_caps,
                                select_lab)


class _ValidatedRig:
    name = "rig"

    def list_capabilities(self):
        return {"assays": ["binding"], "bsl_max": 1,
                "hardware_validated": True, "simulated": False}


def _hyps(assay="binding"):
    return [{"statement": f"S1 binds ({assay})", "candidate": "S1",
             "assay_type": assay, "predicted": "<= 20",
             "predicted_value": 20.0, "rationale": "t"}]


def _cfg(labs, req=None, assay="binding"):
    return CampaignConfig(
        problem=ProblemStatement(objective="match the lab"),
        hypotheses=_hyps(assay), k=1, rounds=1, autonomy="act",
        inbox=tempfile.mkdtemp(prefix="ls-"), poll_secs=0.02,
        labs=labs, lab_requirement=req)


def test_hardware_preferred_over_simulator_within_pool():
    sel, declined = select_lab(
        [("sim-0", SimulatorLab(seed=7)), ("rig-1", _ValidatedRig())],
        LabRequirement.build({"assay_types": ["binding"], "max_bsl": 1}))
    assert sel.name == "rig-1"          # hardware first, within the pool
    assert declined == []
    assert normalize_caps(SimulatorLab(seed=7))["simulated"] is True


def test_capability_mismatch_refuses_with_reasons():
    sel, refusals = select_lab(
        [("sim-0", SimulatorLab(seed=7))],
        LabRequirement.build({"readouts": ["pH"]}))
    assert sel is None
    assert any("pH" in " ".join(r["why"]) for r in refusals)


def test_mcp_pool_member_matches_via_declared_tools():
    from bionexus.labselect import available_instruments
    if not any(e["id"] == "labmcp-mettler-toledo" and e["installed"]
               for e in available_instruments()):
        pytest.skip("labmcp-mettler-toledo not installed")
    pool = build_pool([{"instrument": "bionexus-virtual-lab"},
                       {"instrument": "labmcp-mettler-toledo"}])
    try:
        sel, declined = select_lab(
            pool, LabRequirement.build({"readouts": ["read_weight"]}))
        assert sel is not None and "mettler" in sel.name
        assert declined and "no readout" in " ".join(declined[0]["why"])
    finally:
        for _, lab in pool:
            if hasattr(lab, "close"):
                lab.close()


def test_campaign_refused_and_sealed_when_pool_cannot_serve():
    store = SqliteProvenanceStore(":memory:")
    with pytest.raises(ValueError, match="lab selection refused"):
        run_campaign(_cfg([{"simulator": {"seed": 7}}], assay="hplc"),
                     SimulatorLab(seed=7), store, notify=lambda m: None)
    decisions = [r.decision for r in
                 next(br for br in store.branches()
                      if br.startswith("problem/"))
                 and store.branch_records(
                      next(br for br in store.branches()
                           if br.startswith("problem/")))
                 if r.event_type.value == "gate_decision"
                 ] if False else []
    evs = [r.decision for br in store.branches()
           for r in store.branch_records(br)
           if r.event_type.value == "gate_decision"]
    assert any(e.get("kind") == "lab_refusal" for e in evs)


def test_campaign_runs_with_pool_and_seals_selection():
    store = SqliteProvenanceStore(":memory:")
    rep = run_campaign(
        _cfg([{"simulator": {"seed": 42}}], assay="binding"),
        SimulatorLab(seed=1), store, notify=lambda m: None)
    evs = [r.decision for br in store.branches()
           for r in store.branch_records(br)
           if r.event_type.value == "gate_decision"]
    sel = [e for e in evs if e.get("kind") == "lab_selected"]
    assert sel and sel[0]["chosen"]["simulated"] is True
    assert store.verify_chain() == []
    assert rep.verdicts


def _gate_cfg(labs):
    c = _cfg(labs, assay="binding")
    c.autonomy = "gate"
    return c


def test_gate_mode_human_confirms_multi_eligible_choice():
    """Machine ranks, human signs: with 2 eligible instruments under gate
    autonomy, the approver is asked about the LAB and the confirmation
    is sealed."""
    store = SqliteProvenanceStore(":memory:")
    calls = []
    rep = run_campaign(
        _gate_cfg([{"simulator": {"seed": 7}},
                   {"simulator": {"seed": 8}}]),
        None, store,
        approver=lambda title: calls.append(title) or True,
        notify=lambda m: None)
    assert any(str(c).startswith("LAB [") for c in calls)
    kinds = [r.decision.get("kind") for br in store.branches()
             for r in store.branch_records(br)
             if r.event_type.value == "gate_decision"]
    assert "lab_selected" in kinds and "lab_confirmed" in kinds
    assert rep.verdicts


def test_gate_mode_declined_lab_choice_refuses_campaign():
    store = SqliteProvenanceStore(":memory:")
    with pytest.raises(ValueError, match="declined by the approver"):
        run_campaign(
            _gate_cfg([{"simulator": {"seed": 7}},
                       {"simulator": {"seed": 8}}]),
            None, store, approver=lambda title: False,
            notify=lambda m: None)
    kinds = [r.decision.get("kind") for br in store.branches()
             for r in store.branch_records(br)
             if r.event_type.value == "gate_decision"]
    assert "lab_confirmation_declined" in kinds


def test_single_eligible_instrument_needs_no_confirmation():
    store = SqliteProvenanceStore(":memory:")
    calls = []
    run_campaign(_gate_cfg([{"simulator": {"seed": 7}}]), None, store,
                 approver=lambda title: calls.append(title) or True,
                 notify=lambda m: None)
    assert not any(str(c).startswith("LAB [") for c in calls)


def test_config_schema_flows_to_server_flags():
    """The review's interface-config idea: connection details (address,
    simulate) are per-instrument config translated to server flags via
    the catalog's declared config_schema — simulate defaults ON so a
    campaign must opt INTO hardware, never accidentally touch it."""
    from bionexus.labselect import _config_args
    cat = next(e for e in __import__("json").loads(
        (Path(__file__).resolve().parents[1]
         / "src/bionexus/instruments.json").read_text())["instruments"]
        if e["id"] == "labmcp-mettler-toledo")
    assert _config_args(cat, {}) == ["--simulate"]
    assert _config_args(cat, {"simulate": True,
                              "address": "tcp://10.0.0.5:1234"}) == \
        ["--simulate", "--address", "tcp://10.0.0.5:1234"]
    assert _config_args(cat, {"simulate": False,
                              "address": "COM3"}) == ["--address", "COM3"]


def test_fence_info_resolves_and_flags_honestly():
    from bionexus.labselect import fence_info
    fence = fence_info([{"instrument": "labmcp-mettler-toledo"}])
    f = fence[0]
    assert f["name"].startswith("Mettler Toledo")
    assert f["simulated"] is True and f["installed"] is True
    assert f["hardware_validated"] is False
    # unknown id: declared but unresolvable — kept visible, flagged
    f2 = fence_info([{"instrument": "ghost-9000"}])[0]
    assert f2["unknown"] is True and f2["installed"] is False
