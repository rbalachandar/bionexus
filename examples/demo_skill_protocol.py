"""Demo: AI-authored protocol, safely executed.

The full trust story in one script:

  1. An LLM is given protocol-authoring guidance (the same instructions shipped
     in the `opentrons-integration` agent skill, condensed) and authors an
     abstract dose-response protocol for a candidate.
  2. The protocol goes through the SafetyEngine gateway — an intentionally
     unsafe variant is also authored and must be BLOCKED.
  3. The approved protocol executes on the virtual lab; results + provenance
     recorded.

    BIONEXUS_LLM_* (or ANTHROPIC_*) env for a real model; otherwise offline stub.
    .venv/bin/python examples/demo_skill_protocol.py
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "src")

from bionexus.adapters.lab.simulator import SimulatorLab
from bionexus.adapters.models.openai_compat import OpenAICompatProvider
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import (
    AssayType, Envelope, Priority, ProtocolOp, ProtocolStep, ProtocolSubmission,
    ReagentSpec, SampleKind, SampleSpec,
)
from bionexus.core.interfaces import system_actor
from bionexus.core.registry import Registry
from bionexus.core.safety import ForbiddenComboRule, LabGateway, SafetyEngine

SKILL_GUIDANCE = """You author wet-lab protocols. Rules:
- Dose-response series: at least 4 concentrations spanning ~0.5 uM to 40 uM.
- Always include negative controls (buffer wells).
- Declare all reagents with biosafety level (BSL 1-2 typical).
- Never combine incompatible reagents (e.g. acids with hypochlorite oxidizers).
- Output ONLY JSON: {"steps": [{"well": "A1", "volume_ul": 50}],
  "compounds": [{"sample_id": "...", "concentration": "..."}],
  "reagents": [{"name": "...", "amount": "...", "bsl_level": 1}]}
"""


def author_protocol(model, candidate: str, title: str,
                    unsafe: bool = False) -> ProtocolSubmission:
    prompt = (f"{SKILL_GUIDANCE}\n\nCandidate: {candidate}\n"
              f"Title: {title}")
    if unsafe:
        prompt += "\nAlso include 1 mL of 'tris buffer' and 1 mL of 'sodium hypochlorite'."
    inv_name = f"inv-{abs(hash((candidate, unsafe))) % 10**8}"
    from bionexus.core.contracts import ToolInvocation
    inv = ToolInvocation(envelope=Envelope(experiment_branch_id="skill-demo"),
                         tool="d.lab.submit_protocol")
    raw = model.generate(inv, prompt).output["text"]
    doc = json.loads(raw)
    if isinstance(doc, list):
        # offline stub returns proposal lists; substitute a standard protocol doc
        doc = {"steps": [{"well": f"A{i + 1}", "volume_ul": 50}
                         for i, _ in enumerate(doc[:4] or [1])] or [{"well": "A1",
                                                                    "volume_ul": 50}],
               "compounds": [{"sample_id": candidate, "concentration": c}
                             for c in ["0.5uM", "2uM", "10uM", "40uM"]],
               "reagents": [{"name": "assay-buffer", "amount": "5 mL", "bsl_level": 1}]}
    steps = [ProtocolStep(seq=i + 1, op=ProtocolOp.dispense,
                          params={"well": s["well"], "volume_ul": s["volume_ul"]})
             for i, s in enumerate(doc.get("steps", [{"well": "A1", "volume_ul": 50}]))]
    reagents = [ReagentSpec(name=r["name"], amount=r["amount"],
                            bsl_level=r.get("bsl_level", 1))
                for r in doc.get("reagents", [{"name": "buffer", "amount": "5 mL"}])]
    if unsafe:
        reagents += [ReagentSpec(name="tris buffer", amount="1 mL", bsl_level=1),
                     ReagentSpec(name="sodium hypochlorite", amount="1 mL", bsl_level=1)]
    return ProtocolSubmission(
        envelope=Envelope(experiment_branch_id="skill-demo"),
        title=title, assay_type=AssayType.binding, priority=Priority.normal,
        steps=steps,
        samples=[SampleSpec(sample_id=c["sample_id"], kind=SampleKind.compound,
                            concentration=c["concentration"])
                 for c in doc.get("compounds", [{"sample_id": candidate,
                                                 "concentration": "10uM"}])]
        + [SampleSpec(sample_id="ctrl-neg", kind=SampleKind.buffer,
                      concentration="10uM")],
        reagents=reagents,
    )


def main() -> None:
    model = OpenAICompatProvider()
    registry = Registry()
    registry.register_model(model, default=True)
    store = SqliteProvenanceStore()
    actor = system_actor("skill-demo")
    safety = SafetyEngine(rules=[ForbiddenComboRule([("*buffer*", "*hypochlorite*")])])
    gateway = LabGateway(SimulatorLab(seed=42), safety, store, actor)

    print("[1] LLM authors a safe dose-response protocol (skill-guided)")
    p = author_protocol(model, "C-101", "skill-guided dose response")
    run_id, rejection = gateway.submit(p)
    assert run_id, f"unexpected rejection: {rejection}"
    r = gateway.results(p.envelope, run_id)
    print(f"    approved -> run {run_id}: {len(r.measurements)} measurement(s), "
          f"Z'={r.qc.z_prime}")

    print("\n[2] LLM authors an unsafe variant (buffer + hypochlorite)")
    bad = author_protocol(model, "C-101", "unsafe variant", unsafe=True)
    run_id2, rejection2 = gateway.submit(bad)
    assert run_id2 is None
    print(f"    BLOCKED by SafetyEngine: {rejection2}")

    print("\n[3] provenance: every approval and rejection recorded, hash-chained")
    for rec in store.branch_records("skill-demo"):
        print(f"    {rec.event_type.value}")


if __name__ == "__main__":
    main()
