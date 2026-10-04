"""S-T1.1 chemotype/SAR series view: grouping, honest rollups, CI'd pairs."""
import pytest

from bionexus.series import build_series, chemotype_key, matched_pairs, series_summary

B1 = "Cc1ccc(NC(=O)c2ccccc2)cc1"      # acetanilide benzanilide
B2 = "COc1ccc(NC(=O)c2ccccc2)cc1"     # one O further: same Murcko scaffold
B3 = "CS(=O)(=O)NC(=O)c1ccccc1"       # different scaffold


def test_chemotype_grouping_and_backend_stamp():
    s = build_series([
        {"candidate": "A", "smiles": B1, "verdict": "confirmed"},
        {"candidate": "B", "smiles": B2, "verdict": "refuted"},
        {"candidate": "C", "smiles": B3, "verdict": "inconclusive"},
        {"candidate": "D", "smiles": "", "verdict": "validated"},
    ])
    assert [k for k, v in s.items() if v["kind"] == "chemotype:Murcko"
            and v["n_members"] == 2], "A+B share a Murcko chemotype"
    ab = next(v for v in s.values() if v["n_members"] == 2)
    assert {m["candidate"] for m in ab["members"]} == {"A", "B"}
    assert ab["label"] == "1 confirmed, 1 refuted, 0 preliminary, 0 abstained"
    assert ab["chemotype_backend"] in ("rdkit-Murcko", "none(exact-id fallback)")
    ungrouped = [v for v in s.values() if v["kind"] == "ungrouped"]
    assert any(v["members"][0]["candidate"] == "D" for v in ungrouped)


def test_family_hook_is_modality_agnostic():
    s = build_series([
        {"candidate": "ab-1", "family": "anti-CD20", "verdict": "confirmed"},
        {"candidate": "ab-2", "family": "anti-CD20", "verdict": "confirmed"},
    ])
    assert len(s) == 1
    ser = next(iter(s.values()))
    assert ser["kind"] == "family" and ser["n_members"] == 2


def test_matched_pair_calls_cover_all_four_verdicts():
    def mk(cand, obs, ci=None):
        return {"candidate": cand, "smiles": B1, "verdict": "confirmed",
                "observed": obs, "ci": ci}

    def one_pair(a, b, cia=None, cib=None):
        ser = build_series([mk("A", a, cia), mk("B", b, cib)])
        return matched_pairs(next(iter(ser.values())))[0]

    p = one_pair(1.0, 30.0)
    assert p["call"] == "gain" and p["fold_a_over_b"] == pytest.approx(1 / 30, rel=0.01)
    assert p["ci95"] is None and p["cited_cis"] is False  # point-only, DISCLOSED

    p = one_pair(1.0, 1.6, [0.8, 1.25], [1.3, 2.0])
    assert p["call"] == "retained" and p["cited_cis"] is True

    p = one_pair(1.0, 30.0, [0.8, 1.25], [24.0, 37.0])
    assert p["call"] == "gain" and p["ci95"][1] < 0   # A stronger, CI says so

    # wide CI crossing the 3.2x boundary must ABSTAIN, not pick a side
    p = one_pair(1.0, 3.0, [0.5, 40.0], [1.0, 9.0])
    assert p["call"] == "abstained"


def test_abstentions_are_counted_never_averaged():
    s = build_series([
        {"candidate": c, "smiles": B1, "verdict": "inconclusive"}
        for c in ("A", "B", "C")])
    ser = next(iter(s.values()))
    assert ser["rollup"]["abstained"] == 3
    assert "3 abstained" in ser["label"]


def test_series_summary_from_campaign_chain():
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.autoloop import CampaignConfig, run_campaign
    from bionexus.core.hypothesis import Constraint, ProblemStatement
    from bionexus.views import series_view

    problem = ProblemStatement(objective="series view", constraints=[
        Constraint(name="potency", description="d", kind="hard", limit=60.0,
                   unit="uM")])
    hyps = [{"statement": f"{c} binds", "candidate": c,
             "assay_type": "binding", "predicted": "<= 60",
             "predicted_value": 60.0, "rationale": "t", "smiles": smi}
            for c, smi in (("SAR-1", B1), ("SAR-2", B2), ("SAR-3", B3))]
    cfg = CampaignConfig(problem=problem, hypotheses=hyps, k=3, rounds=1,
                         autonomy="act", inbox=".data/inbox-series",
                         poll_secs=0.05)
    store = SqliteProvenanceStore(":memory:")
    rep = run_campaign(cfg, SimulatorLab(seed=5), store)
    recs = store.branch_records(f"problem/{rep.problem_id}")

    out = series_view(recs)          # the workbench read-model shape
    assert out and all({"rollup", "members", "kind", "backend",
                        "matched_pairs"} <= set(o) for o in out)
    chem = [o for o in out if o["kind"] == "chemotype:Murcko"]
    assert any(o["n_members"] == 2 for o in chem)   # SAR-1 + SAR-2 grouped
    tot = {k: sum(o["rollup"][k] for o in out)
           for k in ("confirmed", "refuted", "preliminary", "abstained",
                     "proposed")}
    assert sum(tot.values()) == 3     # every hypothesis counted once
    assert tot["proposed"] == 1       # SAR-1 refused at Make, still VISIBLE
    assert chem and all(c["n_members"] < 3 for c in chem)

    from bionexus.diary import build_diary_html
    html = build_diary_html(recs, f"problem/{rep.problem_id}")
    assert "Series view" in html and "grouping:" in html
    assert "SAR-" in html


# ---------------------------------------------------------------- S-T1.2
# series-level claims: verdicts DERIVED from members, abstention dominant


def _family_chain(kind="series", retain_fold=3.2):
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.hypothesis import (Constraint, HypothesisTracker,
                                          ProblemStatement)
    from bionexus.core.interfaces import record_for, system_actor

    store = SqliteProvenanceStore(":memory:")
    tr = HypothesisTracker(store, system_actor("t"))
    prob = ProblemStatement(objective="rb", constraints=[Constraint(
        name="potency", description="d", kind="hard", limit=60.0, unit="uM")])
    tr.define_problem(prob)
    branch = f"problem/{prob.problem_id}"
    tr.propose_families(prob, [{
        "family": "fam-rb", "parent_statement": "ring-B para-substitution "
        "retains potency <= 3.2x", "kind": kind, "retain_fold": retain_fold,
        "rationale": "r", "variants": [
            {"statement": "RB-1 binds", "candidate": "RB-1",
             "assay_type": "binding", "predicted": "<=60",
             "predicted_value": 60.0, "smiles": B1},
            {"statement": "RB-2 binds", "candidate": "RB-2",
             "assay_type": "binding", "predicted": "<=60",
             "predicted_value": 60.0, "smiles": B2}]}])
    recs = store.branch_records(branch)
    hids = {r.artifact.metadata["candidate"]: r.artifact.artifact_id
            for r in recs
            if r.event_type.value == "hypothesis_proposed" and r.artifact
            and (r.artifact.metadata or {}).get("candidate")}
    assert len(hids) == 2

    def verdict(cand, hid, v, obs=None, ci=None, claim=False):
        store.append(record_for(
            Envelope(experiment_branch_id=branch),
            EventType.hypothesis_validated, system_actor("t"),
            decision={"hypothesis_id": hid, "candidate": None if claim else cand,
                      "verdict": v, "observed": obs, "observed_ci": ci,
                      **({"claim_kind": "series-derived", "family_id": "fam-rb"}
                         if claim else {})}))
    return store, branch, verdict, dict(zip(("RB-1", "RB-2"), hids))


def resolve1(store, branch):
    from bionexus.series import resolve_series_claims
    out = resolve_series_claims(store.branch_records(branch))
    assert len(out) == 1
    return out[0]


def test_series_claim_lifecycle_is_derived_not_invented():
    store, branch, vd, H = _family_chain()
    r = resolve1(store, branch)
    assert r["status"] == "open" and r["derived"] is True

    vd("RB-1", H["RB-1"], "confirmed", 1.0, [0.8, 1.3])
    vd("RB-2", H["RB-2"], "confirmed", 1.5, [1.2, 1.9])
    r = resolve1(store, branch)
    assert r["status"] == "confirmed" and "retain" in r["reason"]

    vd("RB-2", H["RB-2"], "confirmed", 50.0, [40.0, 60.0])   # recency wins
    assert resolve1(store, branch)["status"] == "refuted"

    vd("RB-2", H["RB-2"], "inconclusive", 8.0, [0.5, 90.0])  # straddle
    r = resolve1(store, branch)
    assert r["status"] == "inconclusive" and "abstain" in r["reason"]
    assert len(r["derived_from"]) == 2     # claim verdict never self-inflates

    vd("fam-rb", "fam-rb", "refuted", claim=True)            # derived write
    r = resolve1(store, branch)
    assert len(r["derived_from"]) == 2     # excluded from membership


def test_mechanistic_family_rollup_abstains_when_members_do():
    store, branch, vd, H = _family_chain(kind="mechanistic")
    vd("RB-1", H["RB-1"], "confirmed", 1.0, None)
    r = resolve1(store, branch)
    assert r["status"] == "inconclusive"       # one member unresolved
    vd("RB-2", H["RB-2"], "confirmed", 9.0, None)
    assert resolve1(store, branch)["status"] == "confirmed"
    vd("RB-2", H["RB-2"], "inconclusive", 9.0, None)
    assert resolve1(store, branch)["status"] == "inconclusive"
    vd("RB-2", H["RB-2"], "refuted", 9.0, None)
    assert resolve1(store, branch)["status"] == "refuted"


def test_family_series_rows_carry_claim_status_in_summary():
    from bionexus.series import series_summary
    store, branch, vd, H = _family_chain()
    vd("RB-1", H["RB-1"], "confirmed", 1.0, [0.8, 1.3])
    vd("RB-2", H["RB-2"], "confirmed", 1.5, [1.2, 1.9])
    ss = series_summary(store.branch_records(branch))
    fam = [x for x in ss if x["kind"] == "family"]
    assert fam and fam[0]["claim_status"] == "confirmed"
    assert "3.2x" in fam[0]["claim_reason"]
    # family hook WINS over chemotype: every member sits in exactly one
    # series — no double counting across views
    assert sum(x["n_members"] for x in ss) == 2


def test_no_family_claims_yields_no_derivation():
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.series import resolve_series_claims
    st = SqliteProvenanceStore(":memory:")
    assert resolve_series_claims(st.branch_records("problem/none")) == []
