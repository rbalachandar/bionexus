"""Regenerate assets/story/demo-run.json — the campaign the Story page
narrates. Run from the repo root: python scripts/capture_story_run.py"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bionexus import citations
from bionexus.adapters.lab.simulator import SimulatorLab
from bionexus.adapters.models.assayloop_ranker import AssayLoopRanker
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.autoloop import CampaignConfig, run_campaign
from bionexus.core.hypothesis import Constraint, ProblemStatement


class ObservedIC50Policy:
    """Toy 'more of what worked' policy — stands in for AssayFormer."""

    def predict(self, observations, candidates, task_context=None):
        good = {o.candidate[:2] for o in observations if o.label.get("hit")}

        class P:
            scores = {c: (2.0 if c[:2] in good else 1.0) + 0.01 * i
                      for i, c in enumerate(candidates)}
        return P


def spec(c, smi, mech, ref, cite, cstat):
    return {"statement": f"{c} inhibits MAP4K1 with IC50 <= 20 uM",
            "candidate": c, "assay_type": "binding", "predicted": "IC50 <= 20",
            "predicted_value": 20.0, "family": c[:2], "smiles": smi,
            "mechanism": mech, "refutation_condition": ref,
            "citation": cite, "citation_status": cstat}


def main() -> None:
    inbox = Path(".data/story-run")
    shutil.rmtree(inbox, ignore_errors=True)
    inbox.mkdir(parents=True)
    log = []
    cits = {c: citations.verify(c) for c in
            ["PMID:35377565", "PMID:99999999"]}
    specs = [
        spec("AA-1", "Nc1ccc(-c2ccc(NC(=O)NC3CCCCC3)cc2)n2ccn12",
             "type-I hinge binder occupying the ATP pocket of MAP4K1's "
             "active conformation",
             "no dose-response in enzymatic assay despite confirmed binding",
             "PMID:35377565", cits["PMID:35377565"]["status"]),
        spec("AA-2", "CC(=O)Nc1ccc(-c2cccnc2)cc1",
             "amide-linked aza-biaryl, same hinge geometry",
             "activity lost when hinge gatekeeper mutated",
             "PMID:99999999", cits["PMID:99999999"]["status"]),
        spec("BB-1", "C=CC(=O)Nc1ccc(Oc2ccccn2)cc1",
             "covalent warhead (acrylamide) targeting Cys433 — declared "
             "intent", "selectivity lost in C433S mutant",
             "PMID:35377565", cits["PMID:35377565"]["status"]),
        spec("BX-1", "O=[N+]([O-])c1ccc(N=Nc2ccccc2)cc1",
             "aromatic nitro with azo link — flagged by structural alerts",
             "any activity at all (expected toxicophore liability)",
             "", "unverified"),
    ]
    problem = ProblemStatement(
        objective="Find MAP4K1 inhibitors with IC50 <= 20 uM",
        problem_id="prob-story",
        constraints=[Constraint(name="potency", description="IC50 <= 20 uM",
                                kind="hard", limit=20.0, unit="uM")],
        success_metric="orthogonally confirmed binder")
    cfg = CampaignConfig(problem=problem, hypotheses=specs, k=2, rounds=2,
                         autonomy="act", inbox=str(inbox), poll_secs=0.05,
                         policy=AssayLoopRanker(policy=ObservedIC50Policy()))
    store = SqliteProvenanceStore()
    report = run_campaign(cfg, SimulatorLab(seed=2), store, notify=log.append)
    recs = [{"event": r.event_type.value, "ts": r.envelope.created_at,
             "decision": r.decision or {},
             "candidate": ((r.artifact.metadata if r.artifact else {})
                           or {}).get("candidate")}
            for r in store.branch_records("problem/prob-story")]
    out = Path("assets/story")
    out.mkdir(parents=True, exist_ok=True)
    (out / "demo-run.json").write_text(json.dumps(
        {"log": log, "records": recs, "rounds_run": report.rounds_run,
         "history": report.history, "verdicts": report.verdicts}, indent=1))
    print(f"captured {len(log)} log lines, {len(recs)} records")


if __name__ == "__main__":
    main()
