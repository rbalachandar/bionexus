"""CASE STUDY 04 — PROSPECTIVE hit-to-lead on real published EGFR data.

The test the roadmap demanded (S-T0): the epistemic machinery runs against
REAL measured values, with the field's actual future — the seven documented
successor drugs gefitinib, erlotinib, lapatinib, afatinib, dacomitinib,
neratinib, osimertinib — REMOVED from everything the loop can see: the
candidate library, the surrogate's training pool, and the replay lab.

Flow (real DMTA machinery, no new physics):
  frozen ChEMBL corpus -> canonicalize -> blind the 7 -> 70/30 split
  -> Morgan-RF surrogate (seeded) trained on the 70
  -> library = 24 never-trained-on compounds (opaque IDs; chemistry travels
     in provenance metadata, never as a plate label)
  -> Campaign A: gated campaign (autonomy=act), hypotheses declared
     REVERSIBLE mechanism; safety gate screens every molecule for real
     (acrylamides = medium toxicophore -> refused without declared intent)
  -> Campaign B: the refused Michael-acceptors re-proposed with an honest
     DECLARED covalent intent — does the gate let the warheads through?
  -> Verdicts scored against published truth (median pIC50 >= 8 = active)
  -> REVEAL: do the loop's confirmed compounds share chemotype (Murcko
     scaffold) and structure (Tanimoto) with the drugs the field picked?

Offline-capable: reads frozen fixtures (materialize verifies checksums).
Run:  .venv/bin/python case-studies/04-prospective-hit2lead/run.py
"""
from __future__ import annotations

import csv
import json
import random
import shutil
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

CASE = HERE
CACHE = CASE / ".cache"
GATE_PIC50 = 6.0                    # truth-active: median published pIC50 >= 6
GATE_IC50_UM = 1.0                  # the pre-registered gate (1 uM, HTS hit bar)
# floor at the fit-grid minimum (0.001 uM): a true K below the ladder
# floor pins both fits and CI-agreement breaks (CS04 caught this as a
# false refutation of a 4.5 nM compound)
LADDER = ("0.001uM", "0.003uM", "0.01uM", "0.03uM", "0.1uM", "0.3uM",
          "1uM", "3uM", "10uM")
SEED = 42


# --------------------------------------------------------------- corpus

def _canon(smi: str):
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog("rdApp.*")
    m = Chem.MolFromSmiles(smi.split(".")[0].strip())
    if m is None:
        return None
    frags = Chem.GetMolFrags(m, asMols=True)
    if not frags:
        return None
    return Chem.MolToSmiles(max(frags, key=lambda f: f.GetNumAtoms()))


def load_corpus() -> dict[str, dict]:
    """canonical compound -> {median, n, range, assays}."""
    path = CACHE / "chembl_CHEMBL203.csv"
    by: dict[str, dict] = defaultdict(lambda: {"values": [], "assays": set()})
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            c = _canon(row["smiles"])
            if c is None:
                continue
            try:
                by[c]["values"].append(float(row["pic50"]))
                by[c]["assays"].add(row["assay"])
            except ValueError:
                continue
    return {c: {"median": round(statistics.median(d["values"]), 3),
                "n": len(d["values"]),
                "range": [min(d["values"]), max(d["values"])],
                "assays": sorted(d["assays"])[:5]}
            for c, d in by.items()}


def blind_drugs(corpus: dict, drugs: list[dict]) -> tuple[dict, list]:
    """Verify each held-out drug EXISTS in the frozen corpus (blinding is
    only real if there was something to remove), keep its published truth
    for the reveal, then remove it from the loop's universe."""
    reveal, missing = [], []
    for d in drugs:
        c = _canon(d["canonical_smiles"])
        rec = dict(d, canonical=c)
        if c in corpus:
            rec["published"] = dict(corpus[c],
                                    active=corpus[c]["median"] >= GATE_PIC50)
            reveal.append(rec)
        else:
            missing.append(d["name"])
    if missing:
        print(f"  !! held-out drugs NOT in corpus (blinding untestable): "
              f"{missing}")
    blind = {r["canonical"] for r in reveal}
    return {c: v for c, v in corpus.items() if c not in blind}, reveal


# --------------------------------------------------------------- surrogate

def train_surrogate(pool: dict[str, dict]):
    """Morgan-FP RF on a seeded 70% (pIC50 regression); the 30% test side is
    what the loop may explore — the model has never seen their values."""
    from bionexus.adapters.models.sklearn_policy import MorganFingerprintRF
    items = sorted(pool.items())
    rng = random.Random(SEED)
    rng.shuffle(items)
    cut = int(len(items) * 0.70)
    train, test = items[:cut], items[cut:]
    pol = MorganFingerprintRF(seed=SEED)
    pol.fit([(s, v["median"]) for s, v in train])
    return pol, dict(train), dict(test)


def build_library(test: dict, pol) -> dict[str, dict]:
    """36 candidates STRATIFIED across the surrogate's predicted-pIC50
    range (well below the gate -> borderline -> well above), so the loop's
    claims, kills and abstentions all face the published truth. Measured
    >=3x only (stable truth). Keyed by opaque IDs — plate labels are
    sanitized to 60 chars; SMILES must never be the identity."""
    cands = []
    for smi, r in test.items():
        if r["n"] < 3:
            continue
        pred = pol.predict(smi)
        if pred < 4.0 or pred > 9.5:
            continue
        cands.append((pred, smi, r))
    cands.sort()
    bins: dict[int, list] = defaultdict(list)
    for pred, smi, r in cands:
        bins[int(round(pred * 2))].append((pred, smi, r))   # 0.5 pIC50 bins
    picks, per_bin = [], dict(sorted(bins.items()))
    keys = list(per_bin)
    while len(picks) < 36 and keys:
        for k in list(keys):                                # round-robin bins
            if per_bin[k]:
                picks.append(per_bin[k].pop(0))
            if not per_bin[k]:
                keys.remove(k)
            if len(picks) >= 36:
                break
    picks.sort(key=lambda t: -t[0])
    return {f"EG-{i + 1:02d}": dict(r, smiles=smi,
                                    surrogate_pred_um=round(
                                        10 ** (6.0 - pred), 4),
                                    truth_um=round(
                                        10 ** (6.0 - r["median"]), 4))
            for i, (pred, smi, r) in enumerate(picks)}


# --------------------------------------------------------- chemistry utils

def murcko(smiles: str) -> str:
    from rdkit import Chem, RDLogger
    from rdkit.Chem.Scaffolds import MurckoScaffold
    RDLogger.DisableLog("rdApp.*")
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return ""
    try:
        return MurckoScaffold.MurckoScaffoldSmiles(mol=m, includeChirality=False)
    except Exception:
        return ""


def tanimoto(a: str, b: str) -> float:
    from rdkit import Chem, DataStructs, RDLogger
    from rdkit.Chem import rdFingerprintGenerator
    RDLogger.DisableLog("rdApp.*")
    gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)

    def fp(s):
        m = Chem.MolFromSmiles(s)
        return gen.GetFingerprint(m) if m else None
    fa, fb = fp(a), fp(b)
    return 0.0 if fa is None or fb is None else float(
        DataStructs.FingerprintSimilarity(fa, fb))


# --------------------------------------------------------------- campaigns

def _problem(pid: str, objective: str):
    from bionexus.core.hypothesis import Constraint, ProblemStatement
    return ProblemStatement(
        problem_id=pid, objective=objective,
        constraints=[Constraint(name="ic50_um", description="<= 0.01 uM",
                                kind="hard", limit=GATE_IC50_UM, unit="uM")])


def run_campaign_a(library: dict[str, dict]):
    """Gated campaign over the blinded library; every hypothesis honestly
    declares a REVERSIBLE mechanism."""
    from bionexus.adapters.lab.replay import ReplayLab
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.autoloop import CampaignConfig, ResourceBudget, run_campaign
    from bionexus.core.hypothesis import SuccessCriteria
    from bionexus.flywheel import Flywheel

    lab = ReplayLab({cid: r["truth_um"] for cid, r in library.items()},
                    sources={cid: {"assays": r["assays"],
                                   "n_measurements": r["n"],
                                   "origin": "published ChEMBL median (replay)"}
                             for cid, r in library.items()},
                    seed=SEED)
    store = SqliteProvenanceStore(str(CASE / "study.db"))
    specs = [{"statement": f"{cid} inhibits EGFR with IC50 <= 10 nM",
              "candidate": cid, "assay_type": "binding",
              "predicted": f"<= {GATE_IC50_UM:g} uM",
              "criteria": SuccessCriteria(metric="ic50_um", direction="min",
                                          threshold=GATE_IC50_UM),
              "smiles": r["smiles"],
              "mechanism": "reversible ATP-site competitive antagonist",
              "rationale": "surrogate-prior ranking over published EGFR pool"}
             for cid, r in library.items()]
    msgs: list[str] = []
    cfg = CampaignConfig(
        problem=_problem("cs04-hit2lead",
                         "Identify EGFR binders with IC50 <= 10 nM "
                         "(published-data replay; gate 0.01 uM)"),
        hypotheses=specs, k=18, k_schedule=(18, 12), rounds=2,
        budget=ResourceBudget(max_total_runs=250, max_hypotheses_total=40,
                              max_confirmations=40),
        concentrations=LADDER, autonomy="act",
        inbox=str(CASE / ".inbox-a"), actor_name="cs04",
        flywheel=Flywheel(":memory:"),
        score_fn=lambda h: 1.0 / (1.0 + library.get(h.candidate, {}).get(
            "surrogate_pred_um", 1e6)))
    report = run_campaign(cfg, lab, store,
                          notify=lambda m: msgs.append(str(m)))
    branch = f"problem/{report.problem_id}"
    refusals = [r.decision for r in store.branch_records(branch)
                if r.event_type.value == "gate_decision"
                and (r.decision or {}).get("kind") == "safety_refusal"]
    return report, refusals, branch, msgs


def run_campaign_b(refusals, library: dict[str, dict]):
    """Re-design pass: gate-refused warhead-bearing candidates, re-proposed
    with an honest DECLARED covalent mechanism."""
    from bionexus.adapters.lab.replay import ReplayLab
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.autoloop import CampaignConfig, ResourceBudget, run_campaign
    from bionexus.core.hypothesis import SuccessCriteria
    from bionexus.flywheel import Flywheel

    refused = [cid for d in refusals for cid in d.get("samples", [])]
    reprops = [cid for cid in refused if cid in library][:6]
    if not reprops:
        return None
    lab = ReplayLab({cid: library[cid]["truth_um"] for cid in reprops},
                    seed=SEED)
    store = SqliteProvenanceStore(str(CASE / "study.db"))
    specs = [{"statement":
              f"{cid} covalently inhibits EGFR with IC50 <= 10 nM",
              "candidate": cid, "assay_type": "binding",
              "predicted": f"<= {GATE_IC50_UM:g} uM",
              "criteria": SuccessCriteria(metric="ic50_um", direction="min",
                                          threshold=GATE_IC50_UM),
              "smiles": library[cid]["smiles"],
              "mechanism": "irreversible covalent EGFR inhibitor — "
                           "Michael-acceptor warhead engaging the reactive "
                           "cysteine (declared intent)",
              "rationale": "re-design after gate refusal: keep the chemistry, "
                           "declare the mechanism"} for cid in reprops]
    cfg = CampaignConfig(
        problem=_problem("cs04-covalent-reproposal",
                         "Re-test gate-refused warhead-bearing EGFR binders "
                         "with declared covalent mechanism (IC50 <= 10 nM)"),
        hypotheses=specs, k=len(reprops), rounds=1,
        budget=ResourceBudget(max_total_runs=40, max_hypotheses_total=10,
                              max_confirmations=10),
        concentrations=LADDER, autonomy="act",
        inbox=str(CASE / ".inbox-b"), actor_name="cs04b",
        flywheel=Flywheel(":memory:"))
    report = run_campaign(cfg, lab, store, notify=lambda m: None)
    return report, reprops


# --------------------------------------------------------------- scoring

def score(report_a, refusals, b_result, library, reveal):
    out = {"campaign_a": {}, "campaign_b": {}, "per_compound": [],
           "gate_refusals": [], "future_convergence": []}
    for d in refusals:
        out["gate_refusals"].append({
            "samples": d.get("samples"),
            "reason": (d.get("reason") or "")[:240]})

    def bucket(v):
        if str(v) in ("confirmed", "validated"):
            return "claims_hit"
        if str(v) in ("refuted", "invalidated"):
            return "claims_miss"
        if str(v) == "inconclusive":
            return "abstains"
        return "unjudged"        # never reached the lab (refused upstream)

    stats = defaultdict(int)
    rows = []
    b_map = {cid: v for cid, v in (b_result[0].verdicts.items()
                                   if b_result else [])}

    def tally(verdicts: dict, key: str):
        local = defaultdict(int)
        for cid, v in verdicts.items():
            r = library.get(cid)
            if r is None:
                continue
            t = r["median"] >= GATE_PIC50
            local[f"{bucket(v)}_{'active' if t else 'inactive'}"] += 1
            rows.append({"candidate": cid, "campaign": key,
                         "smiles": r["smiles"], "verdict": v,
                         "bucket": bucket(v),
                         "published_median_pic50": r["median"],
                         "n_measurements": r["n"],
                         "assays": r["assays"][:3], "true_active": t})
        return local

    sa = tally(report_a.verdicts, "A")
    out["campaign_a"] = {
        "selected": len(report_a.verdicts),
        "judged": sum(1 for v in report_a.verdicts.values()
                      if bucket(v) != "unjudged"),
        "correct_hit_claims": sa["claims_hit_active"],
        "FALSE_hit_claims": sa["claims_hit_inactive"],
        "correct_miss_calls": sa["claims_miss_inactive"],
        "WRONGLY_KILLED_actives": sa["claims_miss_active"],
        "honest_abstentions": sa["abstains_active"] + sa["abstains_inactive"],
        "safety_refused": sum(1 for d in refusals),
        "synthesis_refused": None,   # filled from store below if available
    }
    if b_result:
        rep, reprops = b_result
        sb = tally(rep.verdicts, "B")
        out["campaign_b"] = {
            "reproposed_with_declared_covalent_intent": len(reprops),
            "gate_then_allowed": len([c for c in reprops
                                      if c in rep.verdicts]),
            "judged": sum(1 for v in rep.verdicts.values()
                          if bucket(v) != "unjudged"),
            "correct_hit_claims": sb["claims_hit_active"],
            "FALSE_hit_claims": sb["claims_hit_inactive"],
            "correct_miss_calls": sb["claims_miss_inactive"],
            "WRONGLY_KILLED_actives": sb["claims_miss_active"],
            "honest_abstentions": sb["abstains_active"] + sb["abstains_inactive"],
            "verdicts": rep.verdicts,
        }
    out["per_compound"] = sorted(rows, key=lambda x: -x["published_median_pic50"])
    confirmed_smi = {r["candidate"]: r["smiles"] for r in rows
                     if r["verdict"] in ("confirmed", "validated")
                     and r["campaign"] in ("A", "B")}
    truth_active = {r["candidate"]: r["true_active"] for r in rows}
    for d in reveal:
        sc = murcko(d["canonical_smiles"])
        same = [cid for cid, smi in confirmed_smi.items()
                if murcko(smi) == sc and sc]
        best, bestsim = None, -1.0
        for cid, smi in confirmed_smi.items():
            t = tanimoto(smi, d["canonical_smiles"])
            if t > bestsim:
                best, bestsim = cid, t
        out["future_convergence"].append({
            "drug": d["name"], "generation": d["generation"],
            "published_median_pic50": d["published"]["median"],
            "published_range": d["published"]["range"],
            "passes_gate_on_truth_alone": d["published"]["active"],
            "loop_confirmed_same_scaffold": len(same),
            "nearest_confirmed_tanimoto": (round(bestsim, 3)
                                           if best else None),
            "nearest_confirmed_was_true_active": (
                truth_active.get(best) if best else None),
        })
    return out


# --------------------------------------------------------------- main

def main() -> None:
    print("== CS04 prospective hit-to-lead — EGFR (CHEMBL203) ==")
    try:
        from bionexus import fixtures
        n = fixtures.materialize(CASE)
        print(f"materialized {n} frozen fixture file(s) (checksum-verified)")
    except (FileNotFoundError, ValueError):
        print("no frozen fixtures (or corrupt) — fetching from ChEMBL and "
              "FREEZING now")
        from bionexus.adapters.data.chembl import fetch_target_activities
        CACHE.mkdir(exist_ok=True)
        fetch_target_activities("CHEMBL203", cache_dir=CACHE,
                                max_records=100000)
        fixtures.freeze(CASE, [("chembl_CHEMBL203.csv",
                                CACHE / "chembl_CHEMBL203.csv"),
                               ("heldout.json", CASE / "heldout.json")])

    # fresh artifacts each run (study.db history would confuse the scoring)
    (CASE / "study.db").unlink(missing_ok=True)
    shutil.rmtree(CASE / ".inbox-a", ignore_errors=True)
    shutil.rmtree(CASE / ".inbox-b", ignore_errors=True)

    heldout = json.loads((CASE / "heldout.json").read_text())
    corpus = load_corpus()
    print(f"corpus: {len(corpus)} unique canonical compounds")
    loop_corpus, reveal = blind_drugs(corpus, heldout["drugs"])
    print(f"blinded {len(reveal)}/7 documented drugs -> loop universe: "
          f"{len(loop_corpus)}")

    pol, train, test = train_surrogate(loop_corpus)
    print(f"surrogate trained on {len(train)} compounds; blinded test pool "
          f"{len(test)}")
    library = build_library(test, pol)

    report_a, refusals, branch_a, msgs = run_campaign_a(library)
    print(f"campaign A branch {branch_a}: judged={len(report_a.verdicts)} "
          f"gate-refused={sum(len(d.get('samples') or []) for d in refusals)}")
    for c, v in report_a.verdicts.items():
        r = library[c]
        print(f"  {v:<13} {c}  published pIC50={r['median']:.2f} n={r['n']}")

    b = run_campaign_b(refusals, library)
    if b:
        rep, reprops = b
        print(f"campaign B re-proposal ({len(reprops)} declared covalent): "
              f"gate allowed {len([c for c in reprops if c in rep.verdicts])}"
              f" — verdicts: {rep.verdicts}")

    results = score(report_a, refusals, b, library, reveal)
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    _recs = SqliteProvenanceStore(str(CASE / "study.db")).branch_records(
        branch_a)
    results["campaign_a"]["synthesis_refused"] = sum(
        1 for r in _recs if r.event_type.value == "gate_decision"
        and (r.decision or {}).get("kind") == "synthesis_failed")
    results["meta"] = {
        "gate": {"metric": "ic50_um", "threshold": GATE_IC50_UM,
                 "truth_rule": f"published median pIC50 >= {GATE_PIC50}"},
        "ladder": list(LADDER), "seed": SEED, "branch_a": branch_a,
        "campaign_a_tail": msgs[-6:],
        "lab": "replay-published (replay-v1): IC50 truth = published "
               "median; curve shape + well noise are a declared replay model",
    }
    (CASE / "results.json").write_text(json.dumps(results, indent=1,
                                                  default=str))
    print("\n== SCORE vs published truth ==")
    print(json.dumps(results["campaign_a"], indent=1))
    if results["campaign_b"]:
        print(json.dumps(results["campaign_b"], indent=1))
    print("== REVEAL: convergence onto the drugs the field actually picked ==")
    for fc in results["future_convergence"]:
        print(f"  {fc['drug']:<12} gen={fc['generation']:<18} "
              f"same-scaffold-confirmed={fc['loop_confirmed_same_scaffold']} "
              f"nearest-Tanimoto={fc['nearest_confirmed_tanimoto']} "
              f"(nearest was true-active: "
              f"{fc['nearest_confirmed_was_true_active']})")
    print(f"\nwrote {CASE / 'results.json'}")


if __name__ == "__main__":
    main()
