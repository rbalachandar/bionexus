"""Single source of truth for the dose-response curve model.

Every IC50 path (the plate-reader fit, the adaptive dose designer, the
simulators, the eval generators) uses the SAME forward model — a logistic in
log10(conc) with slope fixed at 1 and bottom at 0:

    r(c) = rmax / (1 + IC50 / c)

— and the same search window, so two entry points cannot disagree about
what an IC50 means or where "out of range" begins.
"""
from __future__ import annotations

import math
from typing import Any

# IC50 search window (log10 uM): 0.001 .. ~316 uM. A fit pinned at either
# edge is a range statement ("<=" / ">"), never a measured IC50.
GRID_LOG_LO = -3.0
GRID_LOG_HI = 2.5
GRID_FLOOR_UM = 10 ** GRID_LOG_LO
GRID_CEIL_UM = 10 ** GRID_LOG_HI


def hill_response(conc: float, ic50: float, rmax: float = 100.0,
                  eps: float = 1e-9) -> float:
    """Response at `conc` for the slope-1 / bottom-0 model. `eps` only guards
    conc=0 (simulators historically use 1e-6; the fit uses 1e-9)."""
    return rmax / (1.0 + ic50 / max(conc, eps))


# two-sided 95% Student-t critical values, indexed by degrees of freedom
_T975 = {2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
         8: 2.306}


def replicate_ci(values: list[float | None], seed: int = 7,
                 n_boot: int = 200) -> tuple[float, float] | None:
    """Bootstrap CI (95%) of the MEAN over replicate well readings at one
    dose. This is how a property metric (potency_pct, tensile MPa, t_half)
    gets an interval: well-level variance, same abstention rule as the
    Hill IC50. Returns None below 3 usable wells — a single reading has
    no measurable spread, and inventing one is not honesty. Below 10
    wells the interval is a Student-t one (the bootstrap under-covers)."""
    vals = [v for v in values if isinstance(v, (int, float))]
    if len(vals) < 3:
        return None
    xs = [float(v) for v in vals]
    if len(xs) < 10:
        # small n: a percentile bootstrap badly under-covers (n=3 has only
        # 10 distinct resamples) -> Student-t interval of the mean instead
        n = len(xs)
        mean = sum(xs) / n
        sd = (sum((x - mean) ** 2 for x in xs) / (n - 1)) ** 0.5
        half = _T975[n - 1] * sd / n ** 0.5
        return (round(mean - half, 4), round(mean + half, 4))
    from proef.benchmark import bootstrap_ci
    lo, hi = bootstrap_ci(xs, n_boot=n_boot, seed=seed)
    return (lo, hi)


def _spearman(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")

    def rank(x):
        order = sorted(range(n), key=lambda i: x[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and x[order[j + 1]] == x[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def classify_curve(pts: list[tuple[float, float]]) -> dict[str, Any]:
    """qHTS-lite SHAPE taxonomy (registered, blind; a documented
    simplification of the class taxonomies NCATS/Incyte screening floors
    use — monotonic sigmoids vs flat vs noisy vs falling).

    WHY shape, not numbers, in self-normalized frames: those tables had
    their plate references divided out before deposition, so the 50%-of-
    what line is undefined — but affine re-normalization preserves
    monotonicity, span structure, and WITHIN-CURVE midpoints. So the only
    honest claims available there are relative: is there a
    concentration-dependent rise (RISE-*), is the 50%-of-span crossing
    inside the window (a midpoint AC50-estimate in µM), or is this a
    flatline artifact / falling curve our physics rejects? These
    claims CANNOT become IC50s — that would smuggle a frame back in.
    """
    pts = sorted(pts)
    vals = [v for _, v in pts]
    if len(pts) < 4:
        return {"class": "insufficient", "trend": None, "span": None,
                "midpoint_uM": None}
    lo, hi = min(vals), max(vals)
    span = hi - lo
    trend = _spearman([c for c, _ in pts], vals)
    out: dict[str, Any] = {"class": "", "trend": round(trend, 2),
                           "span": round(span, 1), "midpoint_uM": None}
    if span < 25:
        out["class"] = "flat"          # no response (or floor-pinned artifact)
        return out
    if trend <= -0.4:
        out["class"] = "falling"       # opposite of inhibition physics
        return out
    if trend < 0.4:
        out["class"] = "noisy"         # not concentration dependent
        return out
    mid = lo + 0.5 * span
    n_below = sum(1 for v in vals if v < mid)
    n_above = len(vals) - n_below
    if n_below >= 2 and n_above >= 2:
        for (c0, v0), (c1, v1) in zip(pts, pts[1:]):
            if v0 < mid <= v1 and v1 > v0:
                out["midpoint_uM"] = round(
                    c0 + (c1 - c0) * (mid - v0) / (v1 - v0), 5)
                break
        out["class"] = "rise-complete"  # full S inside the window
    elif min(vals) >= mid:
        out["class"] = "rise-partial-low"  # every dose past mid: potent
                                           # below the measured window
    else:
        out["class"] = "rise-partial-high"  # hasn't reached mid by top dose
    return out



def _hill_sse(log_ic50: float, pts: list[tuple[float, float]],
              max_response: float) -> float:
    ic50 = 10 ** log_ic50
    sse = 0.0
    for c, v in pts:
        pred = hill_response(c, ic50, max_response)
        sse += (v - pred) ** 2
    return sse


def _hill_fit_params(pts: list[tuple[float, float]],
                     max_response: float | None
                     ) -> tuple[float, float] | None:
    """Least-squares Hill fit by grid search, refined once.

    max_response given  -> 2-param fit (IC50 only).
    max_response None   -> 3-param fit: the plateau is ALSO unknown, so we
      grid-search the max multiplier over the observed top response (1x–4x).
      Pretending the observed max is the true max biases IC50 toward the
      potent side — the classic right-censoring trap.
    Returns (IC50 in µM, fitted top) or None."""
    import math

    if len(pts) < 2:
        return None
    top = max(v for _, v in pts)
    if top <= 0:
        return None
    lo, hi = GRID_LOG_LO, GRID_LOG_HI       # 0.001 – ~316 µM
    n = 60
    step = (hi - lo) / n
    if max_response is None:                # 3-param: unknown plateau
        mults = [1.0 + 3.0 * j / 12 for j in range(13)]        # 1x .. 4x
        best = (None, None, float("inf"))
        for m in mults:
            for i in range(n + 1):
                g = lo + step * i
                s = _hill_sse(g, pts, top * m)
                if s < best[2]:
                    best = (g, m, s)
        if best[0] is None:
            return None
        g0, m0, sse0 = best
        for m in [max(1.0, m0 - 0.25 + 0.5 * k / 4) for k in range(5)]:
            for i in range(-8, 9):
                g = g0 + i * step / 8
                s = _hill_sse(g, pts, top * m)
                if s < sse0:
                    sse0, g0, m0 = s, g, m
        return 10 ** g0, top * m0
    if max_response <= 0:
        return None
    best, best_sse = None, float("inf")
    for i in range(n + 1):
        g = lo + step * i
        s = _hill_sse(g, pts, max_response)
        if s < best_sse:
            best, best_sse = g, s
    for i in range(-8, 9):                   # refine
        g = best + i * step / 8
        s = _hill_sse(g, pts, max_response)
        if s < best_sse:
            best, best_sse = g, s
    if best_sse >= float("inf"):
        return None
    return 10 ** best, max_response


def _hill_fit_ic50(pts: list[tuple[float, float]],
                   max_response: float | None) -> float | None:
    """IC50 (µM) of the least-squares Hill fit, or None."""
    fit = _hill_fit_params(pts, max_response)
    return fit[0] if fit else None


def hill_fit(points: list[tuple[float, float]],
             max_response: float | None = 100.0) -> dict[str, float] | None:
    """{ic50, top} of the slope-1 / bottom-0 fit — what a plot needs to draw
    the fitted curve (top is the known maximum, or the fitted plateau)."""
    pts = sorted((c, v) for c, v in points if v is not None)
    fit = _hill_fit_params(pts, max_response)
    return {"ic50": fit[0], "top": fit[1]} if fit else None


def fit_ic50(points: list[tuple[float, float]], max_response: float = 100.0) -> float | None:
    """IC50 from (conc, response) points — Hill fit, with legacy linear
    interpolation (in log10 conc) as the fallback for sparse data."""
    import math
    pts = sorted((c, v) for c, v in points if v is not None)
    if len(pts) < 2:
        return None
    hill = _hill_fit_ic50(pts, max_response)
    if hill is not None and len(pts) >= 3:
        return round(hill, 3)
    if max_response is None:
        return None  # 3-param declined (or too few points) -> honest censoring
    target = max_response / 2.0
    for (c0, v0), (c1, v1) in zip(pts, pts[1:]):
        if min(v0, v1) <= target <= max(v0, v1):
            frac = 0.0 if v1 == v0 else (target - v0) / (v1 - v0)
            if c0 > 0 and c1 > 0:
                # dose-response is ~linear in log10(conc), not in conc
                lc = math.log10(c0) + frac * (math.log10(c1) - math.log10(c0))
                return round(10 ** lc, 3)
            return round(c0 + frac * (c1 - c0), 3)
    return None  # right-censored within this concentration range


def fit_ic50_ci(points: list[tuple[float, float]], max_response: float = 100.0,
                n_boot: int = 300, seed: int = 7) -> dict[str, float] | None:
    """Residual bootstrap CI for the Hill IC50.

    Refits on resampled residuals around the fitted curve; returns
    {ic50, ci_low, ci_high} (95%, log-scale percentiles) or None.
    Deterministic given the seed — reproducible verdicts, same as everything
    else in Proef.
    """
    import math
    import random

    pts = sorted((c, v) for c, v in points if v is not None)
    if len(pts) < 3 or (max_response is not None and max_response <= 0):
        return None
    base = _hill_fit_ic50(pts, max_response)
    if base is None:
        return None
    rng = random.Random(seed)
    boots: list[float] = []
    if max_response is None:
        # residual bootstrap around the best 3-param fit, at its implied max
        top = max(v for _, v in pts)
        mults = [1.0 + 3.0 * j / 12 for j in range(13)]
        best_m = min(mults, key=lambda m: _hill_sse(math.log10(base), pts,
                                                    top * m))
        fitted = [hill_response(c, base, top * best_m) for c, _ in pts]
    else:
        fitted = [hill_response(c, base, max_response) for c, _ in pts]
    # df-corrected residuals: raw residuals of a fitted curve understate the
    # noise by sqrt((n-p)/n); with 3-5 points that is a large optimism
    n_par = 1 if max_response is not None else 2
    scale = (len(pts) / max(1, len(pts) - n_par)) ** 0.5
    residuals = [(v - f) * scale for (_, v), f in zip(pts, fitted)]
    for _ in range(n_boot):
        sample = [(c, max(0.0, f + rng.choice(residuals)))
                  for (c, _v), f in zip(pts, fitted)]
        est = _hill_fit_ic50(sample, max_response)
        if est:
            boots.append(math.log10(est))
    if len(boots) < 30:                      # too few successful refits
        return {"ic50": round(base, 3), "ci_low": None, "ci_high": None,
                "method": "hill-no-ci"}
    boots.sort()
    q = lambda p: boots[max(0, min(len(boots) - 1, int(p * (len(boots) - 1))))]
    return {"ic50": round(base, 3), "ci_low": round(10 ** q(0.025), 3),
            "ci_high": round(10 ** q(0.975), 3), "method": "hill-bootstrap"}


def std_dev(values: list[float]) -> float:
    """Sample standard deviation (n-1 denominator). NOT a Z'-factor —
    the old name invited that mistake; the plate QC heuristic lives in
    analyze_records and is labeled there."""
    import math

    if len(values) < 2:
        return float("nan")
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)
