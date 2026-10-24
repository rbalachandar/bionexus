"""acquisition — EI math, the AD gate, determinism, diversity, baseline."""
from bionexus.acquisition import (Posterior, expected_improvement,
                                  POLICY_NAME, randomize_batch, select_batch)


def _pool():
    # two clean hits, one borderline, one confident miss, one AD-outside
    # "hit". metric_log=True so every sd is on the LOG10 axis (a fold, not
    # a µM): sd=0.2 ≈ ±1.6x. A confident miss carries SMALL sd -> EI ~0.
    return [
        Posterior(candidate="H1", mean=2.0, sd=0.2),
        Posterior(candidate="H2", mean=5.0, sd=0.2),
        Posterior(candidate="B1", mean=19.0, sd=0.2),   # borderline at gate 20
        Posterior(candidate="M1", mean=80.0, sd=0.2),   # confidently high
        Posterior(candidate="AD1", mean=1.0, sd=0.2, in_domain=False,
                  ad_note="nn-Tanimoto 0.31 < floor"),
    ]


# ------------------------------------------------------------------- EI math

def test_ei_point_posterior_is_plain_improvement():
    assert expected_improvement(2.0, None, 20.0, "min") == 18.0
    assert expected_improvement(80.0, None, 20.0, "min") == 0.0   # never negative


def test_ei_sd_widens_toward_the_gate():
    # a uncertain candidate straddling the gate has higher EI than a certain
    # point below it by the same mean distance — uncertainty buys option value
    sure = expected_improvement(18.0, 0.1, 20.0, "min")
    fuzzy = expected_improvement(18.0, 3.0, 20.0, "min")
    assert fuzzy > sure


def test_ei_direction_max_flips():
    assert expected_improvement(90.0, None, 50.0, "max") == 40.0
    assert expected_improvement(10.0, None, 50.0, "max") == 0.0


# -------------------------------------------------------------- AD gate

def test_ad_outside_is_refused_never_picked():
    sel = select_batch(_pool(), k=6, target=20.0, direction="min")
    picked = {p.candidate for p in sel.picks}
    assert "AD1" not in picked
    refusal = next(r for r in sel.refusals if r.candidate == "AD1")
    assert "extrapolation-veto" in refusal.reason
    assert "0.31 < floor" in refusal.reason   # AD note carried through


# -------------------------------------------------------------- ordering

def test_best_confident_candidate_first():
    sel = select_batch(_pool(), k=1, target=20.0, direction="min")
    assert sel.picks[0].candidate == "H1"     # lowest IC50, low sd


def test_batch_respects_k_and_budgets_the_rest_as_refusals():
    sel = select_batch(_pool(), k=2, target=20.0)
    assert len(sel.picks) == 2
    assert any(r.reason.startswith("outside batch") for r in sel.refusals)


def test_diversity_cap_limits_one_family():
    pool = [Posterior(candidate=f"F{i}", mean=1.0 + i * 0.1, sd=0.1,
                      family="same") for i in range(5)]
    pool.append(Posterior(candidate="G0", mean=3.0, sd=0.1, family="other"))
    sel = select_batch(pool, k=3, target=20.0, max_per_family=1)
    fams = {p.candidate for p in sel.picks}
    assert len([c for c in fams if c.startswith("F")]) == 1  # capped
    assert "G0" in fams


def test_point_posterior_is_labelled_exploit_only():
    pool = [Posterior(candidate="X", mean=5.0, sd=None)]
    sel = select_batch(pool, k=1, target=20.0)
    assert "point-posterior" in sel.picks[0].reason


# -------------------------------------------------------------- determinism

def test_same_inputs_same_selection():
    a = select_batch(_pool(), k=2, target=20.0, seed=7)
    b = select_batch(_pool(), k=2, target=20.0, seed=7)
    assert [p.candidate for p in a.picks] == [p.candidate for p in b.picks]
    assert [p.acquisition for p in a.picks] == [p.acquisition for p in b.picks]


def test_direction_max_selects_high_values():
    pool = [Posterior(candidate="lo", mean=10.0, sd=1.0),
            Posterior(candidate="hi", mean=95.0, sd=1.0)]
    sel = select_batch(pool, k=1, target=90.0, direction="max",
                       metric_log=False)
    assert sel.picks[0].candidate == "hi"


def test_no_target_falls_back_to_raw_axis_ranking():
    sel = select_batch(_pool(), k=1, target=None, best_observed=None)
    assert "no target" in sel.note
    assert sel.picks[0].candidate == "AD1" or sel.refusals  # AD still vetoes
    assert "AD1" not in {p.candidate for p in sel.picks}


# -------------------------------------------------------------- baseline

def test_randomize_is_deterministic_and_ad_respecting():
    a = randomize_batch(_pool(), k=2, seed=1, skip_out_of_domain=True)
    b = randomize_batch(_pool(), k=2, seed=1, skip_out_of_domain=True)
    assert [p.candidate for p in a.picks] == [p.candidate for p in b.picks]
    assert a.picks[0].acquisition == 0.0        # never ranks
    assert "AD1" not in {p.candidate for p in a.picks}


def test_decision_payload_is_chain_ready():
    sel = select_batch(_pool(), k=2, target=20.0, round_no=3, seed=2)
    d = sel.decision_payload()
    assert d["kind"] == "acquisition_selection"
    assert d["policy"] == POLICY_NAME
    assert d["round"] == 3
    assert set(d["picks"][0]) >= {"candidate", "acquisition", "reason"}
