"""Applicability domain (Trust-T2 / Bender audit T0): the local-model guard.

Every piece here is the same epistemics as the CS06 regime gate, moved
from the DATA side to the MODEL side: claim inside what has been earned,
refuse outside it, and stamp which case happened.
"""
import pytest

from bionexus.ad import AD_FLOOR, ApplicabilityDomain, tanimoto
from bionexus.benchmark import CharRidgePolicy
from bionexus.core.hypothesis import SuccessCriteria

ALIPHATICS = ["CCO", "CCCO", "CCCCO", "CCCCO", "CCN", "CCCN"]
FAR = ["c1ccccc1O", "NCC(=O)NC(=O)CN", "O=S(=O)(N)c1ccc2ccccc2c1"]


def test_tanimoto_set_similarity():
    assert tanimoto({1, 2, 3}, {1, 2, 3}) == 1.0
    assert tanimoto({1, 2}, {3, 4}) == 0.0
    assert tanimoto(set(), set()) == 1.0          # both-empty: equal, not free
    assert tanimoto(set(), {1}) == 0.0            # missing never matches


def test_ad_basics_char_basis():
    ad = ApplicabilityDomain.from_smiles(ALIPHATICS, basis="char3")
    near = ad.check("CCCCO")
    assert near["extrapolation"] is False
    assert near["nn_tanimoto"] == 1.0
    for s in FAR:
        st = ad.check(s)
        assert st["extrapolation"] is True, s
        assert st["nn_tanimoto"] < AD_FLOOR
    assert ad.check("")["extrapolation"] is True   # empty never in-domain
    assert ad.check("???")["extrapolation"] is True
    assert ad.basis == "char3"
    assert len(ad) == len(set(ALIPHATICS))


def test_ad_stamp_fields_present():
    ad = ApplicabilityDomain.from_smiles(ALIPHATICS, basis="char3")
    payload = ad.stamp({"value": 1.2}, "O=S(=O)(N)c1ccc2ccccc2c1")
    assert payload["extrapolation"] is True
    assert payload["nn_tanimoto"] < AD_FLOOR
    assert payload["ad_floor"] == AD_FLOOR
    assert payload["ad_basis"] == "char3"
    assert payload["ad_n_reference"] == len(set(ALIPHATICS))
    assert payload["value"] == 1.2                 # payload untouched


def test_morgan_basis_when_rdkit_present():
    pytest.importorskip("rdkit")
    ad = ApplicabilityDomain.from_smiles(["c1ccccc1O", "Cc1ccccc1O",
                                          "COc1ccccc1O"], basis="morgan")
    assert ad.basis == "morgan"
    assert ad.check("c1ccccc1O")["extrapolation"] is False   # exact
    assert ad.check("Cc1ccccc1O")["extrapolation"] is False  # cresol neighbor
    # the declared floor is deliberately conservative: a same-ring but
    # differently-substituted query MAY abstain — never the reverse
    assert ad.check("NCCCCCCCCCCC(=O)N")["extrapolation"] is True


def test_classify_veto_is_two_directional():
    crit = SuccessCriteria(metric="ic50_um", direction="min", threshold=25.0)
    # claim-grade verdicts die outside the domain, in BOTH directions...
    assert crit.classify(10.0, None, extrapolation=True) == "inconclusive"
    assert crit.classify(40.0, None, extrapolation=True) == "inconclusive"
    # ...but default behavior is untouched (lab observations are not models)
    assert crit.classify(10.0, None) == "validated"
    assert crit.classify(40.0, None) == "invalidated"


def test_policy_stamps_survive_prediction():
    train = [(s, 2.0 * len(s)) for s in ALIPHATICS] + \
            [("CC" * k, float(k)) for k in range(1, 5)]
    pol = CharRidgePolicy()
    pol.fit(train)
    val, ad = pol.predict_with_ad("CCCCO")
    assert isinstance(val, float)
    assert ad["extrapolation"] is False
    assert ad["ad_basis"] == "char3"
    _, ad_far = pol.predict_with_ad("c1ccc2ccccc2c1")
    assert ad_far["extrapolation"] is True


def test_views_card_chip_from_extrapolation():
    """A verdict record carrying the extrapolation stamp must surface on
    the pipeline card: status text mentions it, verdict dict flags it."""
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    from bionexus.views import pipeline_cards

    store = SqliteProvenanceStore(":memory:")
    env = Envelope(experiment_branch_id="problem/p-ad")
    store.append(record_for(env, EventType.hypothesis_proposed,
                            system_actor("t"),
                            decision={"hypothesis_id": "h-1",
                                      "candidate": "X",
                                      "statement": "X binds",
                                      "predicted": "<= 25",
                                      "criteria": {"metric": "ic50_um",
                                                  "direction": "min",
                                                  "threshold": 25.0}}))
    store.append(record_for(env, EventType.hypothesis_inconclusive,
                            system_actor("t"),
                            decision={"hypothesis_id": "h-1",
                                      "candidate": "X",
                                      "verdict": "inconclusive",
                                      "observed": 3.0,
                                      "extrapolation": True}))
    cards = pipeline_cards(store.branch_records("problem/p-ad"))
    card = next(c for c in cards if c["candidate"] == "X")
    assert card["verdict"]["extrapolation"] is True
    assert "extrapolation" in card["stage"]


# ------------------------------------------------------ auto (quantile) floors

def test_auto_floor_gives_declared_false_alarm_rate():
    """LOO-NN quantile floor: by construction ~q of domain members are
    'far from their nearest sibling' -> leave-one-out flag rate ≈ q."""
    fam = ["CC" + "C" * i + "O" for i in range(8)]          # tight family
    dom = ApplicabilityDomain.from_smiles(fam + ["c1ccccc1I",
                                                 "NCCCCCCCCCCCCC(=O)N"],
                                          basis="char3", floor="auto",
                                          loo_quantile=0.25)
    assert dom.floor_mode == "auto" and 0 < dom.floor <= 0.5
    # every real family member queries near-identical siblings
    for s in fam[2:-1]:
        assert dom.check(s)["extrapolation"] is False
    assert dom.check("NCCCCCCOP(=O)(O)O")["extrapolation"] is True
    stamp = dom.check("c1ccccc1Cl")
    assert stamp["floor_mode"] == "auto" and "p25" in stamp["floor_basis"]


def test_fixed_default_unchanged_and_stamp_discloses():
    dom = ApplicabilityDomain.from_smiles(["CCO", "CCCO"], basis="char3")
    st = dom.check("CCCCO")
    assert st["ad_floor"] == 0.5 and st["floor_mode"] == "fixed"
