"""Eligibility + quality gates for an Adaptyv-style binder submission.

Deterministic, refuse-and-explain (the gateway doctrine applied to
sequences). Rules encode what Proteinbase competitions state: single-chain
proteins under 250 aa, sanity of composition, and NOT a near-copy of a
known binder (>=10-mutations-away, enforced here by k-mer containment —
a documented proxy, not an alignment).
"""
from __future__ import annotations

import re
from typing import Iterable

AA = set("ACDEFGHIKLMNPQRSTVWY")
MAX_LEN, MIN_LEN = 250, 40
MAX_FREE_CYS = 6          # >6 unpaired cysteines: misfolding magnet
MAX_HOMOPOLYMER = 10
NEAR_COPY_CONTAINMENT = 0.75   # >=75% of query 5-grams found in a known
                               # binder == too close (proxy for <10 muts)


def check_sequence(seq: str) -> dict:
    reasons = []
    n = len(seq)
    if not (MIN_LEN <= n <= MAX_LEN):
        reasons.append(f"length {n} outside [{MIN_LEN},{MAX_LEN}]")
    bad = set(seq) - AA
    if bad:
        reasons.append(f"non-standard residues: {''.join(sorted(bad))}")
    if re.search(rf"(.)\1{{{MAX_HOMOPOLYMER},}}", seq):
        reasons.append(f"homopolymer run > {MAX_HOMOPOLYMER}")
    if seq.count("C") > MAX_FREE_CYS:
        reasons.append(f"{seq.count('C')} cysteines > {MAX_FREE_CYS}")
    if "GGGGGGG" in seq or "PPPPPP" in seq:
        reasons.append("low-complexity linker-like repeat")
    return {"pass": not reasons, "reasons": reasons, "len": n}


def _kmers(s: str, k: int = 5) -> set[int]:
    return {hash(s[i:i + k]) & 0xFFFFFFFF for i in range(max(0, len(s) - k + 1))}


def too_close_to_binders(seq: str, binder_seqs: Iterable[str],
                        containment: float = NEAR_COPY_CONTAINMENT) -> bool:
    """Proxy for '<10 mutations from a known binder': if >=75% of this
    sequence's 5-mers appear in some known binder, call it a near-copy."""
    q = _kmers(seq)
    if not q:
        return True
    for b in binder_seqs:
        bk = _kmers(b)
        if bk and len(q & bk) / len(q) >= containment:
            return True
    return False
