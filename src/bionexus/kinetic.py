"""Kinetic matching for multi-step biochemical assembly (split inteins, etc.).

From the protein editing literature (Hua et al., Science 2025): when two
sequential splicing reactions run at mismatched rates, the reaction partitions
between a concerted pathway and a stepwise one, and hemi-spliced intermediates
accumulate. Deliberately slowing one component (e.g. mut-Cfa) restores
synchronisation.

This module encodes that principle as a reusable check for any experiment
involving multi-step biochemical assembly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


@dataclass
class KineticProfile:
    """Rate constants for one component of a multi-step reaction."""
    component_name: str
    splicing_rate_per_sec: float | None = None   # k_splice
    association_rate_per_molar_sec: float | None = None  # k_on
    dissociation_constant_nM: float | None = None  # K_D
    half_life_sec: float | None = None
    source: str = ""  # where this data comes from (paper, measurement, estimate)


@dataclass
class KineticMatchResult:
    compatible: bool
    rate_ratio: float                    # faster_rate / slower_rate
    interpretation: str
    details: str


def check_kinetic_match(
    a: KineticProfile,
    b: KineticProfile,
    max_ratio: float = 10.0,
) -> KineticMatchResult:
    """Check whether two components' splicing rates are matched.

    Rule (from Hua et al.): if the ratio of the two rate constants exceeds
    ~10x, the slower step becomes rate-limiting and hemi-spliced intermediates
    accumulate. The fix is to slow the faster component (e.g. M75L/M81L
    mutations) so both clocks keep time.

    Returns compatible=False when the ratio exceeds max_ratio.
    """
    if a.splicing_rate_per_sec is None or b.splicing_rate_per_sec is None:
        return KineticMatchResult(
            compatible=True, rate_ratio=1.0,
            interpretation="rate data not available; cannot check",
            details="no splicing rates provided — skipping kinetic match check")

    fast = max(a.splicing_rate_per_sec, b.splicing_rate_per_sec)
    slow = min(a.splicing_rate_per_sec, b.splicing_rate_per_sec)
    if slow <= 0:
        return KineticMatchResult(
            compatible=True, rate_ratio=float("inf"),
            interpretation="invalid rate (zero or negative)",
            details=f"non-positive rate: {slow}")

    ratio = fast / slow
    if ratio <= max_ratio:
        return KineticMatchResult(
            compatible=True, rate_ratio=round(ratio, 2),
            interpretation="matched",
            details=f"rate ratio {ratio:.2f}x (limit {max_ratio}x)")
    return KineticMatchResult(
        compatible=False, rate_ratio=round(ratio, 2),
        interpretation=f"mismatched by {ratio:.0f}x — expect intermediate accumulation",
        details=f"{a.component_name} k={a.splicing_rate_per_sec} vs "
                f"{b.component_name} k={b.splicing_rate_per_sec}; "
                f"ratio {ratio:.1f}x exceeds limit {max_ratio}x")


class InteinPairConfig(BaseModel):
    """Declared intein pair for a protein-editing experiment."""
    n_intein: str
    c_intein: str
    n_splicing_rate: float | None = None
    c_splicing_rate: float | None = None
    is_engineered_slow_variant: bool = False
    notes: str = ""


def check_intein_pair(pair: InteinPairConfig) -> KineticMatchResult:
    """Check a declared intein pair for kinetic compatibility."""
    if pair.n_splicing_rate is None or pair.c_splicing_rate is None:
        return KineticMatchResult(
            compatible=True, rate_ratio=1.0,
            interpretation="rates not declared; cannot check",
            details="no splicing rates provided for either intein domain")
    a = KineticProfile(component_name=pair.n_intein,
                       splicing_rate_per_sec=pair.n_splicing_rate)
    b = KineticProfile(component_name=pair.c_intein,
                       splicing_rate_per_sec=pair.c_splicing_rate)
    return check_kinetic_match(a, b, max_ratio=10.0)
