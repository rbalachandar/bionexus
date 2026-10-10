"""S-T4 POC: wire-level sensor adapter -> gateway-mediated verdicts, with
calibration-state uncertainty flowing into the PRODUCTION classify().

The claim under test (from the trust thread):
  agents never hold raw instrument verbs; a datasheet-faithful wire
  simulator lets the same adapter target real hardware; and honest
  uncertainty means an uncalibrated probe CANNOT buy a decisive verdict —
  even when its number happens to be right.
"""
import json

import pytest

from bionexus.adapters.devices.ezo_ph import EzoPHLine, EzoPHProbe
from bionexus.core.contracts import (Envelope, ProtocolOp, ProtocolStep,
                                     ProtocolSubmission, SampleKind,
                                     SampleSpec)
from bionexus.core.hypothesis import SuccessCriteria

GATE = SuccessCriteria(metric="ph", direction="max", threshold=7.20)
TRUTH = 7.35          # compliant with the gate, if you trust the probe


def _submission():
    return ProtocolSubmission(
        envelope=Envelope(experiment_branch_id="ezo-scenario"),
        title="bioreactor pH check", assay_type="custom",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense,
                            params={"reads": 5})],
        samples=[SampleSpec(sample_id="br-1", kind=SampleKind.compound)],
        reagents=[])


def _verdict(reading: float, uncertainty: float) -> str:
    """95% interval from the probe's own calibration-state uncertainty —
    the SAME classify() the plate-reader pipeline uses."""
    k = 1.96
    return GATE.classify(reading, (reading - k * uncertainty,
                                   reading + k * uncertainty))


def test_uncalibrated_probe_cannot_claim_and_calibrated_one_can():
    line = EzoPHLine(sample_ph=TRUTH, seed=11)
    probe = EzoPHProbe(line=line)

    run = probe.submit_protocol(_submission())
    res = probe.fetch_results(run)
    m = res.measurements[0]
    assert abs(m.value - TRUTH) < 0.02            # reading happens to be fine
    assert m.uncertainty == pytest.approx(0.120)  # but the probe ADMITS it
    assert _verdict(m.value, m.uncertainty) == "inconclusive", \
        "uncalibrated hardware must abstain even on a lucky number"

    # operator calibrates with buffers (a WIRE action; no agent tool for it)
    line.handle("Cal,low,4.01")
    line.handle("Cal,high,10.01")
    run2 = probe.submit_protocol(_submission())
    m2 = probe.fetch_results(run2).measurements[0]
    assert m2.uncertainty == pytest.approx(0.005)
    assert _verdict(m2.value, m2.uncertainty) == "validated"


def test_wire_quirks_the_mock_must_keep():
    line = EzoPHLine(sample_ph=7.0, seed=3)
    # unknown command -> datasheet error token
    assert line.handle("frobnicate") == "*ER"
    # mid-clears-other-points quirk
    line.handle("Cal,low,4.01")
    line.handle("Cal,mid,7.00")
    assert line.cal_points == {"mid"}
    # sleep quirk: first command wakes, reply is *WA — adapter retries
    probe = EzoPHProbe(line=line)
    line.handle("sleep")
    assert line.handle("r") == "*WA"
    assert probe._tx("r").endswith("*OK")          # retry got the reading


def test_agents_never_see_the_command_grammar():
    caps = json.dumps(EzoPHProbe().list_capabilities())
    for verb in ("Cal,", "c,0", "?i,", "*OK", "handle"):
        assert verb not in caps
    # ...while the planner still learns what it can MEASURE and how well
    assert "pH" in caps and "hardware_validated" in caps
    probe_caps = EzoPHProbe().list_capabilities()
    assert probe_caps["simulated"] is True
    assert probe_caps["hardware_validated"] is False


def test_rejected_command_raises_not_silently():
    probe = EzoPHProbe(line=EzoPHLine(seed=1))
    with pytest.raises(RuntimeError, match="rejected"):
        probe._tx("not-a-real-command")
