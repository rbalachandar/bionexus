"""BoTorch GP posterior provider (optional extra).

The provider must be (a) genuinely optional — importing bionexus and the
default campaign path never touch botorch — and (b) deterministic: same
fit -> same (mean, sd), so a GP posterior can ride the reproducibility
story without breaking byte-exact replay.
"""
import importlib.util

import pytest

_HAS_BOTORCH = importlib.util.find_spec("botorch") is not None

TRAIN = ([("CCO", 3.0), ("CCN", 4.0), ("c1ccccc1", 7.0), ("CCCCO", 2.5),
          ("c1ccc2ccccc2c1", 8.1), ("CCCl", 2.0), ("C", 1.0), ("CC", 1.5),
          ("CCC", 1.8), ("c1ccncc1", 6.0), ("CCCO", 3.1), ("CCCC", 2.1)] * 5)


def test_import_does_not_require_botorch():
    # the module pulls torch/botorch lazily inside fit/predict, so importing
    # it (or bionexus) must not demand the extra — the minimal-core contract
    import bionexus.adapters.models.gp_policy as gp
    assert hasattr(gp, "GaussianProcessPolicy")


@pytest.mark.skipif(not _HAS_BOTORCH, reason="botorch not installed")
def test_gp_returns_mean_and_positive_sd():
    from bionexus.adapters.models.gp_policy import GaussianProcessPolicy
    gp = GaussianProcessPolicy(noise="fixed", lengthscale=64.0, seed=0)
    gp.fit(TRAIN)
    mu, sd = gp.predict_with_sd("c1ccc2c(c1)ccc1ccccc12")   # far: big PAH
    mu2, sd2 = gp.predict_with_sd("CCO")                    # near a train pt
    assert mu == mu and sd > 0 and sd2 > 0                  # finite, sd positive
    assert sd > sd2                                         # uncertainty grows away from data


@pytest.mark.skipif(not _HAS_BOTORCH, reason="botorch not installed")
def test_gp_is_deterministic_for_a_seed():
    from bionexus.adapters.models.gp_policy import GaussianProcessPolicy
    a = GaussianProcessPolicy(noise="fixed", lengthscale=64.0, seed=0)
    a.fit(TRAIN)
    b = GaussianProcessPolicy(noise="fixed", lengthscale=64.0, seed=0)
    b.fit(TRAIN)
    assert a.predict_with_sd("c1ccncc1") == b.predict_with_sd("c1ccncc1")


@pytest.mark.skipif(not _HAS_BOTORCH, reason="botorch not installed")
def test_gp_exposes_ad_stamp_like_sklearn_policy():
    from bionexus.adapters.models.gp_policy import GaussianProcessPolicy
    gp = GaussianProcessPolicy(noise="fixed", seed=0)
    gp.fit(TRAIN)
    mu, stamp = gp.predict_with_ad("CCO")
    assert "extrapolation" in stamp and "nn_tanimoto" in stamp
