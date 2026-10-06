"""Slot allocation: greedy farthest-first over aa k-mer similarity.

Test slots are the scarce resource (adaptyv comp: 100s of slots against
1000s of designs). Diversity-first selection spends them on DISTINCT
solutions; a pure score-ranking spends them on N copies of whatever the
ranker likes (CS07 replay: the rankers we have are worse than random).
"""
from __future__ import annotations
from typing import Callable, Iterable


def _jaccard(a: set[int], b: set[int]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def select_diverse(items: list[tuple[str, set[int]],], n: int,
                   must_pass: Callable[[str], bool] | None = None) -> list[str]:
    """Farthest-first traversal: start from the most-connected item (safe
    anchor), repeatedly add the item least similar to everything chosen."""
    cand = [k for k in items if not must_pass or must_pass(k)]
    if n <= 0 or not cand:
        return []
    picks: list[str] = []
    chosen_sets: list[set[int]] = []
    # anchor: largest kmer set == broadest chemistry surface
    first = max(cand, key=lambda kv: len(kv[1]))
    picks.append(first[0]); chosen_sets.append(first[1])
    while len(picks) < n and len(picks) < len(cand):
        best_id, best_sim = None, 2.0
        for kid, ks in cand:
            if kid in picks:
                continue
            sim = max(_jaccard(ks, c) for c in chosen_sets)
            if sim < best_sim:
                best_id, best_sim = kid, sim
        if best_id is None:
            break
        picks.append(best_id)
        chosen_sets.append(dict(cand)[best_id])
    return picks
