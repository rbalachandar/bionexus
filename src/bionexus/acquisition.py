"""acquisition — deterministic, AD-gated batch selection ("which experiments
run").

The campaign loop always had a socket for this (round-2+ policy slot);
this is the first real plug. The framing is honest about what it is: a
closed-form expected-improvement acquisition over DECLARED posteriors —
the posterior (mean ± sd) is supplied by whoever ran the surrogate, the
AD module decides whether a candidate may be chosen at all, and the
harness layer (safety, budget, diversity, approval) still vetoes every
pick. Nothing here fits a model; nothing here clears a refusal.

Why EI and not a GP library: at DMTA batch scale (tens of candidates,
k of 4–8) EI-over-CI behaves like the Bayesian-dosing module behaves on
wells — graded, deterministic, explainable — while a GP over fingerprints
would smuggle in exactly the unvalidated ranking the CS07/CS08 negatives
warned about.

Determinism: identical posteriors + params + seed => identical `Selection`.
"""
from __future__ import annotations

import hashlib
import math
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict

POLICY_NAME = "bo-ei"
POLICY_VERSION = 1


class Posterior(BaseModel):
    """One candidate's DECLARED predictive posterior on the metric scale.

    For "min" metrics whose good values span orders of magnitude (IC50 µM),
    mean/sd are interpreted on the log10 scale by the acquisition — sd is
    OPTIONAL: no fabricated uncertainty, a missing sd is an explicit
    point-posterior and is labeled as such in the pick reason.
    """
    model_config = ConfigDict(extra="forbid")

    candidate: str
    mean: float
    sd: float | None = None
    family: str | None = None
    in_domain: bool = True
    ad_note: str = ""            # why an AD stamp fired, when it did
    source: str = "declared"     # surrogate | flywheel | declared


class Pick(BaseModel):
    candidate: str
    acquisition: float
    mean: float
    sd: float | None = None
    reason: str


class Refusal(BaseModel):
    candidate: str
    reason: str


class Selection(BaseModel):
    policy: str = POLICY_NAME
    policy_version: int = POLICY_VERSION
    seed: int = 0
    round: int = 1
    k: int = 0
    target: float | None = None          # threshold or best-observed, on scale
    direction: Literal["min", "max"] = "min"
    picks: list[Pick] = Field(default_factory=list)
    refusals: list[Refusal] = Field(default_factory=list)
    note: str = ""

    def decision_payload(self) -> dict:
        """JSON-ready for the provenance chain — every pick and every
        refusal, with the arithmetic worded out."""
        return {
            "kind": "acquisition_selection", "policy": self.policy,
            "policy_version": self.policy_version, "seed": self.seed,
            "round": self.round, "k": self.k, "target": self.target,
            "direction": self.direction,
            "picks": [p.model_dump() for p in self.picks],
            "refusals": [r.model_dump() for r in self.refusals],
            "note": self.note,
        }


def _normal_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def expected_improvement(mean: float, sd: float | None, target: float,
                         direction: str = "min") -> float:
    """Closed-form EI: for "min" metrics improvement = (target - mean);
    for "max" it's (mean - target). sd None => point posterior: the
    improvement itself, never a silent Gaussian invention."""
    imp = (target - mean) if direction == "min" else (mean - target)
    if not sd or sd <= 0:
        return max(0.0, imp)
    z = imp / sd
    return max(0.0, imp * _cdf(z) + sd * _normal_pdf(z))


def _log_safe(v: float) -> float:
    return math.log10(v) if v > 0 else -6.0


def select_batch(posteriors: list[Posterior], k: int,
                 target: float | None = None,
                 best_observed: float | None = None,
                 direction: Literal["min", "max"] = "min",
                 metric_log: bool = True, seed: int = 0, round_no: int = 1,
                 max_per_family: int | None = 1,
                 explore_weight: float = 0.0) -> Selection:
    """Rank by EI(+kappa·sd when explore_weight>0), apply the diversity
    cap, return k picks. The AD gate runs BEFORE ranking: a candidate
    outside the surrogate's domain is refused, not "explored" — the
    infinite-exploration failure mode the applicability-domain module
    exists to stop.

    target: the decision gate a scientist registered. If absent, the
    acquisition improves on best_observed (the classic BO reference).
    """
    log = direction == "min" and metric_log
    ref: float | None = None
    if target is not None:
        ref = target
    elif best_observed is not None:
        ref = best_observed
    sel = Selection(seed=seed, round=round_no, k=k, target=ref,
                    direction=direction)
    if ref is None:
        sel.note = ("no target (gate) and no observation yet — EI has "
                    "nothing to improve on; falling back to raw posterior "
                    "ranking")

    def _to_axis(value: float) -> float:
        """project a raw metric value onto the good-is-LARGER axis: log10
        for span metrics (so IC50 sd reads as multiplicative fold), sign
        flipped so a LOWER IC50 (direction=min) is a LARGER axis value."""
        v = _log_safe(value) if log else value
        return v if direction == "max" else -v

    def _to_axis_post(p: Posterior) -> tuple[float, float | None]:
        m = _to_axis(p.mean)
        s = p.sd if (p.sd is not None and p.sd > 0) else None
        return m, s

    axis_ref = None if ref is None else _to_axis(ref)
    scored: list[tuple[float, Posterior, float, float | None]] = []
    for p in posteriors:
        if not p.in_domain:
            sel.refusals.append(Refusal(
                candidate=p.candidate,
                reason=(f"extrapolation-veto (AD): selection outside the "
                        f"surrogate's domain is refused exploration"
                        + (f" — {p.ad_note}" if p.ad_note else ""))))
            continue
        m, s = _to_axis_post(p)
        if axis_ref is None:
            val = m + explore_weight * (s or 0.0)
        else:
            # on the good-is-larger axis, improvement over target is "max"
            ei = expected_improvement(m, s, axis_ref, direction="max")
            val = ei + explore_weight * (s or 0.0)
        scored.append((val, p, m, s))
    # stable, deterministic ordering: value desc, then candidate asc
    scored.sort(key=lambda t: (-round(t[0], 9), t[1].candidate))

    fam_counts: dict[str, int] = {}
    for val, p, m, s in scored:
        if len(sel.picks) >= k:
            sel.refusals.append(Refusal(candidate=p.candidate,
                                        reason="outside batch (budget)"))
            continue
        if (max_per_family is not None and p.family
                and fam_counts.get(p.family, 0) >= max_per_family):
            sel.refusals.append(Refusal(
                candidate=p.candidate,
                reason=f"family '{p.family}' already has {max_per_family} "
                       f"selected (diversity cap)"))
            continue
        reason = (f"acquisition={round(val, 4)}; "
                  + ("point-posterior, no sd declared (exploit-only)"
                     if s is None
                     else f"mean={round(p.mean, 4)}, sd={round(p.sd, 4)}"))
        sel.picks.append(Pick(candidate=p.candidate,
                              acquisition=round(val, 6),
                              mean=round(p.mean, 6),
                              sd=round(p.sd, 6) if s is not None else None,
                              reason=reason))
        if p.family:
            fam_counts[p.family] = fam_counts.get(p.family, 0) + 1
    if not sel.picks and not sel.note:
        sel.note = "nothing selectable — every candidate refused (see refusals)"
    return sel


def randomize_batch(posteriors: list[Posterior], k: int, seed: int = 0,
                    round_no: int = 1,
                    max_per_family: int | None = 1,
                    skip_out_of_domain: bool = False) -> Selection:
    """The interim champion, spelled out so the comparison is apples to
    apples: gates + randomize, never rank. AD gate is still applied when
    skip_out_of_domain (the campaign's real behaviour keeps it)."""
    sel = Selection(policy="gates-random", policy_version=1, seed=seed,
                    round=round_no, k=k)
    # deterministic shuffle, not python's RNG ordering luck
    shuffled = sorted(posteriors, key=lambda p: hashlib.sha256(
        f"{seed}:{p.candidate}".encode()).hexdigest())
    fam_counts: dict[str, int] = {}
    for p in shuffled:
        if not p.in_domain and skip_out_of_domain:
            sel.refusals.append(Refusal(
                candidate=p.candidate, reason="extrapolation-veto (AD)"))
            continue
        if len(sel.picks) >= k:
            sel.refusals.append(Refusal(candidate=p.candidate,
                                        reason="outside batch (budget)"))
            continue
        if (max_per_family is not None and p.family
                and fam_counts.get(p.family, 0) >= max_per_family):
            sel.refusals.append(Refusal(
                candidate=p.candidate,
                reason=f"family '{p.family}' capped"))
            continue
        sel.picks.append(Pick(candidate=p.candidate, acquisition=0.0,
                              mean=round(p.mean, 6), sd=p.sd,
                              reason="uniform batch pick (gates+randomize)"))
        if p.family:
            fam_counts[p.family] = fam_counts.get(p.family, 0) + 1
    return sel
