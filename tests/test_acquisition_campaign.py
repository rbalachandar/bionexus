"""bo-ei acquisition wired into the real campaign loop: AD-gated picks,
the 'why this plate' record on the provenance branch, determinism, and the
score/policy path left untouched when acquisition is off."""
from bionexus.adapters.lab.simulator import SimulatorLab
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.autoloop import CampaignConfig, run_campaign
from bionexus.core.hypothesis import Constraint, ProblemStatement
from bionexus.flywheel import Flywheel

# AD1 has the BEST predicted IC50 (2.0) but is extrapolation — EI must
# refuse it; the batch should be the in-domain low values H1/H2/H3.
SPECS = [("AD1", 2.0, True), ("H1", 5.0, False), ("H2", 8.0, False),
         ("H3", 11.0, False), ("M1", 90.0, False)]


def _cfg(tmp_path, autonomy="observe", acquisition="bo-ei", seed=7):
    specs = [{"statement": f"{c} binds", "candidate": c,
              "assay_type": "binding", "predicted": f"{pv} uM",
              "predicted_value": pv,
              "metadata": {"predicted_sd": 0.2, "extrapolation": ad,
                           "ad_note": "nn-Tanimoto 0.3 < 0.5" if ad else ""}}
             for c, pv, ad in SPECS]
    problem = ProblemStatement(
        objective="find IC50<=20", constraints=[
            Constraint(name="potency", description="IC50", kind="hard",
                       limit=20.0, unit="uM")])
    return CampaignConfig(problem=problem, hypotheses=specs, k=3, rounds=1,
                          autonomy=autonomy, inbox=str(tmp_path),
                          poll_secs=0.05, acquisition=acquisition, seed=seed,
                          flywheel=Flywheel(":memory:"))


def _acq_record(store, report):
    for r in store.branch_records(f"problem/{report.problem_id}"):
        if (r.decision or {}).get("kind") == "acquisition_selection":
            return r.decision
    return None


def test_ad_outsider_vetoed_despite_best_mean(tmp_path):
    store = SqliteProvenanceStore()
    report = run_campaign(_cfg(tmp_path), SimulatorLab(seed=3), store)
    assert "AD1" not in report.selected          # best mean, still refused
    assert set(report.selected) == {"H1", "H2", "H3"}
    rec = _acq_record(store, report)
    assert rec and rec["policy"] == "bo-ei"
    assert {p["candidate"] for p in rec["picks"]} == {"H1", "H2", "H3"}
    veto = next(r for r in rec["refusals"] if r["candidate"] == "AD1")
    assert "extrapolation-veto" in veto["reason"]


def test_selection_lands_on_provenance_branch(tmp_path):
    store = SqliteProvenanceStore()
    report = run_campaign(_cfg(tmp_path), SimulatorLab(seed=3), store)
    rec = _acq_record(store, report)
    assert rec["k"] == 3 and rec["target"] == 20.0
    # every pick carries its arithmetic and reason (the audit answer)
    assert all("acquisition=" in p["reason"] for p in rec["picks"])


def test_determinism_same_seed_same_batch(tmp_path):
    s1 = SqliteProvenanceStore()
    s2 = SqliteProvenanceStore()
    r1 = run_campaign(_cfg(tmp_path, seed=99), SimulatorLab(seed=3), s1)
    r2 = run_campaign(_cfg(tmp_path, seed=99), SimulatorLab(seed=3), s2)
    assert r1.selected == r2.selected


def test_off_by_default_uses_score_path(tmp_path):
    # acquisition="" must not emit an acquisition_selection record
    store = SqliteProvenanceStore()
    report = run_campaign(_cfg(tmp_path, acquisition=""), SimulatorLab(3),
                          store)
    assert _acq_record(store, report) is None
    assert len(report.selected) == 3          # score selection still runs


def test_no_posterior_candidates_are_refused_not_invented(tmp_path):
    # a candidate with no predicted_value: EI cannot rank it, says so
    cfg = _cfg(tmp_path)
    cfg.hypotheses.append({"statement": "X binds", "candidate": "X",
                           "assay_type": "binding", "predicted": "unknown"})
    store = SqliteProvenanceStore()
    report = run_campaign(cfg, SimulatorLab(seed=3), store)
    rec = _acq_record(store, report)
    xr = next(r for r in rec["refusals"] if r["candidate"] == "X")
    assert "no declared posterior" in xr["reason"]
    assert "X" not in report.selected


def test_views_round_attaches_selection(tmp_path):
    from bionexus import views
    store = SqliteProvenanceStore()
    report = run_campaign(_cfg(tmp_path), SimulatorLab(seed=3), store)
    recs = store.branch_records(f"problem/{report.problem_id}")
    rounds = views._rounds_with_verdicts(recs)
    sel = rounds[0].get("selection")
    assert sel and sel["policy"] == "bo-ei"
    assert {p["candidate"] for p in sel["picks"]} == {"H1", "H2", "H3"}
    assert any(r["candidate"] == "AD1" for r in sel["refusals"])
