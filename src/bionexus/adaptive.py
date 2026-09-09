"""Adaptive dose-series design — sequential decision-making under uncertainty.

A fixed 0.5/2/10/40 µM series wastes wells whenever the true IC50 sits
between points (or outside the range). DoseDesigner keeps a grid posterior
over log IC50 under the Hill response model r(c) = Rmax / (1 + K/c) + noise,
and picks each next dose where the current posterior is most uncertain —
maximum expected information per well.

Offline, deterministic, dependency-free. This is the mechanism; the eval
task `adaptive-dose-design` is the claim.
"""
from __future__ import annotations

import math
import random
from typing import Iterable


class DoseDesigner:
    def __init__(self, rmax: float = 500.0, sigma: float = 15.0,
                 k_lo: float = 0.1, k_hi: float = 200.0, n_grid: int = 60,
                 doses: tuple[float, ...] = (0.25, 0.5, 1.0, 2.0, 5.0,
                                             10.0, 20.0, 40.0, 80.0),
                 first_dose: float = 2.0):
        self.rmax = rmax
        self.sigma = sigma
        self.doses = list(doses)
        self.grid = [math.exp(math.log(k_lo) +
                              (math.log(k_hi) - math.log(k_lo)) * i / (n_grid - 1))
                     for i in range(n_grid)]
        self.post = [1.0 / n_grid] * n_grid
        self.used: list[float] = []
        self.first_dose = first_dose

    # -- belief updates ------------------------------------------------------

    def _pred(self, k: float, conc: float) -> float:
        return self.rmax / (1.0 + k / max(conc, 1e-9))

    def observe(self, conc: float, response: float) -> None:
        self.used.append(conc)
        lik = [math.exp(-0.5 * ((response - self._pred(k, conc)) / self.sigma) ** 2)
               for k in self.grid]
        raw = [p * l for p, l in zip(self.post, lik)]
        total = sum(raw)
        if total <= 0:                       # numerically impossible obs
            return
        self.post = [x / total for x in raw]

    # -- decision --------------------------------------------------------------

    def _predictive_spread(self, conc: float) -> float:
        preds = [self._pred(k, conc) for k in self.grid]
        mean = sum(p * w for p, w in zip(preds, self.post))
        return sum(w * (p - mean) ** 2 for p, w in zip(preds, self.post))

    def next_dose(self) -> float | None:
        """The unused dose whose response most splits the current posterior."""
        avail = [d for d in self.doses if d not in self.used]
        if not avail:
            return None
        if not self.used:
            return self.first_dose
        return max(avail, key=self._predictive_spread)

    # -- readout ---------------------------------------------------------------

    def estimate(self) -> tuple[float, tuple[float, float]]:
        """Posterior median IC50 and 95% credible interval."""
        cdf, acc = [], 0.0
        for w in self.post:
            acc += w
            cdf.append(acc)
        q = lambda p: self.grid[min(len(cdf) - 1,
                                    next(i for i, c in enumerate(cdf) if c >= p))]
        return q(0.5), (q(0.025), q(0.975))

    def entropy(self) -> float:
        return -sum(w * math.log(w) for w in self.post if w > 0)


def run_adaptive_series(true_ic50: float, rmax: float, sigma: float,
                        n_wells: int, rng: random.Random,
                        designer: DoseDesigner | None = None) -> tuple:
    """Simulate an adaptive experiment; returns (estimate, ci, wells_used)."""
    d = designer or DoseDesigner(rmax=rmax, sigma=sigma)
    for _ in range(n_wells):
        c = d.next_dose()
        if c is None:
            break
        r = rmax / (1.0 + true_ic50 / max(c, 1e-9)) + rng.gauss(0, sigma)
        d.observe(c, max(0.0, r))
    est, ci = d.estimate()
    return est, ci, len(d.used)


def run_fixed_series(true_ic50: float, rmax: float, sigma: float,
                     doses: Iterable[float], rng: random.Random) -> tuple:
    """The incumbent: fixed series + the same grid-posterior estimator
    (generous to the baseline — it gets the best possible fit of its data)."""
    d = DoseDesigner(rmax=rmax, sigma=sigma, doses=tuple(doses))
    for c in doses:
        r = rmax / (1.0 + true_ic50 / max(c, 1e-9)) + rng.gauss(0, sigma)
        d.observe(c, max(0.0, r))
    est, ci = d.estimate()
    return est, ci, len(d.used)
