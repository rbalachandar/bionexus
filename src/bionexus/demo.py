"""bn demo — onboarding that engineers THE moment (S-T2).

Scientists adopt pre-registration discipline at the speed they feel it
save them. This demo runs a curated, scripted campaign THROUGH THE REAL
MACHINERY (HypothesisTracker, SimulatorLab, AutoAnalysisAgent orthogonal
confirmation, CI-aware verdicts, hash-chained provenance) so that the
first screen shows the two moments no competitor ships:

  BORDER  — IC50 with a 95% CI straddling the gate: the system ABSTAINS,
            visibly, and abstains again when the second method agrees
            on the number but not the decision.
  FALSER  — a clean-looking preliminary hit (4.9 uM, CI well under the
            gate) that the orthogonal method DISAGREES with: REFUTED,
            on the record, with the comparison and the rule used.

Numbers are simulated (seeded — the same demo every run) and labeled
simulated. The discipline they demonstrate is the production discipline.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

DEMO_GATE_UM = 10.0
DEMO_SEED = 19
DEMO_SMILES = {
    "WINNER": "Cc1ccc(NC(=O)c2ccc(O)cc2)cc1",
    "FALSER": "COc1ccc(NC(=O)c2ccccc2F)cc1",
    "BORDER": "Cc1cccc(NC(=O)c2ccc(F)cc2)c1",
}
EXPECTED = {"WINNER": "confirmed", "FALSER": "refuted", "BORDER": "inconclusive"}


def _campaign_config():
    from bionexus.autoloop import CampaignConfig
    from bionexus.core.hypothesis import Constraint, ProblemStatement

    problem = ProblemStatement(
        objective="SER-DEMO: three compounds, one gate (IC50 <= 10 uM), "
                  "pre-registered before measurement",
        constraints=[Constraint(name="potency", description="<= 10 uM",
                                kind="hard", limit=DEMO_GATE_UM, unit="uM")])
    hyps = [{"statement": f"{c} inhibits the demo target", "candidate": c,
             "assay_type": "binding", "predicted": "<= 10",
             "predicted_value": DEMO_GATE_UM, "rationale": "demo (simulated)",
             "mechanism": "reversible binding",
             "refutation_condition": f"orthogonal method disagrees (no CI "
                                      f"overlap) or IC50 CI sits above "
                                      f"{DEMO_GATE_UM} uM",
             "citation": "demo — no real prior art claimed",
             "smiles": smi}
            for c, smi in DEMO_SMILES.items()]
    return CampaignConfig(
        problem=problem, hypotheses=hyps, k=3, rounds=1, autonomy="act",
        concentrations=["0.1uM", "0.3uM", "1uM", "3uM", "10uM"],
        inbox=tempfile.mkdtemp(prefix="bionexus-demo-"), poll_secs=0.02)


def _moments(recs) -> dict[str, Any]:
    """Pull the two engineered moments + the hero out of the chain —
    straight from provenance decisions, not the in-memory report."""
    out: dict[str, Any] = {}
    prelim: dict[str, dict] = {}
    for r in recs:
        d = r.decision or {}
        cand = d.get("candidate") or (
            (r.artifact.metadata if r.artifact else {}) or {}).get("candidate")
        v = d.get("verdict")
        if not cand or not v:
            continue
        obs = d.get("observed") or d.get("ic50_um")
        ci = d.get("observed_ci") or d.get("ic50_ci")
        if cand == "BORDER" and "abstain" not in out and ci \
                and ci[0] < DEMO_GATE_UM < ci[1]:
            out["abstain"] = {"candidate": cand, "observed_uM": obs,
                              "ci95": list(ci), "gate_uM": DEMO_GATE_UM}
        if cand == "FALSER":
            conf = d.get("confirmation") or {}
            if v == "validated" and "fake_hit" not in prelim:
                prelim["fake_hit"] = {"observed_uM": obs, "ci95": list(ci)}
            if v == "refuted" and conf:
                out["refutation"] = {
                    "candidate": cand, "rule": conf.get("rule"),
                    "primary_uM": conf.get("primary_ic50"),
                    "secondary_uM": conf.get("secondary_ic50"),
                    "agreed": conf.get("agreed"),
                    "preliminary": prelim.get("fake_hit", {})}
        if cand == "WINNER" and v == "confirmed":
            out["hero"] = {"observed_uM": obs, "ci95": list(ci)}
    return out


def run_demo(db_path: str | Path | None = None,
             html_path: str | Path | None = None,
             echo: bool = False) -> dict[str, Any]:
    """Execute the scripted campaign. Chain lands in db_path (default
    .data/demo.db, overwritten fresh); diary HTML optional. Returns
    {verdicts, moments, branch, records, db, chain_ok, lines}."""
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.autoloop import run_campaign
    from bionexus.paths import DATA_DIR

    db = Path(db_path) if db_path else DATA_DIR / "demo.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.unlink(missing_ok=True)          # idempotent: the demo is stateless
    store = SqliteProvenanceStore(str(db))
    lines: list[str] = []
    rep = run_campaign(_campaign_config(), SimulatorLab(seed=DEMO_SEED),
                       store,
                       notify=(lambda m: (lines.append(str(m)),
                                          print(f"  [demo] {m}")
                                          if echo else None)))
    branch = f"problem/{rep.problem_id}"
    recs = store.branch_records(branch)
    moments = _moments(recs)
    verdicts = dict(rep.verdicts)
    chain_problems = store.verify_chain(branch)

    if html_path:
        from bionexus.diary import build_diary_html
        p = Path(html_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(build_diary_html(recs, branch))

    return {"verdicts": verdicts, "moments": moments, "branch": branch,
            "records": len(recs), "db": str(db),
            "chain_ok": not chain_problems,
            "lines": [l for l in lines if l.strip()],
            "simulated": True,
            "narration": narration(verdicts, moments)}


def narration(verdicts: dict, moments: dict) -> list[str]:
    """The story beat — what to point at first."""
    out: list[str] = []
    ab = moments.get("abstain")
    if ab:
        out.append(
            f"BORDER measured IC50 {ab['observed_uM']:.2f} uM, 95% CI "
            f"{ab['ci95'][0]:.2f}-{ab['ci95'][1]:.2f} uM — the interval "
            f"straddles the {ab['gate_uM']:.0f} uM gate, so the system "
            "ABSTAINS: \"we do not claim this\". And it abstains AGAIN when "
            "the orthogonal method agrees on the number but not the decision.")
    rf = moments.get("refutation")
    if rf:
        pre = rf.get("preliminary", {})
        out.append(
            f"FALSER looked like a hit ({pre.get('observed_uM', 0):.2f} uM, "
            f"CI {pre.get('ci95', [0, 0])[0]:.2f}-{pre.get('ci95', [0, 0])[1]:.2f} "
            f"uM) — the kind of number that gets a slide. The orthogonal "
            f"method read {rf['secondary_uM']:.2f} uM; intervals do not "
            f"overlap (rule: {rf['rule']}), so the preliminary call was "
            "REFUTED — on the record, with the comparison kept.")
    if verdicts.get("WINNER") == "confirmed":
        out.append("WINNER: both methods inside the gate with overlapping "
                   "CIs — CONFIRMED. That is the whole pitch: agree -> "
                   "claim, disagree -> kill, unsure -> abstain. All "
                   "hash-chained (bn prove the branch).")
    return out
