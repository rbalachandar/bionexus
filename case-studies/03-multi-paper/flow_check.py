"""CS-03 flow check — does the BioNexus FLOW guide experiments to the right end
results, using each held-out paper's REAL published values as the lab itself?

The model is not the subject. PaperLab is a LabAdapter whose "assay results"
are the paper's actual measurements — so the loop (hypothesis -> design ->
safety-gated experiment -> notice -> verdict -> iterate) runs against real
ground truth, and we verify:

  FLOW INTEGRITY  every stage provenance-recorded; hash chain intact;
                  budget enforced; campaign completed end to end
  END RESULT      with a fixed experiment budget, does a guided campaign
                  recover the paper's true actives better than random
                  (recall@budget), and rank the paper's best compound?

    python flow_check.py [--llm] [--docs a,b]
"""
from __future__ import annotations

import json
import math
import random
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from run import PAPERS, chembl, fetch_doc_activities, pic50  # noqa: E402
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import (
    AssayResult, Envelope, EventType, InstrumentInfo, Measurement,
    ProtocolOp, ProtocolStep, ProtocolSubmission, ReagentSpec, RunStatus,
    SampleKind, SampleSpec,
)
from bionexus.core.hypothesis import (Constraint, ExperimentDesign,
                                      HypothesisTracker, ProblemStatement,
                                      SuccessCriteria)
from bionexus.core.interfaces import record_for, system_actor
from bionexus.core.safety import LabGateway, MaxStepsRule, SafetyEngine

ACTIVE_PIC50 = 6.5
BUDGET = 30          # experiments per campaign
DOCS = ["CHEMBL6087407", "CHEMBL6087417", "CHEMBL6078657"]


class PaperLab:
    """LabAdapter backed by a paper's REAL published values (the ground truth)."""

    name = "paper-lab"

    def __init__(self, values: dict[str, float]):
        self.values = values
        self._runs: dict[str, list[str]] = {}

    def list_capabilities(self):
        return {"assays": ["potency"], "readout": "published-values", "bsl_max": 1}

    def submit_protocol(self, protocol: ProtocolSubmission) -> str:
        rid = f"paper-{protocol.protocol_id[:8]}"
        self._runs[rid] = [s.sample_id for s in protocol.samples]
        return rid

    def get_status(self, run_id): return "done"

    def fetch_results(self, run_id: str) -> AssayResult:
        smis = self._runs[run_id]
        ms = [Measurement(sample_id=s, assay_type="potency",
                          value=self.values[s], unit="pIC50")
              for s in smis if s in self.values]
        return AssayResult(
            envelope=Envelope(experiment_branch_id="paper-lab"),
            protocol_id=run_id,
            instrument=InstrumentInfo(adapter=self.name, instrument_id="published-1"),
            status=RunStatus.completed, measurements=ms,
            qc={"controls_passed": True})

    def cancel(self, run_id): pass


def paper_data(doc: str) -> dict[str, float]:
    acts = fetch_doc_activities(doc)
    vals: dict[str, float] = {}
    for a in acts:
        p = pic50(a)
        if p is not None and a.get("canonical_smiles"):
            vals.setdefault(a["canonical_smiles"], p)
    return vals


def run_campaign(doc: str, label: str, strategy: str, use_llm: bool) -> dict:
    values = paper_data(doc)
    if len(values) < 10:
        return {"paper": label, "skipped": "insufficient published values"}
    compounds = list(values)
    truth_actives = {c for c, p in values.items() if p >= ACTIVE_PIC50}

    store = SqliteProvenanceStore()
    actor = system_actor(f"flow-{strategy}")
    tracker = HypothesisTracker(store, actor)
    lab = PaperLab(values)
    budget_hits = [0]

    safety = SafetyEngine(rules=[MaxStepsRule(50)])
    gw = LabGateway(lab, safety, store, actor)

    problem = tracker.define_problem(ProblemStatement(
        objective=f"Identify the active compounds of {label}",
        constraints=[Constraint(name="budget", description=f"{BUDGET} experiments",
                                kind="hard", limit=BUDGET)],
        success_metric=f"recover published actives (pIC50 >= {ACTIVE_PIC50})"))
    branch = f"problem/{problem.problem_id}"
    env = Envelope(experiment_branch_id=branch)

    # guided scorer: random baseline vs model vs (optionally) LLM
    if strategy == "rf":
        from bionexus.adapters.models.sklearn_policy import MorganFingerprintRF
        from run import fetch_target_pool
        acts = fetch_doc_activities(doc)
        target = next(iter({a["target_chembl_id"] for a in acts if a.get("target_chembl_id")}))
        pool = [(s, p) for s, p in fetch_target_pool(target, doc) if s not in values][:12000]
        model = MorganFingerprintRF(n_estimators=200)
        model.fit(pool)
        score = lambda c: model.predict(c)  # noqa: E731
    elif strategy == "llm" and use_llm:
        from bionexus.adapters.models.anthropic_provider import AnthropicProvider
        from bionexus.core.contracts import ToolInvocation
        agent = AnthropicProvider()

        def score(c: str) -> float:
            txt = agent.generate(ToolInvocation(envelope=env, tool="c.fm.predict_property"),
                                 f"Predict potency class 0-100 for EGFR-independent "
                                 f"medicinal chemistry intuition. SMILES: {c}. "
                                 'Reply ONLY {"value": N}').output["text"]
            m = __import__("re").search(r"-?\d+(?:\.\d+)?", txt)
            return float(m.group(0)) if m else 50.0
    else:
        rng = random.Random(0)
        score = lambda c: rng.random()  # noqa: E731

    tested: dict[str, float] = {}
    rounds = 0
    while len(tested) < BUDGET:
        rounds += 1
        batch = sorted(compounds, key=score, reverse=True)[: min(10, BUDGET - len(tested))]
        batch = [c for c in batch if c not in tested] or \
                [c for c in compounds if c not in tested][:10]
        if not batch:
            break
        proto = ProtocolSubmission(
            envelope=env, title=f"{strategy}-r{rounds}", assay_type="custom",
            steps=[ProtocolStep(seq=1, op=ProtocolOp.measure)],
            samples=[SampleSpec(sample_id=c, kind=SampleKind.compound) for c in batch],
            reagents=[ReagentSpec(name="buffer", amount="1 mL", bsl_level=1)])
        # pre-register one hypothesis per compound BEFORE the experiment
        for c in batch:
            store.append(record_for(env, EventType.hypothesis_proposed, actor,
                                    decision={"statement": f"{c} is active "
                                              f"(pIC50 >= {ACTIVE_PIC50})",
                                              "candidate": c, "round": rounds}))
        run_id, rej = gw.submit(proto)
        if rej:
            break
        res = gw.results(env, run_id)
        for m in res.measurements:
            tested[m.sample_id] = m.value
            hit = m.value >= ACTIVE_PIC50
            budget_hits[0] += 1
            store.append(record_for(env, EventType.hypothesis_validated if hit
                                    else EventType.hypothesis_invalidated, actor,
                                    decision={"candidate": m.sample_id,
                                              "measured_pIC50": m.value,
                                              "threshold": ACTIVE_PIC50}))
        if len(compounds) - len(tested) <= 0:
            break

    found = {c for c, p in tested.items() if p >= ACTIVE_PIC50}
    recall = len(found & truth_actives) / len(truth_actives) if truth_actives else 1.0
    best = max(values, key=lambda k: values[k])
    best_rank = (sorted(tested, key=lambda c: -tested[c]).index(best) + 1
                 if best in tested else None)

    # ---- flow integrity audit from the provenance chain itself
    recs = store.branch_records(branch)
    kinds = {r.event_type.value for r in recs}
    prev = None
    chain_ok = True
    for r in recs:
        if prev is not None and r.prev_record_hash != prev:
            chain_ok = False
        prev = r.record_hash
    # flow_ok: every stage recorded (a paper with zero actives legitimately
    # produces only invalidated verdicts — that's still a complete flow)
    flow_ok = ("problem_defined" in kinds and "hypothesis_proposed" in kinds
               and bool({"hypothesis_validated", "hypothesis_invalidated"} & kinds)
               and chain_ok and len(tested) <= BUDGET)

    return {"paper": label, "strategy": strategy, "n_compounds": len(values),
            "n_true_actives": len(truth_actives), "tested": len(tested),
            "rounds": rounds, "recall_of_actives": round(recall, 3),
            "best_compound_rank": best_rank, "chain_intact": chain_ok,
            "flow_stages_recorded": sorted(kinds), "flow_ok": flow_ok}


def main() -> None:
    use_llm = "--llm" in sys.argv
    docs = DOCS
    if "--docs" in sys.argv:
        docs = sys.argv[sys.argv.index("--docs") + 1].split(",")
    results = []
    for doc in docs:
        label = PAPERS.get(doc, doc) if isinstance(PAPERS, dict) else doc
        for strategy in (["random", "rf"] + (["llm"] if use_llm else [])):
            print(f"  {doc} / {strategy} ...", flush=True)
            r = run_campaign(doc, label, strategy, use_llm)
            results.append(r)
            if "skipped" in r:
                print(f"    skipped: {r['skipped']}")
            else:
                print(f"    flow_ok={r['flow_ok']} chain={r['chain_intact']} "
                      f"recall={r['recall_of_actives']} best_rank={r['best_compound_rank']} "
                      f"(tested {r['tested']}/{r['n_compounds']}, true actives {r['n_true_actives']})")
    out = Path(__file__).parent / "flow_results.json"
    out.write_text(json.dumps(results, indent=1))
    print(f"\nresults: {out}")


if __name__ == "__main__":
    main()
