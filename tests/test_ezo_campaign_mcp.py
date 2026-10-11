"""S-T4 integration: wire sensor -> gateway-mediated campaign (#1) and
generic MCP transport (#2), proving the transport-swap claim (#3, free).

Scenario: a bioreactor must hold pH >= 7.20 (pre-registered criterion).
The SAME compliant reading (7.35) gets INCONCLUSIVE from an uncalibrated
probe and VALIDATED from a calibrated one — through the production
tracker/gateway/classify, sealed in the hash chain — once over a direct
serial seam and once over an MCP subprocess speaking tools/list +
tools/call. Verdicts identical: the transport is swappable, the
governance is not.
"""
import sys
from pathlib import Path

import pytest

from bionexus.adapters.devices.ezo_ph import EzoPHLine, EzoPHProbe
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import (Envelope, ProtocolOp, ProtocolStep,
                                     ProtocolSubmission, ReagentSpec,
                                     SampleKind, SampleSpec)
from bionexus.core.hypothesis import (Constraint, HypothesisTracker,
                                      ProblemStatement, SuccessCriteria)
from bionexus.core.interfaces import system_actor
from bionexus.core.safety import LabGateway, SafetyEngine
from bionexus.labselect import build_pool
from bionexus.mcp_instrument import McpError, McpLabAdapter

CRIT = SuccessCriteria(metric="ph", direction="max", threshold=7.20)


def _submission(branch: str) -> ProtocolSubmission:
    return ProtocolSubmission(
        envelope=Envelope(experiment_branch_id=branch),
        title="bioreactor pH check", assay_type="custom",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense,
                            params={"reads": 5})],
        samples=[SampleSpec(sample_id="br-1", kind=SampleKind.compound)],
        reagents=[ReagentSpec(name="air", amount="1x", bsl_level=1)])


def _campaign(lab, transport: str) -> dict:
    store = SqliteProvenanceStore(":memory:")
    actor = system_actor("ezo-campaign")
    branch = "problem/ezo-campaign"
    gw = LabGateway(lab, SafetyEngine(), store, actor)
    sub = _submission(branch)
    run_id, reason = gw.submit(sub)
    assert run_id and reason is None, f"gateway refusal: {reason}"
    res = gw.results(sub.envelope, run_id)
    m = res.measurements[0]
    tr = HypothesisTracker(store, actor)
    prob = ProblemStatement(
        objective="keep bioreactor at pH >= 7.20",
        constraints=[Constraint(name="ph", description="pH >= 7.20",
                                kind="hard", limit=7.20, unit="pH")])
    tr.define_problem(prob)
    ci = (round(m.value - 1.96 * m.uncertainty, 4),
          round(m.value + 1.96 * m.uncertainty, 4))
    h = tr.propose(
        statement="br-1 holds pH >= 7.20 (uncertainty-aware)",
        candidate="br-1", assay_type="ph", predicted="pH >= 7.20",
        predicted_value=m.value, criteria=CRIT,
        refutation_condition="pH 95% CI lies wholly below 7.20",
        rationale=f"transport={transport}; probe uncertainty reflects "
                  f"calibration state {m.metadata.get('cal_state')}",
        branch_id=branch)
    h.status = CRIT.classify(m.value, ci)
    h.observed_value = m.value
    h.observed_ci = ci
    h.qc_passed = True
    tr.record_outcome(h, extra={"uncertainty_ph": m.uncertainty,
                                "evidence_tier": "measured",
                                "transport": transport})
    events = [r.event_type.value for r in store.branch_records(branch)]
    return {"verdict": h.status, "value": m.value, "ci": ci,
            "uncertainty": m.uncertainty, "events": events,
            "chain_ok": store.verify_chain() == []}


def _direct_probe(calibrated: bool) -> EzoPHProbe:
    line = EzoPHLine(sample_ph=7.35, seed=11, clock=lambda: 0.0)
    if calibrated:
        line.handle("Cal,low,4.01")
        line.handle("Cal,high,10.01")
    return EzoPHProbe(line=line)


def _mcp_adapter(calibrated: bool) -> McpLabAdapter:
    _, lab = build_pool([{"instrument": "ezo-ph-reference-mcp",
                          "args": ["11", "7.35"]
                          + (["calibrate"] if calibrated else [])}])[0]
    return lab


def test_1_direct_sensor_campaign_uncertainty_reaches_verdict():
    uncal = _campaign(_direct_probe(False), "serial-sim")
    assert uncal["value"] == pytest.approx(7.35, abs=0.01)
    assert uncal["verdict"] == "inconclusive", \
        "uncalibrated probe must not buy a decisive verdict"
    assert uncal["ci"][0] < 7.20 < uncal["ci"][1]
    assert "lab_run" in uncal["events"] and uncal["chain_ok"]

    cal = _campaign(_direct_probe(True), "serial-sim")
    assert cal["value"] == pytest.approx(7.35, abs=0.01)
    assert cal["verdict"] == "validated"      # same reading, now trusted
    assert cal["chain_ok"]


def test_2_mcp_transport_same_scenario_same_verdicts():
    a = _mcp_adapter(False)
    try:
        caps = a.list_capabilities()
        tools = {t["name"]: t for t in caps["tools"]}
        assert tools["read_ph"]["read_only"] is True
        assert tools["calibrate_sensor"]["read_only"] is False
        assert "properties" in tools["read_ph"]["inputSchema"]
        uncal = _campaign(a, "mcp-stdio")
    finally:
        a.close()
    assert uncal["verdict"] == "inconclusive" and uncal["chain_ok"]

    b = _mcp_adapter(True)
    try:
        cal = _campaign(b, "mcp-stdio")
    finally:
        b.close()
    assert cal["verdict"] == "validated" and cal["chain_ok"]


def test_3_transport_swap_changes_nothing():
    """The architectural claim, tested directly: same seed/sample/clock
    over the two transports must yield IDENTICAL numbers and verdicts."""
    direct = _campaign(_direct_probe(False), "serial-sim")
    mcp = _campaign(_mcp_adapter(False), "mcp-stdio")
    assert direct["value"] == mcp["value"]
    assert direct["uncertainty"] == mcp["uncertainty"]
    assert direct["verdict"] == mcp["verdict"] == "inconclusive"


def test_mutating_tool_is_never_auto_invoked():
    a = _mcp_adapter(False)
    try:
        sub = _submission("problem/ezo-guard")
        sub.samples[0].metadata = {"calibrate": "mid,7.00"}
        with pytest.raises(McpError, match="MUTATING|operator"):
            a.submit_protocol(sub)
    finally:
        a.close()


def test_real_labmcp_server_balance_campaign():
    """S-T4 'can you run all 32?' — the honest answer, demonstrated: the
    transport + profile layer run a REAL third-party MCP server
    (labmcp-mettler-toledo --simulate from PyPI, untouched) through the
    same gateway campaign with identical governance. Instruments whose
    vocabulary a profile can describe are in; instruments without a
    declared read-only value tool are refused, never guessed."""
    import shutil
    from bionexus.labselect import available_instruments
    if not any(e["id"] == "labmcp-mettler-toledo" and e["installed"]
               for e in available_instruments()):
        pytest.skip("labmcp-mettler-toledo not installed "
                    "(pip install labmcp-mettler-toledo)")
    _, a = build_pool([{"instrument": "labmcp-mettler-toledo"}])[0]
    try:
        caps = a.list_capabilities()
        tools = {t["name"] for t in caps["tools"]}
        assert {"read_weight", "tare",
                "run_internal_adjustment"} <= tools      # 17-tool surface
        tare = next(t for t in caps["tools"]
                    if t["name"] == "tare")
        assert tare["read_only"] is False               # mutating, visible
        r = _campaign(a, "mcp-labmcp")
        assert r["value"] > 0 and r["verdict"] in (
            "validated", "inconclusive", "invalidated")
        assert r["chain_ok"]
    finally:
        a.close()


def test_profile_cannot_smuggle_a_mutating_read_tool():
    """A profile that LIES — pointing read_tool at a mutating verb — is
    vetoed by the SERVER's annotation, not our trust in the profile."""
    from bionexus.labselect import _catalog_entry, available_instruments
    if not any(e["id"] == "labmcp-mettler-toledo" and e["installed"]
               for e in available_instruments()):
        pytest.skip("labmcp-mettler-toledo not installed")
    cat = _catalog_entry("labmcp-mettler-toledo")
    bad = dict(cat["profile"])
    bad["read_tool"] = "tare"                       # mutating!
    exe = Path(sys.executable).parent / "labmcp-mettler-toledo"
    a = McpLabAdapter(command=[str(exe), "--simulate"], profile=bad)
    try:
        with pytest.raises(McpError, match="readOnly"):
            a.submit_protocol(_submission("problem/nope"))
    finally:
        a.close()
